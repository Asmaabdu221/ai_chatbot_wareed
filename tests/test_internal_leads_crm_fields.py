from __future__ import annotations

import uuid

from app.api.internal_leads import list_leads
from app.services.conversation_state import LeadDraft
from app.services.lead_service import create_lead_from_draft


def test_internal_leads_response_includes_crm_fields(db):
    draft = LeadDraft(
        phone="0502222233",
        conversation_id=str(uuid.uuid4()),
        latest_intent="ask_phone",
        summary_hint="crm fields",
    )
    lead = create_lead_from_draft(draft, db)
    assert lead is not None

    result = list_leads(q="0502222233", db=db)
    assert result.total >= 1
    row = result.items[0]
    assert hasattr(row, "crm_status")
    assert hasattr(row, "crm_provider")
    assert hasattr(row, "crm_external_id")
    assert hasattr(row, "crm_last_attempt_at")
    assert hasattr(row, "crm_error_message")
    assert hasattr(row, "crm_retry_count")
