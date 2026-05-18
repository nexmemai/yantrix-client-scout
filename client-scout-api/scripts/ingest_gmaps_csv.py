#!/usr/bin/env python
"""Ingest a pre-scraped gosom/google-maps-scraper CSV through app services."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.gmaps_client import parse_gmaps_csv  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest a Google Maps scraper CSV into Client Scout.",
    )
    parser.add_argument("--file", required=True, help="CSV path inside the container or host process.")
    parser.add_argument("--niche", required=True, help="Business niche, e.g. dental.")
    parser.add_argument("--city", required=True, help='City label, e.g. "Sioux Falls".')
    parser.add_argument("--max-businesses", type=int, default=None, help="Optional cap on parsed rows to ingest.")
    parser.add_argument("--run-audit", action="store_true", help="Audit newly inserted businesses.")
    parser.add_argument("--run-score", action="store_true", help="Score newly inserted businesses after audit.")
    parser.add_argument("--run-pitches", action="store_true", help="Generate pitches for high/mid-fit scored leads.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    csv_path = Path(args.file)
    if not csv_path.exists() or not csv_path.is_file():
        print(f"ERROR: CSV file not found: {csv_path}", file=sys.stderr)
        return 2

    try:
        raw_csv = csv_path.read_text(encoding="utf-8-sig")
        parsed_businesses = parse_gmaps_csv(raw_csv)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: failed to parse CSV {csv_path}: {exc}", file=sys.stderr)
        return 2

    if not parsed_businesses:
        print(f"ERROR: CSV contained no business rows: {csv_path}", file=sys.stderr)
        return 2

    rows_parsed = len(parsed_businesses)
    raw_businesses = parsed_businesses
    if args.max_businesses is not None:
        if args.max_businesses <= 0:
            print("ERROR: --max-businesses must be greater than 0.", file=sys.stderr)
            return 2
        raw_businesses = raw_businesses[: args.max_businesses]

    job: DiscoveryJob | None = None
    started_at = datetime.now(tz=timezone.utc)

    try:
        from app.database import AsyncSessionLocal
        from app.models.job import DiscoveryJob
        from app.services.audit_worker import run_audit_for_business
        from app.services.discovery import ingest_raw_businesses
        from app.services.pitch_generator import generate_and_save_pitch
        from app.services.scoring import HIGH_FIT_BUCKET, MID_FIT_BUCKET, score_business

        pitchable_buckets = {HIGH_FIT_BUCKET, MID_FIT_BUCKET}

        async with AsyncSessionLocal() as db:
            job = DiscoveryJob(
                id=uuid.uuid4(),
                query=f"csv:{csv_path.name}:{args.niche} in {args.city}",
                city=args.city,
                niche=args.niche,
                source="csv",
                status="running",
                total_discovered=len(raw_businesses),
                started_at=started_at,
                created_at=started_at,
                updated_at=started_at,
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)

            ingest_result = await ingest_raw_businesses(
                raw_businesses=raw_businesses,
                niche=args.niche,
                db=db,
                discovery_job_id=job.id,
            )

            audited = 0
            scored = 0
            pitched = 0

            for business_id in ingest_result.inserted_ids:
                audit = None
                score_outcome = None

                if args.run_audit:
                    audit = await run_audit_for_business(business_id, db)
                    if audit and audit.status == "completed":
                        audited += 1

                if args.run_score:
                    if audit is None:
                        audit = await run_audit_for_business(business_id, db)
                    if audit and audit.status == "completed":
                        score_outcome = await score_business(business_id, db)
                        if score_outcome:
                            scored += 1

                if args.run_pitches:
                    if score_outcome is None:
                        score_outcome = await score_business(business_id, db)
                    if score_outcome and score_outcome.fit_bucket in pitchable_buckets:
                        await generate_and_save_pitch(business_id=business_id, db=db)
                        pitched += 1

            completed_at = datetime.now(tz=timezone.utc)
            job.status = "completed"
            job.total_discovered = ingest_result.raw_count
            job.total_audited = audited
            job.total_scored = scored
            job.completed_at = completed_at
            job.updated_at = completed_at
            await db.commit()

            print(
                "CSV ingest complete: "
                f"rows_parsed={rows_parsed} "
                f"rows_considered={ingest_result.raw_count} "
                f"new_businesses={len(ingest_result.inserted_ids)} "
                f"duplicates_skipped={ingest_result.duplicates_skipped} "
                f"audited={audited} scored={scored} pitched={pitched} "
                f"job_id={job.id}"
            )
            return 0

    except SQLAlchemyError as exc:
        await _mark_failed(job, str(exc))
        print(f"ERROR: database error during CSV ingest: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        await _mark_failed(job, str(exc))
        print(f"ERROR: CSV ingest failed: {exc}", file=sys.stderr)
        return 1


async def _mark_failed(job: DiscoveryJob | None, message: str) -> None:
    if job is None:
        return
    from app.database import AsyncSessionLocal
    from app.models.job import DiscoveryJob

    async with AsyncSessionLocal() as db:
        fresh = await db.get(DiscoveryJob, job.id)
        if fresh is None:
            return
        now = datetime.now(tz=timezone.utc)
        fresh.status = "failed"
        fresh.error_message = message[:2000]
        fresh.completed_at = now
        fresh.updated_at = now
        await db.commit()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
