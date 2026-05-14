"""
services/snapshot_store.py — Store raw HTML snapshots for debugging.

Storage backends (configured via env vars):
  1. LOCAL (default): Writes to SNAPSHOT_DIR (default: ./snapshots/)
  2. S3 / MinIO: Set SNAPSHOT_BACKEND=s3 and configure S3_* env vars

The stored path is returned and saved in audits.screenshot_url for
later retrieval from the audit detail view.
"""

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


async def save_snapshot(
    business_id: str,
    url: str,
    html: str,
    html_hash: str,
) -> str | None:
    """
    Persist a raw HTML snapshot for a business audit.

    :param business_id: UUID string of the business being audited.
    :param url:         The URL that was audited.
    :param html:        The full raw HTML content.
    :param html_hash:   SHA-256 hex digest (avoids re-saving identical pages).
    :returns:           A string URI/path to the saved snapshot, or None on failure.
    """
    from app.config import get_settings
    settings = get_settings()

    backend = getattr(settings, "SNAPSHOT_BACKEND", "local").lower()

    if backend == "s3":
        return await _save_to_s3(business_id, url, html, html_hash, settings)
    else:
        return await _save_to_disk(business_id, html, html_hash, settings)


# ---------------------------------------------------------------------------
# Local disk backend
# ---------------------------------------------------------------------------


async def _save_to_disk(
    business_id: str,
    html: str,
    html_hash: str,
    settings,  # type: ignore[annotation-unchecked]
) -> str | None:
    """Save HTML to SNAPSHOT_DIR/<date>/<business_id>/<hash>.html"""
    import aiofiles

    snapshot_dir = Path(getattr(settings, "SNAPSHOT_DIR", "./snapshots"))
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    target_dir = snapshot_dir / date_str / business_id
    target_dir.mkdir(parents=True, exist_ok=True)

    file_path = target_dir / f"{html_hash[:16]}.html"

    # Skip if identical snapshot already saved
    if file_path.exists():
        logger.debug("Snapshot already exists: %s", file_path)
        return str(file_path)

    try:
        async with aiofiles.open(file_path, "w", encoding="utf-8", errors="replace") as f:
            await f.write(html)
        logger.info("Saved HTML snapshot: %s (%d bytes)", file_path, len(html))
        return str(file_path)
    except OSError as exc:
        logger.error("Failed to save snapshot to disk: %s", exc)
        return None


# ---------------------------------------------------------------------------
# S3 / MinIO backend
# ---------------------------------------------------------------------------


async def _save_to_s3(
    business_id: str,
    url: str,
    html: str,
    html_hash: str,
    settings,  # type: ignore[annotation-unchecked]
) -> str | None:
    """
    Upload HTML snapshot to S3 or MinIO.

    Required env vars:
      S3_ENDPOINT_URL  – MinIO: http://minio:9000 | AWS: leave blank
      S3_BUCKET        – e.g. "client-scout-snapshots"
      S3_ACCESS_KEY    – AWS access key / MinIO user
      S3_SECRET_KEY    – AWS secret / MinIO password
      S3_REGION        – e.g. "ap-south-1" (or "us-east-1" for MinIO)
    """
    import asyncio

    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    key = f"snapshots/{date_str}/{business_id}/{html_hash[:16]}.html"

    endpoint = getattr(settings, "S3_ENDPOINT_URL", None) or None
    bucket = getattr(settings, "S3_BUCKET", "client-scout-snapshots")
    access_key = getattr(settings, "S3_ACCESS_KEY", None)
    secret_key = getattr(settings, "S3_SECRET_KEY", None)
    region = getattr(settings, "S3_REGION", "ap-south-1")

    def _upload() -> str:
        kwargs: dict = dict(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        if endpoint:
            kwargs["endpoint_url"] = endpoint

        s3 = boto3.client("s3", **kwargs)
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=html.encode("utf-8", errors="replace"),
            ContentType="text/html; charset=utf-8",
            Metadata={"source-url": url[:512], "business-id": business_id},
        )
        return f"s3://{bucket}/{key}"

    try:
        # Run blocking boto3 call in thread executor
        uri = await asyncio.get_event_loop().run_in_executor(None, _upload)
        logger.info("Saved snapshot to S3: %s", uri)
        return uri
    except (BotoCoreError, ClientError) as exc:
        logger.error("Failed to upload snapshot to S3: %s", exc)
        return None
