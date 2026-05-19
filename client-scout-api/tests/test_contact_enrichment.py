from uuid import uuid4

import pytest

from app.models.business import Business
from app.services.contact_enrichment import (
    apply_contact_enrichment,
    enrich_contact_from_site,
)


@pytest.mark.asyncio
async def test_enrich_contact_from_homepage_html_extracts_person_contact():
    business = Business(id=uuid4(), name="Example Dental", source="google_maps")
    html = """
    <html>
      <body>
        <footer>
          Dr. Jane Smith - Owner
          <a href="mailto:jane@exampledental.com">Email</a>
          <a href="tel:+1 555 010 2222">Call</a>
          <a href="https://www.linkedin.com/in/janesmith">LinkedIn</a>
          Updated 2026
        </footer>
      </body>
    </html>
    """

    result = await enrich_contact_from_site(business, html, "https://exampledental.com")

    assert result.contact_name == "Jane Smith"
    assert result.contact_title == "Owner"
    assert result.contact_email == "jane@exampledental.com"
    assert result.contact_phone == "+1 555 010 2222"
    assert result.contact_linkedin_url == "https://www.linkedin.com/in/janesmith"
    assert result.contact_confidence == 90
    assert result.primary_language == "en"
    assert result.has_recent_updates is True


@pytest.mark.asyncio
async def test_apply_contact_enrichment_updates_business_fields():
    business = Business(id=uuid4(), name="Example Dental", source="google_maps")
    html = """
    <p>Owner - Jane Smith</p>
    <a href="mailto:jane@exampledental.com">Email</a>
    """

    result = await enrich_contact_from_site(business, html, "https://exampledental.com")
    apply_contact_enrichment(business, result)

    assert business.contact_name == "Jane Smith"
    assert business.contact_email == "jane@exampledental.com"
    assert business.contact_confidence == 90
