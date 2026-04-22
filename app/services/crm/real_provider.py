from __future__ import annotations

from app.services.crm.base import CRMProvider, CRMSyncResult


class RealCRMProviderPlaceholder(CRMProvider):
    provider_name = "real"

    def sync_lead(self, payload: dict) -> CRMSyncResult:
        return CRMSyncResult(
            ok=False,
            error_message="Real CRM provider is not implemented yet",
            raw_response={"provider": self.provider_name},
        )
