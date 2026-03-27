"""Runtime orchestration for send_message_with_attachment.

This module extracts the large routing/orchestration decision tree from
message_service while preserving behavior.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.services.runtime.entity_memory import update_entity_memory
from app.services.runtime.results_from_report_service import interpret_uploaded_lab_report_text
from uuid import UUID

_REPORT_ATTACHMENT_FALLBACK = "لم أتمكن من قراءة القيم بشكل واضح من التقرير..."
_REPORT_DEBUG_DIR = Path("app/data/runtime/debug/report_interpretation")


def _persist_report_debug_snapshot(
    *,
    attachment_filename: str | None,
    attachment_content_type: str | None,
    extracted_context: str,
    bridged_result: dict[str, Any] | None,
    matched: bool,
    final_answer: str,
) -> None:
    """Persist a temporary debug snapshot for attachment-based report interpretation."""
    try:
        _REPORT_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        snapshot_path = _REPORT_DEBUG_DIR / f"report_debug_{ts}.json"
        payload = {
            "timestamp_utc": ts,
            "attachment_filename": attachment_filename or "",
            "attachment_content_type": attachment_content_type or "",
            "extracted_context_preview": (extracted_context or "")[:4000],
            "matched": bool(matched),
            "final_answer": final_answer or "",
            "results_debug": dict((bridged_result or {}).get("debug") or {}),
        }
        snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # Debug instrumentation must never affect runtime behavior.
        return


@dataclass(frozen=True)
class RuntimeOrchestrationDeps:
    logger: Any
    save_assistant_reply: Callable[..., Any]
    get_history_for_ai: Callable[[], list[dict[str, str]]]
    is_simple_greeting: Callable[[str], bool]
    route_runtime_message: Callable[..., dict[str, Any]]
    resolve_faq_response: Callable[[str], tuple[str | None, dict[str, Any] | None]]
    normalize_text_ar: Callable[[str], str]
    is_general_price_query: Callable[[str], bool]
    detect_preparation_priority: Callable[[str, str], bool]
    is_test_related_question: Callable[[str], bool]
    is_symptoms_query: Callable[[str], bool]
    user_explicitly_asked_home_visit: Callable[[str], bool]
    classify_light_intent: Callable[[str], tuple[str, dict[str, Any]]]
    branch_lookup_bypass_reply: Callable[[str, UUID, str], str | None]
    package_lookup_bypass_reply: Callable[[str, UUID], str | None]
    runtime_tests_rag_reply: Callable[..., str | None]
    resolve_preparation_button_reply: Callable[[str], str | None]
    symptoms_rag_bypass_reply: Callable[[str], str | None]
    get_site_fallback_context: Callable[..., str]
    safe_clarify_message: Callable[[str, str], str]
    classify_intent: Callable[[str], dict[str, Any]]
    is_report_explanation_request: Callable[[str], bool]
    parse_lab_report_text: Callable[[str], Any]
    compose_report_summary: Callable[[Any], str]
    is_rag_ready: Callable[[], bool]
    retrieve: Callable[..., tuple[list[dict[str, Any]], bool]]
    filter_rag_results_by_intent: Callable[[list[dict[str, Any]], str], list[dict[str, Any]]]
    format_rag_results_context: Callable[..., str]
    get_knowledge_context: Callable[..., str]
    build_style_guidance_block_for_intent: Callable[[str, str], str]
    openai_generate_response: Callable[..., dict[str, Any]]
    compose_context_fallback: Callable[[str, str, dict[str, Any], str | None], str]
    sanitize_branch_location_response: Callable[[str, bool, bool], str]
    ensure_result_time_clause: Callable[[str, str], str]
    enforce_escalation_policy: Callable[[str], str]
    settings: Any
    no_info_message: str
    rag_knowledge_path: str
    rag_embeddings_path: str
    customer_service_phone: str


def run_message_runtime_orchestration(
    *,
    question_for_ai: str,
    expanded_query: str,
    ai_prompt: str,
    attachment_content: bytes | None,
    attachment_filename: str | None,
    attachment_content_type: str | None,
    extracted_context: str,
    conversation_id: UUID,
    recent_runtime_messages: list[dict[str, str]],
    gender: str,
    system_rebuild_mode: bool,
    faq_only_runtime_mode: bool,
    deps: RuntimeOrchestrationDeps,
) -> Any:
    """Execute the existing runtime orchestration flow and return saved reply tuple."""
    if attachment_content:
        if (extracted_context or "").strip():
            bridged = interpret_uploaded_lab_report_text(extracted_context)
            if bool(bridged.get("matched")):
                deps.logger.info("report interpretation bridge matched | source=results_from_report_service")
                final_answer = str(bridged.get("answer") or "").strip()
                _persist_report_debug_snapshot(
                    attachment_filename=attachment_filename,
                    attachment_content_type=attachment_content_type,
                    extracted_context=extracted_context,
                    bridged_result=bridged,
                    matched=True,
                    final_answer=final_answer,
                )
                return deps.save_assistant_reply(final_answer)
            deps.logger.info("report interpretation bridge did not match | source=results_from_report_service")
            _persist_report_debug_snapshot(
                attachment_filename=attachment_filename,
                attachment_content_type=attachment_content_type,
                extracted_context=extracted_context,
                bridged_result=bridged,
                matched=False,
                final_answer=_REPORT_ATTACHMENT_FALLBACK,
            )
            return deps.save_assistant_reply(_REPORT_ATTACHMENT_FALLBACK)
        deps.logger.info("report interpretation skipped | reason=empty_extracted_context")
        _persist_report_debug_snapshot(
            attachment_filename=attachment_filename,
            attachment_content_type=attachment_content_type,
            extracted_context=extracted_context,
            bridged_result=None,
            matched=False,
            final_answer=_REPORT_ATTACHMENT_FALLBACK,
        )
        return deps.save_assistant_reply(_REPORT_ATTACHMENT_FALLBACK)

    deps.logger.info(
        "orchestration checkpoint | called=yes | runtime_mode_active=%s | has_attachment=%s | attachment_filename=%s | extracted_present=%s | extracted_len=%s",
        bool(system_rebuild_mode or faq_only_runtime_mode),
        bool(attachment_content),
        attachment_filename,
        bool((extracted_context or "").strip()),
        len(extracted_context or ""),
    )
    runtime_mode_active = system_rebuild_mode or faq_only_runtime_mode
    if runtime_mode_active:
        deps.logger.info(
            "report bridge checkpoint | entering_runtime_mode_bridge=%s | has_attachment=%s | extracted_present=%s | extracted_preview=%s",
            True,
            bool(attachment_content),
            bool((extracted_context or "").strip()),
            (extracted_context or "").replace("\n", " ")[:500],
        )
        if attachment_content and extracted_context:
            bridged = interpret_uploaded_lab_report_text(extracted_context)
            deps.logger.info(
                "report bridge checkpoint | called=yes | matched=%s | items_count=%s",
                bool(bridged.get("matched")),
                len(bridged.get("items") or []),
            )
            if bool(bridged.get("matched")):
                deps.logger.info("report interpretation bridge matched in runtime mode | source=results_from_report_service")
                return deps.save_assistant_reply(str(bridged.get("answer") or "").strip())

        runtime_result = deps.route_runtime_message(
            question_for_ai,
            conversation_id=conversation_id,
            system_rebuild_mode=system_rebuild_mode,
            faq_only_runtime_mode=faq_only_runtime_mode,
            recent_runtime_messages=recent_runtime_messages,
        )

        deps.logger.info(
            "runtime router handled message | route=%s | source=%s | matched=%s | meta=%s",
            runtime_result.get("route"),
            runtime_result.get("source"),
            runtime_result.get("matched"),
            runtime_result.get("meta"),
        )
        if bool(runtime_result.get("matched")):
            source = str(runtime_result.get("source") or "").strip()
            meta = dict(runtime_result.get("meta") or {})
            if source == "branches":
                update_entity_memory(
                    conversation_id,
                    last_intent="branch",
                    last_branch={
                        "id": str(meta.get("matched_branch_id") or meta.get("id") or "").strip(),
                        "label": str(meta.get("branch_name") or "").strip(),
                        "city": str(meta.get("city") or "").strip(),
                    },
                )
            elif source in {"tests", "tests_business"}:
                update_entity_memory(
                    conversation_id,
                    last_intent="test",
                    last_test={
                        "id": str(meta.get("matched_test_id") or "").strip(),
                        "label": str(meta.get("matched_test_name") or "").strip(),
                    },
                )
            elif source in {"packages", "packages_business"}:
                update_entity_memory(
                    conversation_id,
                    last_intent="package",
                    last_package={
                        "id": str(meta.get("matched_package_id") or "").strip(),
                        "label": str(meta.get("matched_package_name") or "").strip(),
                    },
                )
        deps.logger.debug("runtime route path=%s", runtime_result.get("route"))
        return deps.save_assistant_reply(str(runtime_result.get("reply") or "").strip())

    history = deps.get_history_for_ai()

    # A. GREETING
    if deps.is_simple_greeting(question_for_ai):
        print("PATH=greeting")
        return deps.save_assistant_reply(
            "مرحبا، معاكم مختبر وريد الطبية، كيف ممكن أخدمك اليوم؟"
        )

    # B. FAQ
    faq_reply, faq_meta = deps.resolve_faq_response(question_for_ai)
    if faq_reply:
        match_method = str((faq_meta or {}).get("_match_method") or "unknown")
        faq_intent = str((faq_meta or {}).get("_faq_intent") or "")
        route_name = "faq_safe" if match_method == "faq_safe" else "faq"
        deps.logger.info(
            "faq route matched | route=%s | faq_intent=%s | faq_id=%s | match_method=%s | match_score=%s | matched_q_norm=%s",
            route_name,
            faq_intent or "n/a",
            (faq_meta or {}).get("id"),
            match_method,
            (faq_meta or {}).get("_match_score", "n/a"),
            str((faq_meta or {}).get("_matched_q_norm") or (faq_meta or {}).get("q_norm") or "")[:180],
        )
        print("PATH=faq_safe" if route_name == "faq_safe" else "PATH=faq")
        return deps.save_assistant_reply(faq_reply)

    # C. PRICE
    price_query_norm = deps.normalize_text_ar(question_for_ai)
    is_price_query = deps.is_general_price_query(question_for_ai) or any(
        token in price_query_norm for token in ("سعر", "اسعار", "أسعار", "price", "cost")
    )
    if is_price_query:
        print("PATH=price")
        return deps.save_assistant_reply(
            "للاستفسار عن الأسعار يرجى التواصل مع الفريق على الرقم: 920003694"
        )

    # D-H helpers
    preparation_priority = deps.detect_preparation_priority(question_for_ai, expanded_query)
    test_related_for_rag = deps.is_test_related_question(question_for_ai) or preparation_priority
    symptoms_query = deps.is_symptoms_query(question_for_ai)
    user_asked_home_visit = deps.user_explicitly_asked_home_visit(question_for_ai)

    light_intent, light_intent_meta = deps.classify_light_intent(expanded_query)
    deps.logger.info(
        "light intent classification | intent=%s | meta=%s",
        light_intent,
        light_intent_meta,
    )

    # D. BRANCHES
    branch_bypass_reply = deps.branch_lookup_bypass_reply(expanded_query, conversation_id, light_intent)
    if branch_bypass_reply:
        print("PATH=branches")
        return deps.save_assistant_reply(branch_bypass_reply)

    # E. PACKAGES
    package_bypass_reply = deps.package_lookup_bypass_reply(expanded_query, conversation_id)
    if package_bypass_reply:
        print("PATH=packages")
        return deps.save_assistant_reply(package_bypass_reply)

    # F. TEST_DEFINITION
    if test_related_for_rag and not preparation_priority and not symptoms_query:
        rag_reply = deps.runtime_tests_rag_reply(
            question=question_for_ai,
            expanded_query=expanded_query,
            history=history,
        )
        if rag_reply:
            print("PATH=test_definition")
            return deps.save_assistant_reply(rag_reply)

    # G. TEST_PREPARATION
    if preparation_priority:
        prep_button_reply = deps.resolve_preparation_button_reply(question_for_ai)
        if prep_button_reply:
            print("PATH=test_preparation")
            return deps.save_assistant_reply(prep_button_reply)
        prep_rag_reply = deps.runtime_tests_rag_reply(
            question=question_for_ai,
            expanded_query=expanded_query,
            history=history,
        )
        if prep_rag_reply:
            print("PATH=test_preparation")
            return deps.save_assistant_reply(prep_rag_reply)

    # H. TEST_SYMPTOMS
    symptoms_bypass_reply = deps.symptoms_rag_bypass_reply(question_for_ai)
    if symptoms_bypass_reply:
        print("PATH=test_symptoms")
        return deps.save_assistant_reply(symptoms_bypass_reply)

    # I. SITE_FALLBACK
    site_context = deps.get_site_fallback_context(question_for_ai, max_chunks=3)
    if site_context and site_context.strip():
        print("PATH=site_fallback")
        return deps.save_assistant_reply("حسب معلومات الموقع:\n" + site_context)

    # J. CLARIFY
    is_pdf_attachment = bool(
        attachment_content and (attachment_filename or "").lower().endswith(".pdf")
    )
    if not is_pdf_attachment:
        deps.logger.warning(
            "ROUTING_LOCKDOWN | no route A-J matched | bypassing legacy routing | q='%s'",
            question_for_ai[:120],
        )
        print("PATH=clarify")
        return deps.save_assistant_reply(deps.safe_clarify_message(deps.customer_service_phone, gender))

    route_type = "pdf_attachment"
    intent_payload = deps.classify_intent(question_for_ai)
    intent = intent_payload.get("intent", "services_overview")
    slots = intent_payload.get("slots", {}) or {}
    detected_tokens = slots.get("detected_tokens") or []

    wants_report_explain = (
        intent in {"report_explanation", "test_definition"}
        or deps.is_report_explanation_request(question_for_ai)
    )
    if wants_report_explain and extracted_context:
        bridged = interpret_uploaded_lab_report_text(extracted_context)
        if bool(bridged.get("matched")):
            return deps.save_assistant_reply(str(bridged.get("answer") or ""))
        parsed_rows = deps.parse_lab_report_text(extracted_context)
        report_reply = deps.compose_report_summary(parsed_rows)
        return deps.save_assistant_reply(report_reply)

    threshold = getattr(deps.settings, "RAG_SIMILARITY_THRESHOLD", 0.58)
    merged_context_parts: list[str] = []
    rag_chunk_count = 0
    rag_top_score = 0.0
    has_kb_hit = False
    fallback_used = False

    deps.logger.info(
        "retrieval called | query='%s' | rag_ready=%s | knowledge_index='%s' | embeddings_index='%s' | kb_namespace='%s'",
        question_for_ai[:120],
        deps.is_rag_ready(),
        deps.rag_knowledge_path,
        deps.rag_embeddings_path,
        "knowledge_base_with_faq.json",
    )

    if deps.is_rag_ready():
        try:
            rag_results, rag_has_hit = deps.retrieve(
                question_for_ai,
                max_results=3,
                similarity_threshold=threshold,
            )
            rag_results = deps.filter_rag_results_by_intent(rag_results, light_intent)
            rag_has_hit = bool(rag_results)
            rag_chunk_count = len(rag_results)
            rag_top_score = float(rag_results[0]["score"]) if rag_results else 0.0
            deps.logger.info(
                "retrieval rag | called=yes | chunks=%s | top_score=%.3f | has_hit=%s",
                rag_chunk_count,
                rag_top_score,
                bool(rag_has_hit),
            )
            if rag_has_hit:
                rag_context = deps.format_rag_results_context(rag_results, include_prices=True)
                if rag_context:
                    merged_context_parts.append(rag_context)
        except Exception as e:
            deps.logger.warning("retrieval rag failed: %s", e)
    else:
        deps.logger.info("retrieval rag | called=no | reason=rag_not_ready")

    try:
        kb_context = deps.get_knowledge_context(
            user_message=question_for_ai,
            max_tests=3,
            max_faqs=2,
            include_prices=True,
        )
        has_kb_hit = bool(kb_context and "لم يتم العثور على معلومات محددة" not in kb_context)
        deps.logger.info(
            "retrieval kb | called=yes | has_hit=%s | context_len=%s",
            has_kb_hit,
            len(kb_context or ""),
        )
        if has_kb_hit:
            merged_context_parts.append(kb_context)
    except Exception as e:
        deps.logger.warning("retrieval kb failed: %s", e)

    knowledge_context = None
    if merged_context_parts:
        seen = set()
        unique_parts = []
        for part in merged_context_parts:
            key = part.strip()
            if key and key not in seen:
                seen.add(key)
                unique_parts.append(part)
        if unique_parts:
            knowledge_context = "\n\n".join(unique_parts)

    style_guidance_block = deps.build_style_guidance_block_for_intent(question_for_ai, light_intent)
    intent_guidance_block = f"Intent: {light_intent}"
    combined_context = "\n\n".join(
        [part for part in [knowledge_context, intent_guidance_block, style_guidance_block] if part]
    ) or None

    deps.logger.info(
        "prompt context injection | context_injected=%s | context_len=%s | style_examples=%s | light_intent=%s",
        bool(combined_context),
        len(combined_context or ""),
        bool(style_guidance_block),
        light_intent,
    )

    ai_result = deps.openai_generate_response(
        user_message=ai_prompt,
        knowledge_context=combined_context,
        conversation_history=history,
    )
    llm_success = bool(ai_result.get("success"))
    assistant_content = ai_result.get("response") or "عذرًا، حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى."
    tokens = ai_result.get("tokens_used") or 0
    deps.logger.info(
        "response generation | intent=%s | route=%s | llm_success=%s | fallback_used=%s | kb_hit=%s | rag_chunks=%s | rag_top_score=%.3f | context_len=%s",
        intent,
        route_type,
        llm_success,
        fallback_used,
        has_kb_hit,
        rag_chunk_count,
        rag_top_score,
        len(knowledge_context or ""),
    )

    if not llm_success:
        assistant_content = deps.compose_context_fallback(question_for_ai, intent, slots, knowledge_context)
        tokens = 0
        fallback_used = True
        deps.logger.warning(
            "llm unavailable -> fallback answer used | intent=%s | route=%s | rag_ready=%s",
            intent,
            route_type,
            deps.is_rag_ready(),
        )
        deps.logger.info(
            "fallback diagnostics | detected_tokens=%s | intent=%s | route=%s | kb_hit=%s | rag_chunks=%s | rag_top_score=%.3f | llm_status=failed | fallback_used=%s",
            detected_tokens,
            intent,
            route_type,
            has_kb_hit,
            rag_chunk_count,
            rag_top_score,
            fallback_used,
        )

    if knowledge_context and ("لا تتوفر لدي معلومات" in assistant_content or deps.no_info_message in assistant_content):
        deps.logger.info("model returned generic miss despite retrieval hit; retrying grounded answer")
        retry_result = deps.openai_generate_response(
            user_message=f"استخدم المعلومات المسترجعة للإجابة بدقة على: {question_for_ai}",
            knowledge_context=combined_context,
            conversation_history=history,
        )
        retry_response = retry_result.get("response")
        if retry_response:
            assistant_content = retry_response
            tokens = retry_result.get("tokens_used") or tokens

    if light_intent == "branch_location":
        assistant_content = deps.sanitize_branch_location_response(
            assistant_content,
            bool(light_intent_meta.get("has_city_or_area")),
            allow_home_visit=user_asked_home_visit,
        )
    assistant_content = deps.ensure_result_time_clause(assistant_content, light_intent)
    assistant_content = deps.enforce_escalation_policy(assistant_content)

    return deps.save_assistant_reply(assistant_content, token_count=tokens)
