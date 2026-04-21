"""
Chat API Endpoint
Handles chat interactions with OpenAI integration and knowledge base
Includes database persistence for conversations and messages
"""

from fastapi import APIRouter, HTTPException, status, Depends, Request
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict
from datetime import timezone
from uuid import UUID
from datetime import datetime
import logging

from sqlalchemy.orm import Session

from app.services.openai_service import openai_service
from app.services.smart_cache import get_smart_cache
from app.services.context_cache import get_context_cache
from app.services.rate_limiter import get_rate_limiter
from app.services.question_router import route as route_question
from app.services.usage_tracker import get_usage_tracker
# RAG pipeline (primary) or fallback to legacy knowledge loader
from app.data.rag_pipeline import (
    get_grounded_context,
    is_rag_ready,
    NO_INFO_MESSAGE,
)
from app.data.knowledge_loader_v2 import (
    get_knowledge_base,
    get_knowledge_context,
    get_test_statistics
)
from app.core.config import settings
from app.db import get_db
from app.db.models import User, Conversation, Message, MessageRole
from app.core.deps import get_current_user_optional

# Get logger
logger = logging.getLogger(__name__)

router = APIRouter()


# Request/Response Models
class ChatMessage(BaseModel):
    """Individual chat message"""
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    """Chat request model with database persistence"""
    message: str = Field(..., min_length=1, max_length=1000, description="User message")
    user_id: Optional[UUID] = Field(None, description="User ID (created if not exists)")
    conversation_id: Optional[UUID] = Field(None, description="Conversation ID (created if not exists)")
    include_knowledge: bool = Field(
        default=True,
        description="Whether to include knowledge base context"
    )


class ChatResponse(BaseModel):
    """Chat response model with database IDs (reply + response alias for compatibility)"""
    reply: str = Field(..., description="AI assistant reply")
    response: str = Field(..., description="Alias for reply (API compatibility)")
    success: bool = Field(..., description="Whether the request was successful")
    user_id: UUID = Field(..., description="User ID")
    conversation_id: UUID = Field(..., description="Conversation ID")
    message_id: UUID = Field(..., description="Assistant message ID")
    tokens_used: Optional[int] = Field(None, description="Number of tokens used")
    model: Optional[str] = Field(None, description="AI model used")
    timestamp: datetime = Field(..., description="Response timestamp")
    error: Optional[str] = Field(None, description="Error message if failed")

    @model_validator(mode="before")
    @classmethod
    def response_from_reply(cls, data: dict) -> dict:
        """Set response=reply when not provided."""
        if isinstance(data, dict) and "reply" in data and "response" not in data:
            data["response"] = data["reply"]
        return data


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    openai_connected: bool
    knowledge_base_loaded: bool


# Helper Functions
def _get_or_create_user(db: Session, user_id: Optional[UUID]) -> User:
    """Get existing user or create new one"""
    if user_id:
        user = db.get(User, user_id)
        if user:
            user.last_active_at = datetime.now(timezone.utc)
            return user
    
    # Create new user
    new_user = User()
    db.add(new_user)
    db.flush()  # Get the ID without committing
    logger.info(f"✨ Created new user: {new_user.id}")
    return new_user


def _get_or_create_conversation(
    db: Session, 
    user: User, 
    conversation_id: Optional[UUID],
    first_message: str
) -> Conversation:
    """Get existing conversation or create new one"""
    if conversation_id:
        conversation = db.get(Conversation, conversation_id)
        if conversation and conversation.user_id == user.id:
            # Update timestamp (database will handle via onupdate)
            # No manual update needed - SQLAlchemy handles this
            return conversation
    
    # Create new conversation with auto-generated title
    title = first_message[:50] + "..." if len(first_message) > 50 else first_message
    new_conversation = Conversation(
        user_id=user.id,
        title=title
    )
    db.add(new_conversation)
    db.flush()
    logger.info(f"✨ Created new conversation: {new_conversation.id}")
    return new_conversation


def _save_message(
    db: Session,
    conversation: Conversation,
    role: MessageRole,
    content: str,
    token_count: Optional[int] = None
) -> Message:
    """Save a message to the database"""
    message = Message(
        conversation_id=conversation.id,
        role=role,
        content=content,
        token_count=token_count
    )
    db.add(message)
    db.flush()
    return message


def _load_conversation_history(db: Session, conversation: Conversation) -> List[Dict]:
    """Load conversation history from database (exclude soft-deleted)"""
    messages = [msg for msg in conversation.messages if msg.deleted_at is None]
    return [
        {"role": msg.role.value, "content": msg.content}
        for msg in messages
    ]


def _get_client_id(http_request: Request, user_id: Optional[UUID] = None) -> str:
    """Rate limit key: prefer user_id if provided, else client IP."""
    if user_id:
        return f"user:{user_id}"
    if http_request.client:
        return f"ip:{http_request.client.host}"
    return "unknown"


