from __future__ import annotations

from app.core.config import settings
from app.services.crm.base import CRMProvider
from app.services.crm.dummy_provider import DummyCRMProvider
from app.services.crm.real_provider import RealCRMProviderPlaceholder


def get_crm_provider() -> CRMProvider:
    provider = (settings.CRM_PROVIDER or "dummy").strip().lower()
    if provider == "dummy":
        return DummyCRMProvider()
    return RealCRMProviderPlaceholder()
