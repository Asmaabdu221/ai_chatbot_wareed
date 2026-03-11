import json
from uuid import uuid4

import pytest

from app.services import message_service


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


@pytest.fixture()
def faq_runtime_file(tmp_path, monkeypatch):
    faq_path = tmp_path / "faq_clean.jsonl"
    rows = [
        {
            "id": "faq::2",
            "question": "هل يوفر مختبر وريد خدمة الزيارات المنزلية؟",
            "answer": "نعم، نوفر خدمة سحب العينات من المنزل أو مقر العمل.",
            "q_norm": "هل يوفر مختبر وريد خدمه الزيارات المنزليه",
        },
        {
            "id": "faq::6",
            "question": "هل يتم إرسال النتائج إلكترونياً؟",
            "answer": "نعم، يمكن إرسال النتائج عبر الواتساب والتطبيق والبريد الإلكتروني.",
            "q_norm": "هل يتم ارسال النتائج الكترونيا",
        },
        {
            "id": "faq::13",
            "question": "هل نتائج التحاليل سرية؟",
            "answer": "نعم، نتائج التحاليل سرية ويتم حفظها ضمن نظام آمن.",
            "q_norm": "هل نتائج التحاليل سريه",
        },
    ]
    _write_jsonl(faq_path, rows)
    monkeypatch.setattr(message_service, "FAQ_CLEAN_PATH", faq_path)
    message_service._FAQ_CACHE = None
    yield faq_path
    message_service._FAQ_CACHE = None


@pytest.mark.parametrize(
    "query",
    [
        "في عندكم سحب من البيت",
        "تجون البيت تسحبون العينة؟",
        "فيه خدمة سحب عينات من البيت؟",
        "تقدرون تجون تاخذون العينة من البيت؟",
        "تقدرون تجون تاخذون العينة",
        "هل السحب المنزلي متوفر؟",
        "عندكم خدمة سحب من المنزل؟",
        "تجون للمكتب تسحبون العينة؟",
    ],
)
def test_home_visit_dialect_phrases_match_faq(query, faq_runtime_file):
    match = message_service._runtime_faq_lookup(query)
    if match is None:
        intent = message_service._recognize_faq_class_intent(query)
        assert intent == "home_visit"
        match = message_service._runtime_faq_lookup_by_class_intent(intent)
    assert match is not None
    assert match["id"] == "faq::2"


@pytest.mark.parametrize(
    "query",
    [
        "كيف استلم النتيجة؟",
        "كيف استلم نتيجتي",
        "النتيجة تجيني كيف؟",
        "ترسلونها واتساب؟",
        "عادي ترسلونها بالواتس",
        "اقدر اشوف النتيجة اونلاين؟",
    ],
)
def test_results_delivery_dialect_phrases_match_faq(query, faq_runtime_file):
    match = message_service._runtime_faq_lookup(query)
    if match is None:
        intent = message_service._recognize_faq_class_intent(query)
        assert intent == "results_delivery"
        match = message_service._runtime_faq_lookup_by_class_intent(intent)
    assert match is not None
    assert match["id"] == "faq::6"


@pytest.mark.parametrize(
    "query",
    [
        "هل التحاليل سرية؟",
        "هل احد يقدر يشوف نتيجتي؟",
        "في حد غيري يقدر يشوف نتيجتي",
        "هل المعلومات الطبية خاصة؟",
        "هل النتائج سرية؟",
    ],
)
def test_privacy_dialect_phrases_match_faq(query, faq_runtime_file):
    match = message_service._runtime_faq_lookup(query)
    if match is None:
        intent = message_service._recognize_faq_class_intent(query)
        assert intent == "privacy"
        match = message_service._runtime_faq_lookup_by_class_intent(intent)
    assert match is not None
    assert match["id"] == "faq::13"


def test_faq_class_queries_do_not_hijack_package_route(faq_runtime_file, monkeypatch):
    fake_record = {
        "id": "pkg::1",
        "name_raw": "تحليل الأمراض المناعية (ANA TEST)",
        "description_raw": "وصف",
        "price_raw": "100 ريال",
        "turnaround_text": "",
        "sample_type_text": "",
    }

    monkeypatch.setattr(message_service, "match_single_package", lambda _q: fake_record)
    monkeypatch.setattr(message_service, "search_packages", lambda _q, top_k=6: [fake_record])
    monkeypatch.setattr(message_service, "semantic_search_packages", lambda _q, top_k=3: [{"id": "pkg::1", "score": 0.99}])

    faq_like_queries = [
        "في عندكم سحب من البيت",
        "تجون البيت تسحبون العينة؟",
        "فيه خدمة سحب عينات من البيت؟",
        "تقدرون تجون تاخذون العينة",
        "كيف استلم النتيجة؟",
        "كيف استلم نتيجتي",
        "النتيجة تجيني كيف؟",
        "عادي ترسلونها بالواتس",
        "هل التحاليل سرية؟",
        "هل احد يقدر يشوف نتيجتي؟",
        "في حد غيري يقدر يشوف نتيجتي",
    ]

    for query in faq_like_queries:
        reply = message_service._package_lookup_bypass_reply(query, uuid4())
        assert reply is None


def test_faq_class_safe_fallback_when_intent_has_no_record(tmp_path, monkeypatch):
    faq_path = tmp_path / "faq_clean.jsonl"
    rows = [
        {
            "id": "faq::2",
            "question": "هل يوفر مختبر وريد خدمة الزيارات المنزلية؟",
            "answer": "نعم، نوفر خدمة سحب العينات من المنزل أو مقر العمل.",
            "q_norm": "هل يوفر مختبر وريد خدمه الزيارات المنزليه",
        }
    ]
    _write_jsonl(faq_path, rows)
    monkeypatch.setattr(message_service, "FAQ_CLEAN_PATH", faq_path)
    message_service._FAQ_CACHE = None

    assert message_service._runtime_faq_lookup_by_class_intent("privacy") is None
    safe_reply = message_service._safe_faq_class_fallback_reply("privacy")
    assert isinstance(safe_reply, str)
    assert safe_reply.strip()


def test_optional_faq_rephrase_keeps_faq_route(monkeypatch, faq_runtime_file):
    monkeypatch.setattr(message_service, "_is_faq_rephrase_enabled", lambda: True)
    monkeypatch.setattr(
        message_service.openai_service,
        "generate_response",
        lambda **kwargs: {
            "success": True,
            "response": "تقدر تشوف نتيجتك عبر الواتساب أو التطبيق أو البريد الإلكتروني بدون زيارة المركز.",
            "model": "mock",
            "tokens_used": 0,
            "error": None,
        },
    )
    answer, meta = message_service._resolve_faq_response("كيف استلم نتيجتي")
    assert isinstance(answer, str) and answer.strip()
    assert "الواتساب" in answer
    assert meta is not None