# Endpoints
@router.post("/chat", response_model=ChatResponse, summary="Chat with AI Assistant")
async def chat_endpoint(
    http_request: Request,
    request: ChatRequest,
    db: Optional[Session] = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Chat with Wareed AI Medical Assistant (with database persistence)
    
    - **message**: Your question or message in Arabic or English (1-1000 chars)
    - **user_id**: Optional user ID (creates new user if not provided)
    - **conversation_id**: Optional conversation ID (creates new if not provided)
    - **include_knowledge**: Whether to include company knowledge base
    
    The endpoint:
    1. Creates/loads user and conversation
    2. Persists user message BEFORE calling OpenAI
    3. Generates AI response
    4. Persists assistant message AFTER response
    5. Uses database transaction for data integrity
    
    Returns an Arabic response with conversation and message IDs
    """
    try:
        logger.info(f"📨 Received chat request: {request.message[:50]}...")
        
        # Resolve user: JWT Bearer overrides body user_id (same for Web/Mobile)
        effective_user_id = current_user.id if current_user else request.user_id
        
        # Rate limiting (by authenticated user or IP)
        client_id = _get_client_id(http_request, effective_user_id)
        allowed, retry_after = get_rate_limiter().is_allowed(client_id)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="تم تجاوز الحد المسموح من الطلبات. يرجى المحاولة بعد قليل.",
                headers={"Retry-After": str(retry_after)},
            )
        
        # Validate message
        if not request.message or not request.message.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message cannot be empty"
            )
        
        from uuid import uuid4
        
        # Resolve user/conversation and history: use DB when available, else demo IDs
        user_id = effective_user_id or uuid4()
        conversation_id = request.conversation_id or uuid4()
        conversation_history: List[Dict] = []
        user = None
        conversation = None
        
        if db is not None:
            user = _get_or_create_user(db, effective_user_id)
            conversation = _get_or_create_conversation(
                db, user, request.conversation_id, request.message
            )
            user_id = user.id
            conversation_id = conversation.id
            _save_message(db, conversation, MessageRole.USER, request.message)
            logger.info("💾 Saved user message")
            conversation_history = _load_conversation_history(db, conversation)
            logger.info(f"💬 Loaded {len(conversation_history)} previous messages")
            db.commit()
        else:
            logger.info("⚠️ Demo mode: Database operations skipped")
        
        # === PHASE 2A: Phone / topic-switch intercept (before routing) ===
        # Three outcomes:
        #   1. Valid phone   → skip pipeline, return confirmation.
        #   2. Phone attempt → skip pipeline, return soft-invalid message.
        #   3. New topic     → reset state to IDLE, fall through to normal routing.
        try:
            from app.services.conversation_state import get_state_store, StateEnum
            from app.services.conversation_flow import handle_awaiting_phone_state
            _state_store = get_state_store()
            _curr_state = _state_store.get(str(conversation_id))
            if _curr_state.state == StateEnum.AWAITING_PHONE:
                _phone_result = handle_awaiting_phone_state(
                    request.message, _curr_state, str(conversation_id)
                )
                if _phone_result and _phone_result.skip_pipeline:
                    if db is not None and conversation is not None:
                        _save_message(
                            db, conversation, MessageRole.ASSISTANT,
                            _phone_result.final_reply, token_count=0,
                        )
                        db.commit()
                    # Persist + deliver lead when phone was successfully captured
                    if _phone_result.phone_captured and _phone_result.lead_draft:
                        try:
                            from app.services.lead_service import create_lead_from_draft, deliver_lead
                            _lead = create_lead_from_draft(_phone_result.lead_draft, db)
                            if _lead is not None:
                                deliver_lead(_lead, db)
                        except Exception as _lead_err:
                            logger.warning("lead_service skipped (non-blocking): %s", _lead_err)
                    return ChatResponse(
                        reply=_phone_result.final_reply,
                        success=True,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        message_id=uuid4(),
                        tokens_used=0,
                        model="flow",
                        timestamp=datetime.now(),
                        error=None,
                    )
                # None returned → new topic, state already reset to IDLE, fall through
        except Exception as _phase2a_err:
            logger.warning("conversation_flow phase2a skipped (non-blocking): %s", _phase2a_err)

        # === QUESTION ROUTING (price → fixed response, no API) ===
        route_type, fixed_reply = route_question(request.message)

        # === CONVERSATION MANAGER (Phase 1: classify + log, non-blocking) ===
        _conv_decision = None
        try:
            from app.services.conversation_manager import decide_conversation_action
            _conv_decision = decide_conversation_action(
                request.message,
                detected_route=route_type or "",
            )
            logger.info(
                "conversation_manager | action=%s | reason=%s | route=%s | confidence=%s",
                _conv_decision.action.value,
                _conv_decision.reason,
                _conv_decision.detected_route,
                _conv_decision.confidence,
            )
        except Exception as _cm_err:
            logger.warning("conversation_manager skipped (non-blocking): %s", _cm_err)

        if fixed_reply:
            logger.info("🔀 Routed to fixed response (route=%s) - no API call", route_type)
            cache = get_smart_cache()
            try:
                cache.set(request.message, fixed_reply)  # cache base reply (no CTA)
            except Exception:
                pass
            get_usage_tracker().record("router", 0)
            # Phase 2B: inject CTA into the reply the user actually sees
            _fixed_final = fixed_reply
            try:
                if _conv_decision is not None:
                    from app.services.conversation_flow import apply_flow_to_reply
                    _fixed_final = apply_flow_to_reply(
                        fixed_reply, _conv_decision, request.message, str(conversation_id)
                    ).final_reply
            except Exception as _p2b_err:
                logger.warning("conversation_flow phase2b(router) skipped: %s", _p2b_err)
            if db is not None and conversation is not None:
                _save_message(db, conversation, MessageRole.ASSISTANT, _fixed_final, token_count=0)
                db.commit()
            return ChatResponse(
                reply=_fixed_final,
                success=True,
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=uuid4(),
                tokens_used=0,
                model="router",
                timestamp=datetime.now(),
                error=None
            )
        
        # === RUNTIME ROUTER (branches, FAQ, results, packages, tests) ===
        # Attempt domain-specific resolution BEFORE cache/RAG/OpenAI so
        # follow-up selection state (e.g. "2", "23", branch name) is always respected.
        try:
            from app.services.runtime.runtime_router import route_runtime_message
            _runtime_result = route_runtime_message(
                request.message,
                conversation_id=conversation_id,
                faq_only_runtime_mode=True,  # enables branch/domain pipeline
            )
            if _runtime_result.get("matched"):
                _runtime_reply = _runtime_result.get("reply", "")
                _runtime_source = str(_runtime_result.get("source") or "").strip()
                _runtime_meta = dict(_runtime_result.get("meta") or {})
                _runtime_route = str(_runtime_result.get("route") or "").strip()
                logger.info(
                    "runtime_router | matched=yes | route=%s | source=%s",
                    _runtime_route,
                    _runtime_source,
                )

                # --- FIX 2: Re-run conversation_manager with ACTUAL runtime route ---
                try:
                    from app.services.conversation_manager import decide_conversation_action
                    _conv_decision = decide_conversation_action(
                        request.message,
                        detected_route=_runtime_route,
                        runtime_source=_runtime_source,
                        runtime_meta=_runtime_meta,
                        runtime_reply=_runtime_reply,
                    )
                    logger.info(
                        "conversation_manager(post-runtime) | action=%s | reason=%s | route=%s",
                        _conv_decision.action.value,
                        _conv_decision.reason,
                        _conv_decision.detected_route,
                    )
                except Exception as _cm2_err:
                    logger.warning("conversation_manager(post-runtime) skipped: %s", _cm2_err)

                # --- FIX 5: Clear selection state on domain change ---
                try:
                    from app.services.runtime.selection_state import (
                        load_selection_state,
                        clear_selection_state,
                    )
                    _prev_sel = load_selection_state(conversation_id)
                    _prev_domain = str(_prev_sel.get("last_selection_type") or "").strip()
                    _curr_domain = _runtime_source  # e.g. "branches", "tests", "packages"
                    if _prev_domain and _curr_domain and _prev_domain != _curr_domain:
                        clear_selection_state(conversation_id)
                        logger.info(
                            "selection_state cleared | prev=%s | curr=%s | conversation_id=%.8s",
                            _prev_domain, _curr_domain, str(conversation_id),
                        )
                except Exception as _sel_err:
                    logger.debug("selection_state domain-change check skipped: %s", _sel_err)

                # update entity memory for branch follow-ups
                if _runtime_source == "branches":
                    try:
                        from app.services.runtime.entity_memory import update_entity_memory
                        update_entity_memory(
                            conversation_id,
                            last_intent="branch",
                            last_branch={
                                "id": str(_runtime_meta.get("matched_branch_id") or _runtime_meta.get("id") or "").strip(),
                                "label": str(_runtime_meta.get("branch_name") or "").strip(),
                                "city": str(_runtime_meta.get("city") or "").strip(),
                            },
                        )
                    except Exception as _em_err:
                        logger.warning("entity_memory update(branch) skipped: %s", _em_err)
                get_usage_tracker().record("runtime", 0)
                _runtime_final = _runtime_reply
                try:
                    if _conv_decision is not None:
                        from app.services.conversation_flow import apply_flow_to_reply
                        _runtime_final = apply_flow_to_reply(
                            _runtime_reply, _conv_decision, request.message, str(conversation_id)
                        ).final_reply
                except Exception as _p2b_err:
                    logger.warning("conversation_flow phase2b(runtime) skipped: %s", _p2b_err)
                if db is not None and conversation is not None:
                    _save_message(db, conversation, MessageRole.ASSISTANT, _runtime_final, token_count=0)
                    db.commit()
                return ChatResponse(
                    reply=_runtime_final,
                    success=True,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    message_id=uuid4(),
                    tokens_used=0,
                    model="runtime",
                    timestamp=datetime.now(),
                    error=None,
                )
            logger.info(
                "runtime_router | matched=no | route=%s | fallback=cache_rag",
                _runtime_result.get("route"),
            )
        except Exception as _runtime_err:
            logger.warning("runtime_router skipped (non-blocking): %s", _runtime_err)

        # === SMART CACHE CHECK (skip OpenAI if cached) ===
        cache = get_smart_cache()
        cached_reply = cache.get(request.message)
        if cached_reply is not None:
            logger.info("📦 Cache HIT - returning cached response (no API call)")
            get_usage_tracker().record("cache", 0)
            # Phase 2B: CTA on top of cached base reply
            _cached_final = cached_reply
            try:
                if _conv_decision is not None:
                    from app.services.conversation_flow import apply_flow_to_reply
                    _cached_final = apply_flow_to_reply(
                        cached_reply, _conv_decision, request.message, str(conversation_id)
                    ).final_reply
            except Exception as _p2b_err:
                logger.warning("conversation_flow phase2b(cache) skipped: %s", _p2b_err)
            if db is not None and conversation is not None:
                assistant_msg = _save_message(db, conversation, MessageRole.ASSISTANT, _cached_final, token_count=0)
                db.commit()
                return ChatResponse(
                    reply=_cached_final,
                    success=True,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    message_id=assistant_msg.id,
                    tokens_used=0,
                    model="cache",
                    timestamp=datetime.now(),
                    error=None
                )
            return ChatResponse(
                reply=_cached_final,
                success=True,
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=uuid4(),
                tokens_used=0,
                model="cache",
                timestamp=datetime.now(),
                error=None
            )
        
        # === OPENAI API CALL ===

        # Prepare knowledge context: RAG (strict retrieval) or legacy
        knowledge_context = None
        use_rag = request.include_knowledge and is_rag_ready()
        
        if request.include_knowledge:
            try:
                if use_rag:
                    # RAG: strict retrieval, similarity threshold, no hallucination
                    threshold = getattr(settings, "RAG_SIMILARITY_THRESHOLD", 0.58)
                    knowledge_context, has_relevant = get_grounded_context(
                        user_message=request.message,
                        max_tests=3,
                        similarity_threshold=threshold,
                        include_prices=True,
                    )
                    if not has_relevant:
                        # --- FIX 6: LLM fallback before NO_INFO ---
                        # RAG found nothing — try LLM with strict prompt before giving up
                        logger.info("📚 RAG: no relevant info (below threshold) - trying strict LLM fallback")
                        get_usage_tracker().record("rag_no_match", 0)
                        try:
                            _strict_response = openai_service.generate_response(
                                user_message=request.message,
                                knowledge_context=(
                                    "أنت مساعد مختبر وريد الطبي. أجب فقط إذا كنت متأكداً من الإجابة. "
                                    "إذا لم تكن متأكداً، قل: لا أملك معلومات كافية عن هذا الموضوع حالياً."
                                ),
                                conversation_history=conversation_history,
                            )
                            if _strict_response["success"]:
                                _strict_reply = _strict_response["response"]
                                # Check if LLM admitted it doesn't know
                                _no_info_markers = (
                                    "لا أملك معلومات",
                                    "ما عندي معلومات",
                                    "لا أستطيع الإجابة",
                                    "ليس لدي معلومات",
                                )
                                _llm_gave_up = any(m in _strict_reply for m in _no_info_markers)
                                if not _llm_gave_up and len(_strict_reply.strip()) > 20:
                                    logger.info("📚 Strict LLM fallback produced a confident answer")
                                    # Apply CTA if needed
                                    _rag_fb_final = _strict_reply
                                    try:
                                        if _conv_decision is not None:
                                            from app.services.conversation_flow import apply_flow_to_reply
                                            _rag_fb_final = apply_flow_to_reply(
                                                _strict_reply, _conv_decision,
                                                request.message, str(conversation_id),
                                            ).final_reply
                                    except Exception:
                                        pass
                                    get_usage_tracker().record(
                                        _strict_response.get("model") or "openai",
                                        _strict_response.get("tokens_used") or 0,
                                    )
                                    if db is not None and conversation is not None:
                                        _save_message(db, conversation, MessageRole.ASSISTANT,
                                                      _rag_fb_final,
                                                      token_count=_strict_response.get("tokens_used"))
                                        db.commit()
                                    return ChatResponse(
                                        reply=_rag_fb_final,
                                        success=True,
                                        user_id=user_id,
                                        conversation_id=conversation_id,
                                        message_id=uuid4(),
                                        tokens_used=_strict_response.get("tokens_used") or 0,
                                        model=_strict_response.get("model") or "openai",
                                        timestamp=datetime.now(),
                                        error=None,
                                    )
                                logger.info("📚 Strict LLM also gave up - returning NO_INFO")
                        except Exception as _llm_fb_err:
                            logger.warning("Strict LLM fallback failed: %s", _llm_fb_err)

                        # Both RAG and LLM failed — return NO_INFO
                        if db is not None and conversation is not None:
                            _save_message(db, conversation, MessageRole.ASSISTANT, NO_INFO_MESSAGE, token_count=0)
                            db.commit()
                        return ChatResponse(
                            reply=NO_INFO_MESSAGE,
                            success=True,
                            user_id=user_id,
                            conversation_id=conversation_id,
                            message_id=uuid4(),
                            tokens_used=0,
                            model="rag",
                            timestamp=datetime.now(),
                            error=None
                        )
                else:
                    # RAG not built: single source only - return no-info without API call
                    logger.warning("RAG not ready - run: python -m app.data.build_rag_system")
                    get_usage_tracker().record("rag_not_built", 0)
                    if db is not None and conversation is not None:
                        _save_message(db, conversation, MessageRole.ASSISTANT, NO_INFO_MESSAGE, token_count=0)
                        db.commit()
                    return ChatResponse(
                        reply=NO_INFO_MESSAGE,
                        success=True,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        message_id=uuid4(),
                        tokens_used=0,
                        model="rag",
                        timestamp=datetime.now(),
                        error=None
                    )
                logger.info(f"📚 Context loaded ({len(knowledge_context or '')} chars)")
            except Exception as e:
                logger.warning(f"⚠️ Failed to load knowledge context: {str(e)}")
        
        # Generate AI response (grounded in context only)
        ai_response = openai_service.generate_response(
            user_message=request.message,
            knowledge_context=knowledge_context,
            conversation_history=conversation_history
        )
        
        # === SAVE ASSISTANT RESPONSE ===
        
        if ai_response["success"]:
            try:
                cache.set(request.message, ai_response["response"])  # cache base reply
            except Exception as e:
                logger.warning("⚠️ Failed to save response to cache: %s", str(e))

            # Phase 2B: CTA on top of AI base reply
            _ai_final = ai_response["response"]
            try:
                if _conv_decision is not None:
                    from app.services.conversation_flow import apply_flow_to_reply
                    _ai_final = apply_flow_to_reply(
                        ai_response["response"], _conv_decision, request.message, str(conversation_id)
                    ).final_reply
            except Exception as _p2b_err:
                logger.warning("conversation_flow phase2b(ai) skipped: %s", _p2b_err)

            message_id = uuid4()
            if db is not None and conversation is not None:
                assistant_message = _save_message(
                    db,
                    conversation,
                    MessageRole.ASSISTANT,
                    _ai_final,
                    token_count=ai_response["tokens_used"]
                )
                db.commit()
                message_id = assistant_message.id

            logger.info(f"✅ Response generated - {ai_response['tokens_used']} tokens")
            get_usage_tracker().record(
                ai_response.get("model") or "openai",
                ai_response.get("tokens_used") or 0,
            )
            return ChatResponse(
                reply=_ai_final,
                success=True,
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                tokens_used=ai_response["tokens_used"],
                model=ai_response["model"],
                timestamp=datetime.now(),
                error=None
            )
        else:
            message_id = uuid4()
            if db is not None and conversation is not None:
                _save_message(
                    db,
                    conversation,
                    MessageRole.ASSISTANT,
                    ai_response["response"],
                    token_count=0
                )
                db.commit()
            
            logger.error(f"❌ OpenAI service error: {ai_response['error']}")
            get_usage_tracker().record(ai_response.get("model") or "openai", 0)
            return ChatResponse(
                reply=ai_response["response"],
                success=False,
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                tokens_used=0,
                model=ai_response["model"],
                timestamp=datetime.now(),
                error=ai_response["error"]
            )
    
    except HTTPException:
        if db is not None:
            db.rollback()
        raise
    
    except Exception as e:
        if db is not None:
            db.rollback()
        error_msg = f"Unexpected error in chat endpoint: {str(e)}"
        logger.error(f"❌ {error_msg}", exc_info=True)
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process chat request"
        )


@router.get("/chat/health", response_model=HealthResponse, summary="Check Chat Service Health")
async def chat_health_check():
    """
    Check the health status of the chat service
    
    Returns status of OpenAI connection and knowledge base (RAG when built)
    """
    try:
        # Test OpenAI connection
        openai_test = openai_service.test_connection()
        openai_connected = openai_test["success"]
        
        # Check knowledge base: RAG (single source). Legacy used only for stats fallback.
        knowledge_loaded = is_rag_ready()
        if not knowledge_loaded:
            kb = get_knowledge_base()
            knowledge_loaded = bool(kb.tests or kb.faqs)
        
        overall_status = "healthy" if (openai_connected and knowledge_loaded) else "degraded"
        
        logger.info(f"🏥 Health check - Status: {overall_status}")
        
        return HealthResponse(
            status=overall_status,
            openai_connected=openai_connected,
            knowledge_base_loaded=knowledge_loaded
        )
    
    except Exception as e:
        logger.error(f"❌ Health check failed: {str(e)}")
        return HealthResponse(
            status="unhealthy",
            openai_connected=False,
            knowledge_base_loaded=False
        )


@router.get("/chat/usage", summary="Get Usage & Cost Statistics")
async def get_usage_stats():
    """Return usage totals and breakdown by model (for monitoring)."""
    try:
        return {
            "success": True,
            "usage": get_usage_tracker().get_stats(),
        }
    except Exception as e:
        logger.error("❌ Failed to get usage stats: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage statistics",
        )


@router.get("/chat/usage/dashboard", summary="Usage Dashboard Data")
async def get_usage_dashboard():
    """
    Return full dashboard: usage, analysis usage, cache stats.
    Used by the dashboard UI and can be used by chat for stats insights.
    """
    try:
        dashboard = get_usage_tracker().get_dashboard()
        try:
            from app.services.analysis_usage_tracker import get_analysis_usage_tracker
            dashboard["analysis_usage"] = get_analysis_usage_tracker().get_stats()
        except Exception:
            dashboard["analysis_usage"] = {"by_analysis": [], "total_analyses_used": 0, "total_uses": 0}
        try:
            dashboard["cache"] = get_smart_cache().get_stats()
            dashboard["context_cache"] = get_context_cache().get_stats()
        except Exception:
            dashboard["cache"] = {}
            dashboard["context_cache"] = {}
        return {
            "success": True,
            "dashboard": dashboard,
        }
    except Exception as e:
        logger.error("❌ Failed to get usage dashboard: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage dashboard",
        )


@router.get("/chat/rate-limit/stats", summary="Get Rate Limiter Statistics")
async def get_rate_limit_stats():
    """Return rate limiter config and tracked clients count."""
    try:
        stats = get_rate_limiter().get_stats()
        return {"success": True, "rate_limit": stats}
    except Exception as e:
        logger.error("❌ Failed to get rate limit stats: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve rate limit statistics",
        )


@router.get("/chat/cache/stats", summary="Get Cache Statistics")
async def get_cache_stats():
    """
    Get cache statistics: Smart Cache (Q&A) and Context Cache (RAG context).
    """
    try:
        smart_stats = get_smart_cache().get_stats()
        context_stats = get_context_cache().get_stats()
        return {
            "success": True,
            "cache": smart_stats,
            "context_cache": context_stats,
            "message": "Cache statistics retrieved successfully"
        }
    except Exception as e:
        logger.error("❌ Failed to get cache stats: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve cache statistics"
        )


@router.get("/chat/stats/analyses", summary="Analysis Usage for Chat/Widget")
async def get_analysis_usage_stats(top: int = 20):
    """
    Return how many times each analysis was used (in RAG context).
    For dashboard and for chat to show 'أكثر التحاليل طلباً'.
    """
    try:
        from app.services.analysis_usage_tracker import get_analysis_usage_tracker
        stats = get_analysis_usage_tracker().get_stats()
        stats["top"] = get_analysis_usage_tracker().get_top(n=top)
        return {"success": True, "analysis_usage": stats}
    except Exception as e:
        logger.error("❌ Failed to get analysis usage: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve analysis usage",
        )


@router.get("/chat/stats", summary="Get Knowledge Base Statistics")
async def get_knowledge_stats():
    """
    Get statistics about the knowledge base (RAG when built, else legacy)
    
    Returns information about:
    - Total tests and FAQs
    - Tests with/without prices
    - Price range
    - Categories
    """
    try:
        if is_rag_ready():
            from app.data.rag_pipeline import load_rag_knowledge
            tests, meta = load_rag_knowledge()
            prices = [t.get("price") for t in tests if t.get("price") is not None]
            stats = {
                "total_tests": len(tests),
                "total_faqs": 0,
                "tests_with_price": len(prices),
                "tests_without_price": len(tests) - len(prices),
                "categories": len(set(t.get("category") for t in tests if t.get("category"))),
                "price_range": {"min": min(prices), "max": max(prices)} if prices else {"min": 0, "max": 0},
                "version": meta.get("version", "3.0.0"),
                "source": "rag_knowledge_base.json",
            }
        else:
            stats = get_test_statistics()
        
        return {
            "success": True,
            "statistics": stats,
            "message": "Knowledge base statistics retrieved successfully"
        }
    except Exception as e:
        logger.error(f"❌ Failed to get statistics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve knowledge base statistics"
        )


@router.post("/chat/knowledge/reload", summary="Reload Knowledge Base")
async def reload_knowledge():
    """
    Reload the knowledge base. When RAG is active, rebuilds from analysis_file.xlsx.
    Otherwise reloads legacy knowledge base.
    """
    try:
        if is_rag_ready():
            # Rebuild RAG from analysis_file.xlsx
            from app.data.build_rag_system import build
            build(raise_on_error=True)
            try:
                get_context_cache().clear()
                get_smart_cache().clear()
            except Exception:
                pass
            return {"success": True, "message": "قاعدة المعرفة RAG تم إعادة بنائها بنجاح"}
        from app.data.knowledge_loader_v2 import reload_knowledge_base
        ok = reload_knowledge_base()
        if ok:
            return {"success": True, "message": "قاعدة المعرفة تم تحديثها بنجاح"}
        return {"success": False, "message": "فشل تحميل قاعدة المعرفة"}
    except Exception as e:
        logger.error("❌ Failed to reload knowledge base: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reload knowledge base",
        )


@router.post("/chat/cache/clear", summary="Clear Chat Caches")
async def clear_chat_caches():
    """
    Clear Smart Cache and Context Cache.
    Use after updating retrieval logic to get fresh results for previously cached queries.
    """
    try:
        get_smart_cache().clear()
        get_context_cache().clear()
        return {"success": True, "message": "تم مسح الكاش بنجاح"}
    except Exception as e:
        logger.warning("Cache clear failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to clear cache")


@router.post("/chat/test", summary="Test Chat Without AI (Echo)")
async def test_chat_endpoint(request: ChatRequest):
    """
    Test endpoint that echoes back the message without calling OpenAI
    Useful for testing API connectivity
    """
    logger.info(f"🧪 Test endpoint called with message: {request.message[:50]}...")
    
    from uuid import uuid4
    
    return ChatResponse(
        reply=f"تم استلام رسالتك: {request.message}",
        success=True,
        user_id=uuid4(),
        conversation_id=uuid4(),
        message_id=uuid4(),
        tokens_used=0,
        model="test-echo",
        timestamp=datetime.now(),
        error=None
    )


from fastapi import UploadFile, File, Form

@router.post("/chat/voice", summary="Send Voice Message")
async def voice_chat_endpoint(
    http_request: Request,
    audio: UploadFile = File(..., description="Audio file (webm, wav, mp3)"),
    user_id: Optional[str] = Form(None),
    conversation_id: Optional[str] = Form(None)
):
    """
    Send voice message - converts speech to text then processes as chat message
    
    Process:
    1. Receive audio file
    2. Convert speech to text (using Whisper API or similar)
    3. Send transcribed text to chat endpoint
    4. Return AI response with transcribed text
    """
    try:
        logger.info(f"🎤 Received voice message: {audio.filename}")
        
        # Rate limiting (by IP or user_id when provided)
        try:
            uid = UUID(user_id) if user_id else None
        except (ValueError, TypeError):
            uid = None
        client_id = _get_client_id(http_request, uid)
        allowed, retry_after = get_rate_limiter().is_allowed(client_id)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="تم تجاوز الحد المسموح من الطلبات. يرجى المحاولة بعد قليل.",
                headers={"Retry-After": str(retry_after)},
            )
        
        # Read audio file
        audio_data = await audio.read()
        
        # TODO: Implement speech-to-text conversion
        # For now, using placeholder - you can integrate:
        # - OpenAI Whisper API
        # - Google Speech-to-Text
        # - Azure Speech Services
        # - Or any other STT service
        
        transcribed_text = await transcribe_audio(audio_data, audio.filename)
        
        if not transcribed_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="فشل تحويل الصوت إلى نص"
            )
        
        logger.info(f"📝 Transcribed text: {transcribed_text[:100]}...")
        
        # Process as regular chat message
        from uuid import UUID, uuid4
        
        dummy_user_id = UUID(user_id) if user_id else uuid4()
        dummy_conversation_id = UUID(conversation_id) if conversation_id else uuid4()
        
        # Question routing for voice (price → fixed response)
        route_type, fixed_reply = route_question(transcribed_text)
        if fixed_reply:
            logger.info("🔀 Voice routed to fixed response (route=%s)", route_type)
            try:
                get_smart_cache().set(transcribed_text, fixed_reply)
            except Exception:
                pass
            get_usage_tracker().record("router", 0)
            return {
                "reply": fixed_reply,
                "success": True,
                "user_id": str(dummy_user_id),
                "conversation_id": str(dummy_conversation_id),
                "message_id": str(uuid4()),
                "tokens_used": 0,
                "model": "router",
                "timestamp": datetime.now().isoformat(),
                "transcribed_text": transcribed_text,
                "error": None
            }
        
        # Smart cache check for voice (same as text chat)
        voice_cache = get_smart_cache()
        cached_reply = voice_cache.get(transcribed_text)
        if cached_reply is not None:
            logger.info("📦 Cache HIT (voice) - returning cached response")
            get_usage_tracker().record("cache", 0)
            return {
                "reply": cached_reply,
                "success": True,
                "user_id": str(dummy_user_id),
                "conversation_id": str(dummy_conversation_id),
                "message_id": str(uuid4()),
                "tokens_used": 0,
                "model": "cache",
                "timestamp": datetime.now().isoformat(),
                "transcribed_text": transcribed_text,
                "error": None
            }
        
        # Get knowledge context: RAG (strict) or no-info
        knowledge_context = None
        try:
            if is_rag_ready():
                threshold = getattr(settings, "RAG_SIMILARITY_THRESHOLD", 0.58)
                knowledge_context, has_relevant = get_grounded_context(
                    user_message=transcribed_text,
                    max_tests=3,
                    similarity_threshold=threshold,
                    include_prices=True,
                )
                if not has_relevant:
                    try:
                        get_smart_cache().set(transcribed_text, NO_INFO_MESSAGE)
                    except Exception:
                        pass
                    get_usage_tracker().record("rag_no_match", 0)
                    return {
                        "reply": NO_INFO_MESSAGE,
                        "success": True,
                        "user_id": str(dummy_user_id),
                        "conversation_id": str(dummy_conversation_id),
                        "message_id": str(uuid4()),
                        "tokens_used": 0,
                        "model": "rag",
                        "timestamp": datetime.now().isoformat(),
                        "transcribed_text": transcribed_text,
                        "error": None
                    }
            else:
                # RAG not built
                try:
                    get_smart_cache().set(transcribed_text, NO_INFO_MESSAGE)
                except Exception:
                    pass
                get_usage_tracker().record("rag_not_built", 0)
                return {
                    "reply": NO_INFO_MESSAGE,
                    "success": True,
                    "user_id": str(dummy_user_id),
                    "conversation_id": str(dummy_conversation_id),
                    "message_id": str(uuid4()),
                    "tokens_used": 0,
                    "model": "rag",
                    "timestamp": datetime.now().isoformat(),
                    "transcribed_text": transcribed_text,
                    "error": None
                }
        except Exception as e:
            logger.warning(f"⚠️ Failed to load knowledge context: {str(e)}")
        
        # Generate AI response (grounded in context)
        ai_response = openai_service.generate_response(
            user_message=transcribed_text,
            knowledge_context=knowledge_context,
            conversation_history=[]
        )
        
        if ai_response["success"]:
            try:
                voice_cache.set(transcribed_text, ai_response["response"])
            except Exception as e:
                logger.warning("⚠️ Failed to save voice response to cache: %s", str(e))
            logger.info(f"✅ Voice message processed - {ai_response['tokens_used']} tokens")
            get_usage_tracker().record(
                ai_response.get("model") or "openai",
                ai_response.get("tokens_used") or 0,
            )
            return {
                "reply": ai_response["response"],
                "success": True,
                "user_id": str(dummy_user_id),
                "conversation_id": str(dummy_conversation_id),
                "message_id": str(uuid4()),
                "tokens_used": ai_response["tokens_used"],
                "model": ai_response["model"],
                "timestamp": datetime.now().isoformat(),
                "transcribed_text": transcribed_text,
                "error": None
            }
        else:
            logger.error(f"❌ Voice message processing error: {ai_response['error']}")
            get_usage_tracker().record(ai_response.get("model") or "openai", 0)
            return {
                "reply": ai_response["response"],
                "success": False,
                "user_id": str(dummy_user_id),
                "conversation_id": str(dummy_conversation_id),
                "message_id": str(uuid4()),
                "tokens_used": 0,
                "model": ai_response["model"],
                "timestamp": datetime.now().isoformat(),
                "transcribed_text": transcribed_text,
                "error": ai_response["error"]
            }
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"❌ Voice message error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"فشل معالجة الرسالة الصوتية: {str(e)}"
        )


async def transcribe_audio(audio_data: bytes, filename: str) -> str:
    """
    Transcribe audio to text using OpenAI Whisper API
    
    Args:
        audio_data: Audio file bytes
        filename: Original filename
    
    Returns:
        Transcribed text
    """
    try:
        import tempfile
        import os
        
        # Save audio to temporary file
        suffix = os.path.splitext(filename)[1] or '.webm'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_audio:
            temp_audio.write(audio_data)
            temp_audio_path = temp_audio.name
        
        try:
            # Use OpenAI Whisper API
            from openai import OpenAI
            client = OpenAI()
            
            with open(temp_audio_path, 'rb') as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="ar"  # Arabic
                )
            
            return transcript.text
        
        finally:
            # Clean up temp file
            if os.path.exists(temp_audio_path):
                os.remove(temp_audio_path)
    
    except Exception as e:
        logger.error(f"❌ Transcription error: {str(e)}")
        # Fallback: return placeholder text
        return "لم أتمكن من فهم الرسالة الصوتية. يرجى المحاولة مرة أخرى أو الكتابة."
