from __future__ import annotations

from datetime import datetime, timezone

from app.services.crm.base import CRMProvider, CRMSyncResult


class DummyCRMProvider(CRMProvider):
    provider_name = "dummy"

    def sync_lead(self, payload: dict) -> CRMSyncResult:
        lead_id = str(payload.get("lead_id") or "unknown")
        external_id = f"dummy-{lead_id}-{int(datetime.now(timezone.utc).timestamp())}"
        return CRMSyncResult(
            ok=True,
            external_id=external_id,
            raw_response={"provider": self.provider_name, "accepted": True},
        )
