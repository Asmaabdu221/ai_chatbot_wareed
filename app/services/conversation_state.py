"""
Conversation State Layer.

Shared conversation state machine backed by Redis, tracked per conversation_id.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_EVICT_AFTER_SECONDS = settings.CONVERSATION_STATE_TTL_SECONDS
_KEY_PREFIX = "conversation_state:"


class StateEnum(str, Enum):
    IDLE = "idle"
    AWAITING_PHONE = "awaiting_phone"
    PHONE_RECEIVED = "phone_received"
    HUMAN_HELP_OFFERED = "human_help_offered"
    READY_FOR_TRANSFER = "ready_for_transfer"


@dataclass
class LeadDraft:
    """
    Snapshot of a captured lead. Created when phone is received.
    Ready for CRM export in Phase 3.
    """

    phone: str
    conversation_id: str
    latest_intent: str
    summary_hint: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "ready"


@dataclass
class ConversationState:
    """Mutable per-conversation state object."""

    conversation_id: str
    state: StateEnum = StateEnum.IDLE
    pending_action: str = ""
    pending_intent_summary: str = ""
    phone: Optional[str] = None
    lead_draft: Optional[LeadDraft] = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationStateStore:
    """Redis-backed conversation state store."""

    def __init__(self) -> None:
        if not settings.REDIS_URL:
            raise RuntimeError(
                "REDIS_URL must be configured for shared conversation state persistence."
            )
        self._redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

    def _key(self, conversation_id: str) -> str:
        return f"{_KEY_PREFIX}{conversation_id}"

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _parse_datetime(value: object) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            dt = datetime.fromisoformat(value)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _to_lead_draft(value: object) -> Optional[LeadDraft]:
        if isinstance(value, LeadDraft):
            return value
        if not isinstance(value, dict):
            return None
        created_at = ConversationStateStore._parse_datetime(value.get("created_at"))
        return LeadDraft(
            phone=str(value.get("phone") or ""),
            conversation_id=str(value.get("conversation_id") or ""),
            latest_intent=str(value.get("latest_intent") or ""),
            summary_hint=str(value.get("summary_hint") or ""),
            created_at=created_at or ConversationStateStore._now(),
            status=str(value.get("status") or "ready"),
        )

    @staticmethod
    def _serialize(state: ConversationState) -> str:
        payload = {
            "conversation_id": state.conversation_id,
            "state": state.state.value,
            "pending_action": state.pending_action,
            "pending_intent_summary": state.pending_intent_summary,
            "phone": state.phone,
            "lead_draft": (
                {
                    "phone": state.lead_draft.phone,
                    "conversation_id": state.lead_draft.conversation_id,
                    "latest_intent": state.lead_draft.latest_intent,
                    "summary_hint": state.lead_draft.summary_hint,
                    "created_at": state.lead_draft.created_at.isoformat(),
                    "status": state.lead_draft.status,
                }
                if state.lead_draft
                else None
            ),
            "updated_at": state.updated_at.isoformat(),
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _deserialize(raw: str, conversation_id: str) -> ConversationState:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "conversation_state | invalid_payload_reset | conversation_id=%.8s",
                conversation_id,
            )
            return ConversationState(conversation_id=conversation_id)

        updated_at = ConversationStateStore._parse_datetime(payload.get("updated_at"))
        lead_draft = ConversationStateStore._to_lead_draft(payload.get("lead_draft"))
        state_value = str(payload.get("state") or StateEnum.IDLE.value)

        try:
            parsed_state = StateEnum(state_value)
        except ValueError:
            parsed_state = StateEnum.IDLE

        return ConversationState(
            conversation_id=str(payload.get("conversation_id") or conversation_id),
            state=parsed_state,
            pending_action=str(payload.get("pending_action") or ""),
            pending_intent_summary=str(payload.get("pending_intent_summary") or ""),
            phone=str(payload.get("phone") or "") or None,
            lead_draft=lead_draft,
            updated_at=updated_at or ConversationStateStore._now(),
        )

    def _save(self, state: ConversationState) -> None:
        self._redis.set(
            self._key(state.conversation_id),
            self._serialize(state),
            ex=_EVICT_AFTER_SECONDS,
        )

    def get(self, conversation_id: str) -> ConversationState:
        """Return existing state or create a fresh IDLE state."""
        raw = self._redis.get(self._key(conversation_id))
        if raw:
            return self._deserialize(raw, conversation_id)
        state = ConversationState(conversation_id=conversation_id)
        self._save(state)
        return state

    def update(self, conversation_id: str, **fields) -> ConversationState:
        """Update named fields on an existing (or freshly created) state object."""
        state = self.get(conversation_id)
        for key, value in fields.items():
            if key == "state" and isinstance(value, str):
                try:
                    value = StateEnum(value)
                except ValueError:
                    value = StateEnum.IDLE
            if key == "lead_draft":
                value = self._to_lead_draft(value)
            setattr(state, key, value)
        state.updated_at = self._now()
        self._save(state)
        return state

    def evict_expired(self) -> int:
        """Compatibility no-op. Redis key TTL performs expiry."""
        return 0

    def __len__(self) -> int:
        count = 0
        for _ in self._redis.scan_iter(match=f"{_KEY_PREFIX}*"):
            count += 1
        return count


_store = ConversationStateStore()


def get_state_store() -> ConversationStateStore:
    return _store
