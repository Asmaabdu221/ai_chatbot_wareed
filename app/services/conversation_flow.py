"""
Conversation Flow Engine — Phase 2.

Translates a ConversationDecision + current ConversationState into:
  - A final reply (base reply + optional CTA)
  - A state transition
  - An optional LeadDraft (when phone is captured)

Two public entry points
-----------------------
  process_phone_submission(user_text, state, conversation_id)
      Call this BEFORE the normal pipeline whenever state == awaiting_phone.
      Returns a FlowResult with skip_pipeline=True if a phone was captured,
      otherwise returns None (let the pipeline proceed normally).

  apply_flow_to_reply(base_reply, decision, user_text, conversation_id)
      Call this AFTER the pipeline generates base_reply.
      Appends a CTA (if appropriate) and records the state transition.

Design rules
------------
  - All side-effects are in the state store (in-memory, Phase 2).
  - No LLM, no database, no I/O.
  - Both functions are non-blocking by design; the caller wraps them in
    try/except so failures are silent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.services.conversation_manager import ConversationAction, ConversationDecision
from app.services.conversation_state import (
    ConversationState,
    LeadDraft,
    StateEnum,
    get_state_store,
)
from app.services.cta_templates import (
    CONFIRM_PHONE_RECEIVED,
    CONFIRM_TRANSFER_READY,
    OFFER_HUMAN_HELP,
    PHONE_ATTEMPT_SOFT,
    get_ask_phone_cta,
)
from app.services.phone_utils import extract_phone, is_phone_attempt, should_exit_awaiting_phone

logger = logging.getLogger(__name__)


@dataclass
class FlowResult:
    """Outcome of a flow decision."""

    final_reply: str
    state_before: StateEnum
    state_after: StateEnum
    phone_captured: bool = False
    phone: Optional[str] = None
    lead_draft: Optional[LeadDraft] = None
    # When True the caller must NOT run the normal pipeline — the phone
    # submission already produced the complete reply.
    skip_pipeline: bool = False


# ---------------------------------------------------------------------------
# Entry point A — phone submission handler (call BEFORE pipeline)
# ---------------------------------------------------------------------------

def process_phone_submission(
    user_text: str,
    state: ConversationState,
    conversation_id: str,
) -> Optional[FlowResult]:
    """
    If the conversation is awaiting a phone number and *user_text* contains
    a valid phone, capture it and return a confirmation FlowResult.

    Returns None when:
      - state is not awaiting_phone, OR
      - no valid phone is found in user_text.
    """
    if state.state != StateEnum.AWAITING_PHONE:
        return None

    phone = extract_phone(user_text)
    if not phone:
        return None

    pending = state.pending_action or ""

    if pending == ConversationAction.TRANSFER_TO_HUMAN.value:
        new_state = StateEnum.READY_FOR_TRANSFER
        reply = CONFIRM_TRANSFER_READY
    else:
        new_state = StateEnum.PHONE_RECEIVED
        reply = CONFIRM_PHONE_RECEIVED

    lead_draft = LeadDraft(
        phone=phone,
        conversation_id=conversation_id,
        latest_intent=pending,
        summary_hint=state.pending_intent_summary or user_text[:100],
        status="ready",
    )

    get_state_store().update(
        conversation_id,
        state=new_state,
        phone=phone,
        lead_draft=lead_draft,
        pending_action="",
        pending_intent_summary="",
    )

    logger.info(
        "conversation_flow | phone_captured=yes | state_before=%s | state_after=%s"
        " | lead_draft_created=yes | conversation_id=%.8s",
        state.state.value,
        new_state.value,
        conversation_id,
    )

    return FlowResult(
        final_reply=reply,
        state_before=state.state,
        state_after=new_state,
        phone_captured=True,
        phone=phone,
        lead_draft=lead_draft,
        skip_pipeline=True,
    )


# ---------------------------------------------------------------------------
# Entry point A2 — full awaiting_phone handler (replaces raw process_phone_submission
# in the chat endpoint so the caller never needs to classify the message itself)
# ---------------------------------------------------------------------------

def handle_awaiting_phone_state(
    user_text: str,
    state: ConversationState,
    conversation_id: str,
) -> Optional[FlowResult]:
    """
    Unified pre-pipeline handler for messages received while state == awaiting_phone.

    Three-way classification
    ------------------------
    1. Valid phone  → capture it, return confirmation (skip_pipeline=True).
    2. Phone attempt (short numeric, no words) → return soft invalid message
       (skip_pipeline=True, state stays AWAITING_PHONE).
    3. New intent / topic switch → reset state to IDLE, return None so the
       caller proceeds with normal routing.  The user is NOT trapped.

    Returns
    -------
    FlowResult  — when the reply is fully handled here (caller must skip pipeline).
    None        — when the message is a new topic; caller resets state and routes normally.
    """
    if state.state != StateEnum.AWAITING_PHONE:
        return None

    # Case 1 — valid phone
    captured = process_phone_submission(user_text, state, conversation_id)
    if captured:
        return captured

    # Case 2 — invalid phone attempt (short numeric, no real words)
    if is_phone_attempt(user_text):
        logger.info(
            "conversation_flow | phone_attempt_invalid | state=awaiting_phone"
            " | conversation_id=%.8s",
            conversation_id,
        )
        return FlowResult(
            final_reply=PHONE_ATTEMPT_SOFT,
            state_before=StateEnum.AWAITING_PHONE,
            state_after=StateEnum.AWAITING_PHONE,
            skip_pipeline=True,
        )

    # Case 3 — new intent / topic switch: exit phone capture mode
    get_state_store().update(
        conversation_id,
        state=StateEnum.IDLE,
        pending_action="",
        pending_intent_summary="",
    )
    logger.info(
        "conversation_flow | topic_switch_exits_awaiting_phone | state_reset=idle"
        " | conversation_id=%.8s",
        conversation_id,
    )
    return None  # caller proceeds with normal routing


# ---------------------------------------------------------------------------
# Entry point B — CTA injection (call AFTER pipeline produces base_reply)
# ---------------------------------------------------------------------------

def apply_flow_to_reply(
    base_reply: str,
    decision: ConversationDecision,
    user_text: str,
    conversation_id: str,
) -> FlowResult:
    """
    Append the appropriate CTA to *base_reply* based on *decision* and current
    state, then record the state transition.

    Always returns a FlowResult — never raises.
    """
    store = get_state_store()
    state = store.get(conversation_id)
    state_before = state.state
    action = decision.action

    # ---- ANSWER_ONLY --------------------------------------------------------
    if action == ConversationAction.ANSWER_ONLY:
        _log(action, state_before, state_before, phone_detected=False)
        return FlowResult(
            final_reply=base_reply,
            state_before=state_before,
            state_after=state_before,
        )

    # ---- CLARIFY ------------------------------------------------------------
    if action == ConversationAction.CLARIFY:
        _log(action, state_before, state_before, phone_detected=False)
        return FlowResult(
            final_reply=base_reply,
            state_before=state_before,
            state_after=state_before,
        )

    # ---- ASK_PHONE ----------------------------------------------------------
    if action == ConversationAction.ASK_PHONE:
        # Don't spam if already waiting for a phone
        if state.state == StateEnum.AWAITING_PHONE:
            _log(action, state_before, state_before, note="no_repeat_cta")
            return FlowResult(
                final_reply=base_reply,
                state_before=state_before,
                state_after=state_before,
            )

        cta = get_ask_phone_cta(decision.reason)
        store.update(
            conversation_id,
            state=StateEnum.AWAITING_PHONE,
            pending_action=ConversationAction.ASK_PHONE.value,
            pending_intent_summary=user_text[:100],
        )
        _log(action, state_before, StateEnum.AWAITING_PHONE, phone_detected=False)
        return FlowResult(
            final_reply=f"{base_reply}\n\n{cta}",
            state_before=state_before,
            state_after=StateEnum.AWAITING_PHONE,
        )

    # ---- OFFER_HUMAN_HELP ---------------------------------------------------
    if action == ConversationAction.OFFER_HUMAN_HELP:
        # Don't offer again if we already have a phone or are in a later state
        if state.state in (
            StateEnum.AWAITING_PHONE,
            StateEnum.PHONE_RECEIVED,
            StateEnum.READY_FOR_TRANSFER,
        ):
            _log(action, state_before, state_before, note="already_advanced_state")
            return FlowResult(
                final_reply=base_reply,
                state_before=state_before,
                state_after=state_before,
            )

        store.update(
            conversation_id,
            state=StateEnum.HUMAN_HELP_OFFERED,
            pending_intent_summary=user_text[:100],
        )
        _log(action, state_before, StateEnum.HUMAN_HELP_OFFERED, phone_detected=False)
        return FlowResult(
            final_reply=f"{base_reply}\n\n{OFFER_HUMAN_HELP}",
            state_before=state_before,
            state_after=StateEnum.HUMAN_HELP_OFFERED,
        )

    # ---- TRANSFER_TO_HUMAN --------------------------------------------------
    if action == ConversationAction.TRANSFER_TO_HUMAN:
        if state.phone:
            # Phone already known → mark ready for transfer immediately
            store.update(conversation_id, state=StateEnum.READY_FOR_TRANSFER)
            _log(action, state_before, StateEnum.READY_FOR_TRANSFER, note="phone_known")
            return FlowResult(
                final_reply=f"{base_reply}\n\n{CONFIRM_TRANSFER_READY}",
                state_before=state_before,
                state_after=StateEnum.READY_FOR_TRANSFER,
            )

        if state.state == StateEnum.AWAITING_PHONE:
            _log(action, state_before, state_before, note="already_awaiting_phone")
            return FlowResult(
                final_reply=base_reply,
                state_before=state_before,
                state_after=state_before,
            )

        # Phone unknown → ask for it (urgent CTA)
        cta = get_ask_phone_cta("transfer")
        store.update(
            conversation_id,
            state=StateEnum.AWAITING_PHONE,
            pending_action=ConversationAction.TRANSFER_TO_HUMAN.value,
            pending_intent_summary=user_text[:100],
        )
        _log(action, state_before, StateEnum.AWAITING_PHONE, phone_detected=False)
        return FlowResult(
            final_reply=f"{base_reply}\n\n{cta}",
            state_before=state_before,
            state_after=StateEnum.AWAITING_PHONE,
        )

    # Fallback — unknown action
    _log(action, state_before, state_before, note="unknown_action_fallback")
    return FlowResult(
        final_reply=base_reply,
        state_before=state_before,
        state_after=state_before,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _log(
    action: ConversationAction,
    state_before: StateEnum,
    state_after: StateEnum,
    *,
    phone_detected: bool = False,
    note: str = "",
) -> None:
    parts = [
        f"conversation_flow | action={action.value}",
        f"state_before={state_before.value}",
        f"state_after={state_after.value}",
        f"phone_detected={phone_detected}",
    ]
    if note:
        parts.append(f"note={note}")
    logger.info(" | ".join(parts))
