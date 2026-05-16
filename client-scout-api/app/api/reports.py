"""
api/reports.py - browser-safe HTML lead reports.
"""

import uuid
from html import escape

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.business import Business
from app.models.pitch import Pitch
from app.services.scoring import bucket_for_score

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get(
    "/{business_id}",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
    summary="Render the latest lead report as HTML",
)
async def get_report(
    business_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    result = await db.execute(
        select(Business)
        .options(selectinload(Business.audit), selectinload(Business.score))
        .where(Business.id == business_id)
    )
    business = result.scalar_one_or_none()
    if business is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found.")

    pitch = await _latest_pitch(business_id, db)
    html = _render_report(business, pitch)
    return HTMLResponse(content=html)


async def _latest_pitch(business_id: uuid.UUID, db: AsyncSession) -> Pitch | None:
    result = await db.execute(
        select(Pitch)
        .where(Pitch.business_id == business_id)
        .order_by(Pitch.generated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _render_report(business: Business, pitch: Pitch | None) -> str:
    score = business.score
    audit = business.audit
    bucket = bucket_for_score(score.overall_score) if score else "unscored"
    recommendations = _recommend_automations(audit, bucket)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(business.name)} - Yantrix Client Scout Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; color: #17202a; background: #f5f7fb; }}
    main {{ max-width: 920px; margin: 0 auto; padding: 32px 20px 48px; }}
    section {{ background: #fff; border: 1px solid #dce3ee; border-radius: 8px; padding: 20px; margin-top: 16px; }}
    h1, h2 {{ margin: 0 0 12px; }}
    h1 {{ font-size: 30px; }}
    h2 {{ font-size: 18px; }}
    dl {{ display: grid; grid-template-columns: 160px 1fr; gap: 8px 14px; margin: 0; }}
    dt {{ color: #5c6b7a; font-weight: 700; }}
    dd {{ margin: 0; }}
    ul {{ margin: 8px 0 0; padding-left: 22px; }}
    .score {{ font-size: 34px; font-weight: 700; }}
    .muted {{ color: #5c6b7a; }}
    .pitch {{ white-space: pre-wrap; line-height: 1.5; }}
  </style>
</head>
<body>
<main>
  <h1>{escape(business.name)}</h1>
  <p class="muted">Yantrix Client Scout report</p>
  <section>
    <h2>Business Basics</h2>
    <dl>
      <dt>Niche</dt><dd>{_value(business.niche or business.category)}</dd>
      <dt>City</dt><dd>{_value(business.city)}</dd>
      <dt>Website</dt><dd>{_link(business.website_url)}</dd>
      <dt>Source</dt><dd>{_value(business.source)}</dd>
      <dt>Phone</dt><dd>{_value(business.phone)}</dd>
    </dl>
  </section>
  <section>
    <h2>Audit Findings</h2>
    {_audit_html(audit)}
  </section>
  <section>
    <h2>Score Breakdown</h2>
    {_score_html(score, bucket)}
  </section>
  <section>
    <h2>Current Pitch</h2>
    <div class="pitch">{escape(pitch.pitch_notes) if pitch else "No pitch generated yet."}</div>
  </section>
  <section>
    <h2>Recommended Automations</h2>
    <ul>{"".join(f"<li>{escape(item)}</li>" for item in recommendations)}</ul>
  </section>
</main>
</body>
</html>"""


def _audit_html(audit) -> str:
    if audit is None:
        return "<p>No audit has been completed for this business yet.</p>"
    signals = [
        ("Website detected", audit.has_website, "A public website was found." if audit.has_website else "No public website was found."),
        ("SSL valid", audit.ssl_valid, "The site uses HTTPS." if audit.ssl_valid else "The site may not be secured with HTTPS."),
        ("Mobile friendly", audit.mobile_friendly, "The site appears usable on mobile." if audit.mobile_friendly else "Mobile usability needs attention."),
        ("Lead forms", audit.has_forms, "A form is available." if audit.has_forms else "No clear form was detected."),
        ("Booking", audit.has_booking, "Online booking is available." if audit.has_booking else "No booking flow was detected."),
        ("WhatsApp", audit.has_whatsapp, "WhatsApp contact is available." if audit.has_whatsapp else "WhatsApp capture is missing."),
        ("Chatbot", audit.has_chatbot, "Chat support is available." if audit.has_chatbot else "No chatbot was detected."),
    ]
    return "<ul>" + "".join(
        f"<li><strong>{escape(label)}:</strong> {escape(explanation)}</li>"
        for label, _value_bool, explanation in signals
    ) + "</ul>"


def _score_html(score, bucket: str) -> str:
    if score is None:
        return "<p>No score has been generated yet.</p>"
    return f"""
    <div class="score">{score.overall_score}/100</div>
    <p><strong>Bucket:</strong> {escape(bucket)}</p>
    <dl>
      <dt>Website quality</dt><dd>{_value(score.website_quality)}</dd>
      <dt>Online presence</dt><dd>{_value(score.online_presence)}</dd>
      <dt>Conversion readiness</dt><dd>{_value(score.conversion_readiness)}</dd>
      <dt>Urgency</dt><dd>{_value(score.urgency)}</dd>
    </dl>"""


def _recommend_automations(audit, bucket: str) -> list[str]:
    recommendations: list[str] = []
    if audit is None or not audit.has_forms:
        recommendations.append("Lead capture form connected to CRM follow-up")
    if audit is None or not audit.has_whatsapp:
        recommendations.append("WhatsApp inquiry automation with quick replies")
    if audit is None or not audit.has_booking:
        recommendations.append("Online booking and appointment reminders")
    if audit is None or not audit.has_chatbot:
        recommendations.append("Website chatbot for missed-call and FAQ capture")
    if bucket in {"high-fit", "mid-fit"}:
        recommendations.append("CRM pipeline sync with weekly lead reports")
    return recommendations[:5]


def _value(value) -> str:
    if value is None or value == "":
        return "Not available"
    return escape(str(value))


def _link(url: str | None) -> str:
    if not url:
        return "Not available"
    safe_url = escape(url, quote=True)
    return f'<a href="{safe_url}" rel="noopener noreferrer">{safe_url}</a>'
