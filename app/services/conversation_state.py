"""
Conversation State Layer — Phase 2.

Lightweight in-memory state machine that tracks lead-related conversation flow
per conversation_id.  Designed to be replaced by a DB-backed store in Phase 3.

State transitions
-----------------
  idle
    → awaiting_phone    (ASK_PHONE or TRANSFER_TO_HUMAN action without a phone)
    → human_help_offered (OFFER_HUMAN_HELP action)

  awaiting_phone
    → phone_received    (valid phone submitted, action was ASK_PHONE)
    → ready_for_transfer (valid phone submitted, pending_action was TRANSFER_TO_HUMAN)

  human_help_offered
    → awaiting_phone    (user then asks for booking / price)

  phone_received / ready_for_transfer
    → terminal (no transitions in Phase 2; Phase 3 will export lead)
"""

from __future__ import annotations

import threading
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

_EVICT_AFTER_SECONDS = 3600  # 1 hour TTL for idle states


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
    latest_intent: str   # ConversationAction value that triggered the flow
    summary_hint: str    # first ~100 chars of the user question that triggered CTA
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "ready"  # "ready" | "exported" (Phase 3)


@dataclass
class ConversationState:
    """Mutable per-conversation state object."""

    conversation_id: str
    state: StateEnum = StateEnum.IDLE
    pending_action: str = ""            # ConversationAction.value awaited from user
    pending_intent_summary: str = ""    # user question that started the CTA flow
    phone: Optional[str] = None
    lead_draft: Optional[LeadDraft] = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationStateStore:
    """Thread-safe in-memory store with TTL-based eviction."""

    def __init__(self) -> None:
        self._store: dict[str, ConversationState] = {}
        self._lock = threading.Lock()

    def get(self, conversation_id: str) -> ConversationState:
        """Return existing state or create a fresh IDLE state."""
        with self._lock:
            if conversation_id not in self._store:
                self._store[conversation_id] = ConversationState(
                    conversation_id=conversation_id
                )
            return self._store[conversation_id]

    def update(self, conversation_id: str, **fields) -> ConversationState:
        """Update named fields on an existing (or freshly created) state object."""
        with self._lock:
            state = self._store.get(conversation_id)
            if state is None:
                state = ConversationState(conversation_id=conversation_id)
                self._store[conversation_id] = state
            for key, value in fields.items():
                setattr(state, key, value)
            state.updated_at = datetime.now(timezone.utc)
            return state

    def evict_expired(self) -> int:
        """Remove states that have been idle longer than TTL. Returns count removed."""
        cutoff = datetime.now(timezone.utc).timestamp() - _EVICT_AFTER_SECONDS
        with self._lock:
            stale = [
                cid
                for cid, s in self._store.items()
                if s.updated_at.timestamp() < cutoff
            ]
            for cid in stale:
                del self._store[cid]
        return len(stale)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# Module-level singleton
_store = ConversationStateStore()


def get_state_store() -> ConversationStateStore:
    return _store
