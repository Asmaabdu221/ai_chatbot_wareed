from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class CRMSyncResult:
    ok: bool
    external_id: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


class CRMProvider(ABC):
    provider_name: str = "base"

    @abstractmethod
    def sync_lead(self, payload: Dict[str, Any]) -> CRMSyncResult:
        raise NotImplementedError
