"""
Emergency routing lockdown for send_message_with_attachment.
Replaces everything after `history = get_conversation_history_for_ai(...)` to EOF.
"""
import sys

PATH = r"app\services\message_service.py"

with open(PATH, "r", encoding="utf-8") as f:
    content = f.read()

SPLIT_ANCHOR = "    history = get_conversation_history_for_ai(db, conv, max_messages=20)\n"

idx = content.rfind(SPLIT_ANCHOR)   # rfind – use the last occurrence (inside the function)
if idx == -1:
    print("ERROR: split anchor not found", file=sys.stderr)
    sys.exit(1)

# Keep everything up to and including the anchor line.
prefix = content[: idx + len(SPLIT_ANCHOR)]

# ── NEW ROUTING BODY ─────────────────────────────────────────────────────────
NEW_BODY = '''
    # ══════════════════════════════════════════════════════════════════════
    # ROUTING LADDER  A → B → C → D → E → F → G → H → I → J
    # Each path returns immediately on match.
    # Legacy route_question() / intent routing / LLM pipeline are bypassed
    # for plain text chat (emergency routing lockdown).
    # ══════════════════════════════════════════════════════════════════════

    # A. GREETING
    if _is_simple_greeting(question_for_ai):
        print("PATH=greeting")
        return _save_assistant_reply(
            "مرحبا، معاكم مختبر وريد الطبية، كيف ممكن أخدمك اليوم؟"
        )

    # Pre-routing guards (booking flows, stateful multi-turn – not topic routing).
    services_start_reply = _resolve_services_branches_home_visit_start_reply(conversation_id, question_for_ai)
    if services_start_reply:
        return _save_assistant_reply(services_start_reply)

    preparation_priority = _detect_preparation_priority(question_for_ai, expanded_query)
    test_related_for_rag = is_test_related_question(question_for_ai) or preparation_priority

    home_visit_booking_reply = _resolve_home_visit_booking_reply(db, conversation_id, question_for_ai)
    if home_visit_booking_reply:
        return _save_assistant_reply(home_visit_booking_reply)

    phone_followup_reply = _resolve_customer_phone_followup(db, conversation_id, question_for_ai)
    if phone_followup_reply:
        return _save_assistant_reply(phone_followup_reply)

    if _is_working_hours_query(question_for_ai):
        return _save_assistant_reply(_working_hours_deterministic_reply())

    stateful_reply = _handle_stateful_conversation(conversation_id, question_for_ai)
    if stateful_reply:
        return _save_assistant_reply(stateful_reply)

    # B. FAQ – runtime lookup from faq_index.json wins unconditionally.
    runtime_faq_match = _runtime_faq_lookup(expanded_query)
    if runtime_faq_match and runtime_faq_match.get("a"):
        print("PATH=faq", runtime_faq_match.get("id"))
        return _save_assistant_reply(str(runtime_faq_match.get("a")).strip())

    # C. PRICE – fixed contact message (emergency lockdown, all price intents unified).
    _price_hit = _runtime_price_lookup_reply(expanded_query, gender)
    if _price_hit or _is_general_price_query(question_for_ai):
        print("PATH=price")
        return _save_assistant_reply(
            "للاستفسار عن الأسعار يرجى التواصل مع الفريق على الرقم: 920003694"
        )

    # Light-intent classification needed before D. BRANCHES.
    user_asked_home_visit = _user_explicitly_asked_home_visit(question_for_ai)
    light_intent, light_intent_meta = _classify_light_intent(expanded_query)
    logger.info(
        "light intent classification | intent=%s | meta=%s",
        light_intent,
        light_intent_meta,
    )

    # D. BRANCHES
    branch_bypass_reply = _branch_lookup_bypass_reply(expanded_query, conversation_id, light_intent)
    if branch_bypass_reply:
        print("PATH=branches")
        return _save_assistant_reply(branch_bypass_reply)

    # E. PACKAGES
    package_bypass_reply = _package_lookup_bypass_reply(expanded_query, conversation_id)
    if package_bypass_reply:
        print("PATH=packages")
        return _save_assistant_reply(package_bypass_reply)

    # F. TEST_DEFINITION
    if test_related_for_rag and not preparation_priority:
        rag_reply = _runtime_tests_rag_reply(
            question=question_for_ai,
            expanded_query=expanded_query,
            history=history,
        )
        if rag_reply:
            print("PATH=test_definition")
            return _save_assistant_reply(rag_reply)

    # G. TEST_PREPARATION
    if preparation_priority:
        prep_button_reply = _resolve_preparation_button_reply(question_for_ai)
        if prep_button_reply:
            print("PATH=test_preparation")
            return _save_assistant_reply(prep_button_reply)
        prep_rag_reply = _runtime_tests_rag_reply(
            question=question_for_ai,
            expanded_query=expanded_query,
            history=history,
        )
        if prep_rag_reply:
            print("PATH=test_preparation")
            return _save_assistant_reply(prep_rag_reply)

    # H. TEST_SYMPTOMS
    symptoms_bypass_reply = _symptoms_rag_bypass_reply(question_for_ai)
    if symptoms_bypass_reply:
        print("PATH=test_symptoms")
        return _save_assistant_reply(symptoms_bypass_reply)

    # I. SITE_FALLBACK – general website info only (site_knowledge_chunks_hard.jsonl).
    site_context = get_site_fallback_context(question_for_ai, max_chunks=3)
    if site_context and site_context.strip():
        print("PATH=site_fallback")
        return _save_assistant_reply("حسب معلومات الموقع:\\n" + site_context)

    # J. CLARIFY – classify intent to detect explicit clarification need.
    intent_payload = classify_intent(question_for_ai)
    intent = intent_payload.get("intent", "services_overview")
    slots = intent_payload.get("slots", {}) or {}
    detected_tokens = slots.get("detected_tokens") or []
    logger.info(
        "intent classification | intent=%s | confidence=%s | slots=%s | detected_tokens=%s | needs_clarification=%s",
        intent,
        intent_payload.get("confidence"),
        slots,
        detected_tokens,
        intent_payload.get("needs_clarification"),
    )
    if intent_payload.get("needs_clarification") and intent_payload.get("clarifying_question"):
        print("PATH=clarify")
        return _save_assistant_reply(safe_clarify_message(WAREED_CUSTOMER_SERVICE_PHONE, gender))

    # ── ROUTING LOCKDOWN ────────────────────────────────────────────────────
    # Nothing in A-J matched.  For plain text / voice, stop here and clarify.
    # Bypassed:  route_question(), legacy intent routing (branches_locations /
    #            working_hours / symptom_based_suggestion etc.), and the generic
    #            RAG+LLM pipeline.  These were the source of repeated wrong answers.
    is_pdf_attachment = bool(
        attachment_content and (attachment_filename or "").lower().endswith(".pdf")
    )
    if not is_pdf_attachment:
        logger.warning(
            "ROUTING_LOCKDOWN | no route A-J matched | bypassing legacy routing | q=\'%s\'",
            question_for_ai[:120],
        )
        print("PATH=clarify")
        return _save_assistant_reply(safe_clarify_message(WAREED_CUSTOMER_SERVICE_PHONE, gender))

    # ── PDF attachment path only beyond this point ──────────────────────────
    # route_question() and legacy intent routing are NOT called.
    route_type = "pdf_attachment"

    # PDF report summarizer (works even if LLM is unavailable).
    wants_report_explain = (
        intent in {"report_explanation", "test_definition"}
        or is_report_explanation_request(question_for_ai)
    )
    if wants_report_explain and extracted_context:
        parsed_rows = parse_lab_report_text(extracted_context)
        report_reply = compose_report_summary(parsed_rows)
        return _save_assistant_reply(report_reply)

    threshold = getattr(settings, "RAG_SIMILARITY_THRESHOLD", 0.58)
    merged_context_parts: list[str] = []
    rag_chunk_count = 0
    rag_top_score = 0.0
    has_kb_hit = False
    fallback_used = False

    logger.info(
        "retrieval called | query=\'%s\' | rag_ready=%s | knowledge_index=\'%s\' | embeddings_index=\'%s\' | kb_namespace=\'%s\'",
        question_for_ai[:120],
        is_rag_ready(),
        RAG_KNOWLEDGE_PATH,
        RAG_EMBEDDINGS_PATH,
        "knowledge_base_with_faq.json",
    )

    if is_rag_ready():
        try:
            rag_results, rag_has_hit = retrieve(
                question_for_ai,
                max_results=3,
                similarity_threshold=threshold,
            )
            rag_results = _filter_rag_results_by_intent(rag_results, light_intent)
            rag_has_hit = bool(rag_results)
            rag_chunk_count = len(rag_results)
            rag_top_score = float(rag_results[0]["score"]) if rag_results else 0.0
            logger.info(
                "retrieval rag | called=yes | chunks=%s | top_score=%.3f | has_hit=%s",
                rag_chunk_count,
                rag_top_score,
                bool(rag_has_hit),
            )
            if rag_has_hit:
                rag_context = _format_rag_results_context(rag_results, include_prices=True)
                if rag_context:
                    merged_context_parts.append(rag_context)
        except Exception as e:
            logger.warning("retrieval rag failed: %s", e)
    else:
        logger.info("retrieval rag | called=no | reason=rag_not_ready")

    # Broader KB retrieval (tests + FAQs/services/packages).
    try:
        kb_context = get_knowledge_context(
            user_message=question_for_ai,
            max_tests=3,
            max_faqs=2,
            include_prices=True,
        )
        has_kb_hit = bool(kb_context and "لم يتم العثور على معلومات محددة" not in kb_context)
        logger.info(
            "retrieval kb | called=yes | has_hit=%s | context_len=%s",
            has_kb_hit,
            len(kb_context or ""),
        )
        if has_kb_hit:
            merged_context_parts.append(kb_context)
    except Exception as e:
        logger.warning("retrieval kb failed: %s", e)

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
            knowledge_context = "\\n\\n".join(unique_parts)

    style_guidance_block = _build_style_guidance_block_for_intent(question_for_ai, light_intent)
    intent_guidance_block = f"Intent: {light_intent}"
    combined_context = "\\n\\n".join(
        [part for part in [knowledge_context, intent_guidance_block, style_guidance_block] if part]
    ) or None

    logger.info(
        "prompt context injection | context_injected=%s | context_len=%s | style_examples=%s | light_intent=%s",
        bool(combined_context),
        len(combined_context or ""),
        bool(style_guidance_block),
        light_intent,
    )

    ai_result = openai_service.generate_response(
        user_message=ai_prompt,
        knowledge_context=combined_context,
        conversation_history=history,
    )
    llm_success = bool(ai_result.get("success"))
    assistant_content = ai_result.get("response") or "عذرًا، حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى."
    tokens = ai_result.get("tokens_used") or 0
    logger.info(
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
        assistant_content = compose_context_fallback(question_for_ai, intent, slots, knowledge_context)
        tokens = 0
        fallback_used = True
        logger.warning(
            "llm unavailable -> fallback answer used | intent=%s | route=%s | rag_ready=%s",
            intent,
            route_type,
            is_rag_ready(),
        )
        logger.info(
            "fallback diagnostics | detected_tokens=%s | intent=%s | route=%s | kb_hit=%s | rag_chunks=%s | rag_top_score=%.3f | llm_status=failed | fallback_used=%s",
            detected_tokens,
            intent,
            route_type,
            has_kb_hit,
            rag_chunk_count,
            rag_top_score,
            fallback_used,
        )

    # If KB hit exists but model produced generic miss, retry with explicit grounding.
    if knowledge_context and ("لا تتوفر لدي معلومات" in assistant_content or NO_INFO_MESSAGE in assistant_content):
        logger.info("model returned generic miss despite retrieval hit; retrying grounded answer")
        retry_result = openai_service.generate_response(
            user_message=f"استخدم المعلومات المسترجعة للإجابة بدقة على: {question_for_ai}",
            knowledge_context=combined_context,
            conversation_history=history,
        )
        retry_response = retry_result.get("response")
        if retry_response:
            assistant_content = retry_response
            tokens = retry_result.get("tokens_used") or tokens

    if light_intent == "branch_location":
        assistant_content = _sanitize_branch_location_response(
            assistant_content,
            bool(light_intent_meta.get("has_city_or_area")),
            allow_home_visit=user_asked_home_visit,
        )
    assistant_content = _ensure_result_time_clause(assistant_content, light_intent)
    assistant_content = _enforce_escalation_policy(assistant_content)

    return _save_assistant_reply(assistant_content, token_count=tokens)
'''

new_content = prefix + NEW_BODY

with open(PATH, "w", encoding="utf-8") as f:
    f.write(new_content)

print("SUCCESS: routing lockdown applied.")
