"""
Grounding / anti-hallucination tests.

Covers the context-sufficiency guard, the safe fallback, and the retrieval
precision guard that prevents an unknown test (e.g. a price-phrase query for
a test we don't carry) from pulling in unrelated context.
"""

from __future__ import annotations

import pytest

from app.services.context_builder import is_context_sufficient, get_fallback_response
from app.data.lab_data_loader import DEFAULT_EXCEL


def test_is_context_sufficient():
    assert is_context_sufficient("") is False
    assert is_context_sufficient("   ") is False
    assert is_context_sufficient("too short") is False
    assert is_context_sufficient("x" * 60) is True
    # NEEDS_REVIEW with thin context is treated as insufficient
    assert is_context_sufficient("NEEDS_REVIEW " + "y" * 20) is False


def test_get_fallback_response_has_phone_and_safe_text():
    out = get_fallback_response()
    assert "8001221220" in out
    assert "قاعدة بياناتنا" in out
    assert "اكتب رقمك" in out


@pytest.mark.skipif(not DEFAULT_EXCEL.exists(), reason="workbook not found")
def test_known_query_grounded_and_unknown_query_empty():
    from app.services.lab_rag_integration import maybe_build_lab_context

    # Known test -> grounded, sufficient context.
    ctx_known = maybe_build_lab_context("كم سعر تحليل CBC", phone_captured=False)
    assert ctx_known and is_context_sufficient(ctx_known)

    # Unknown test inside a price phrase must NOT fuzzy-match an unrelated test.
    ctx_unknown = maybe_build_lab_context("كم سعر تحليل DNA", phone_captured=False)
    assert not (ctx_unknown and ctx_unknown.strip()), (
        "unknown price-phrase query should yield empty context, got: %r" % (ctx_unknown,)
    )


@pytest.mark.skipif(not DEFAULT_EXCEL.exists(), reason="workbook not found")
def test_offtopic_queries_yield_no_context():
    from app.services.lab_rag_integration import maybe_build_lab_context

    for q in ["ما هو علاج السرطان", "كم عدد سكان السعودية", "ما هو أفضل مستشفى في الرياض"]:
        ctx = maybe_build_lab_context(q, phone_captured=False)
        assert not (ctx and ctx.strip()), f"off-topic query should be empty: {q!r}"


@pytest.mark.skipif(not DEFAULT_EXCEL.exists(), reason="workbook not found")
def test_canonical_term_overrides():
    """Common consumer terms must resolve to the correct core tests, not the
    obscure ones the AI-generated synonym index would otherwise pick."""
    from app.services.lab_retrieval_engine import get_lab_retrieval_engine
    from app.services.intent_classifier import get_intent_classifier

    eng = get_lab_retrieval_engine(); eng.warm_up()
    clf = get_intent_classifier()

    def ids(q):
        return eng.retrieve(q, clf.classify(q)).test_ids

    # سكر -> Glucose (Fasting) + HbA1c
    assert set(ids("تحليل السكر")) == {"TEST_253", "TEST_258"}
    assert set(ids("ابي اعرف عن تحليل السكر")) == {"TEST_253", "TEST_258"}
    # دهون / كوليسترول -> Cholesterol + Triglycerides
    assert set(ids("تحليل الدهون")) == {"TEST_156", "TEST_524"}
    assert set(ids("هل تحليل الكوليسترول يحتاج صيام")) == {"TEST_156", "TEST_524"}
    # هيموجلوبين -> Hemoglobin Level
    assert ids("نتيجة الهيموجلوبين عندي 10 هل طبيعي") == ["TEST_272"]
    # token-boundary guard: عسكر must NOT trigger the سكر override
    assert "TEST_253" not in ids("عسكر")
    # unrelated known test stays correct
    assert "TEST_170" in ids("كم سعر CBC")
