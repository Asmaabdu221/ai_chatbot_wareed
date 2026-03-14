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


@pytest.fixture()
def faq_runtime_file_intent_map(tmp_path, monkeypatch):
    faq_path = tmp_path / "faq_clean.jsonl"
    rows = [
        {
            "id": "faq::1",
            "question": "ما هي الخدمات التي يقدمها مختبر وريد؟",
            "answer": "يقدم المختبر تحاليل طبية متعددة.",
            "q_norm": "ما هي الخدمات التي يقدمها مختبر وريد",
        },
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
            "id": "faq::11",
            "question": "هل توجد عروض أو تخفيضات حالياً؟",
            "answer": "نعم، توجد عروض وباقات تتغير حسب الفترة.",
            "q_norm": "هل توجد عروض او تخفيضات حاليا",
        },
        {
            "id": "faq::13",
            "question": "هل نتائج التحاليل سرية؟",
            "answer": "نعم، نتائج التحاليل سرية.",
            "q_norm": "هل نتائج التحاليل سريه",
        },
    ]
    _write_jsonl(faq_path, rows)
    monkeypatch.setattr(message_service, "FAQ_CLEAN_PATH", faq_path)
    message_service._FAQ_CACHE = None
    yield faq_path
    message_service._FAQ_CACHE = None


@pytest.fixture()
def faq_runtime_file_canonical_missed_cases(tmp_path, monkeypatch):
    faq_path = tmp_path / "faq_clean.jsonl"
    rows = [
        {
            "id": "faq::14",
            "question": "كيف اضمن خصوصية التحاليل الحساسة؟",
            "answer": "نحافظ على سرية وخصوصية التحاليل الحساسة وفق سياسات حماية البيانات.",
            "q_norm": "كيف اضمن خصوصيه التحاليل الحساسه",
        },
        {
            "id": "faq::16",
            "question": "هل تحليل السكر التراكمي HbA1c يحتاج صيام؟",
            "answer": "تحليل السكر التراكمي HbA1c لا يحتاج صيام.",
            "q_norm": "هل تحليل السكر التراكمي hba1c يحتاج صيام",
        },
        {
            "id": "faq::18",
            "question": "هل تحليل الغدة الدرقية TSH يحتاج صيام؟",
            "answer": "عادة تحاليل الغدة الدرقية مثل TSH لا تحتاج صيام.",
            "q_norm": "هل تحليل الغده الدرقيه tsh يحتاج صيام",
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


def test_privacy_access_question_starts_with_no_for_ghairi_phrase(faq_runtime_file):
    answer, meta = message_service._resolve_faq_response("في حد غيري يقدر يشوف نتيجتي")
    assert meta is not None
    assert (meta.get("id") == "faq::13") or (meta.get("_faq_intent") in {"privacy", "faq_privacy"})
    assert isinstance(answer, str) and answer.strip()
    assert answer.strip().startswith("لا")


def test_privacy_access_question_starts_with_no_for_ahad_phrase(faq_runtime_file):
    answer, meta = message_service._resolve_faq_response("هل احد يقدر يشوف نتيجتي؟")
    assert meta is not None
    assert (meta.get("id") == "faq::13") or (meta.get("_faq_intent") in {"privacy", "faq_privacy"})
    assert isinstance(answer, str) and answer.strip()
    assert answer.strip().startswith("لا")


def test_results_online_question_does_not_start_with_yes(faq_runtime_file):
    answer, meta = message_service._resolve_faq_response("اقدر اشوف النتيجة اونلاين")
    assert meta is not None
    assert (meta.get("id") == "faq::6") or (meta.get("_faq_intent") in {"results_delivery", "faq_results_delivery"})
    assert isinstance(answer, str) and answer.strip()
    assert not answer.strip().startswith("نعم")


@pytest.mark.parametrize(
    "query",
    [
        "هل اقدر اطلع نتيجيتي اونلاين و الا",
        "من وين اشوف النتيجة",
        "كيف اعرف نتيجتي",
    ],
)
def test_results_delivery_remaining_phrases_route_to_faq_and_not_package(query, faq_runtime_file):
    answer, meta = message_service._resolve_faq_response(query)
    assert isinstance(answer, str) and answer.strip()
    assert meta is not None
    assert (meta.get("id") == "faq::6") or (meta.get("_faq_intent") in {"results_delivery", "faq_results_delivery"})
    package_reply = message_service._package_lookup_bypass_reply(query, uuid4())
    assert package_reply is None


@pytest.mark.parametrize(
    "query, expected_intent, expected_id",
    [
        ("فيه خدمة زيارة منزلية للتحاليل؟", "faq_home_visit", "faq::2"),
        ("عادي ترسلونها بالواتس؟", "faq_results_delivery", "faq::6"),
        ("الموظفين يشوفون النتائج؟", "faq_privacy", "faq::13"),
        ("هل عندكم تخفيضات حاليا؟", "faq_offers_discounts", "faq::11"),
        ("ايش الخدمات اللي تقدمونها؟", "faq_general_services", "faq::1"),
    ],
)
def test_detect_intent_and_map_to_canonical_faq(query, expected_intent, expected_id, faq_runtime_file_intent_map):
    intent = message_service._detect_faq_intent(query)
    assert intent == expected_intent
    match = message_service._runtime_faq_lookup_by_intent(intent)
    assert match is not None
    assert match["id"] == expected_id
    assert match.get("_match_method") == "faq_intent_canonical"


@pytest.mark.parametrize(
    "query",
    [
        "عادي ترسلونها بالواتس؟",
        "كيف استلم نتيجتي؟",
        "اقدر اشوف نتيجتي اونلاين",
    ],
)
def test_multiple_results_phrasings_resolve_to_same_canonical_faq(query, faq_runtime_file_intent_map):
    answer, meta = message_service._resolve_faq_response(query)
    assert isinstance(answer, str) and answer.strip()
    assert meta is not None
    assert meta.get("_faq_intent") == "faq_results_delivery"
    assert meta.get("id") == "faq::6"


def test_booking_intent_detected_without_canonical_record_returns_safe_faq(faq_runtime_file_intent_map):
    intent = message_service._detect_faq_intent("لازم احجز قبل ما اجي؟")
    assert intent == "faq_booking_required"
    assert message_service._runtime_faq_lookup_by_intent(intent) is None
    answer, meta = message_service._resolve_faq_response("لازم احجز قبل ما اجي؟")
    assert isinstance(answer, str) and answer.strip()
    assert meta is not None
    assert meta.get("_match_method") == "faq_safe"
    assert meta.get("_faq_intent") == "faq_booking_required"


def test_not_faq_intent_keeps_normal_routing_path(faq_runtime_file_intent_map):
    assert message_service._detect_faq_intent("كم سعر تحليل فيتامين د") == "not_faq"


@pytest.mark.parametrize(
    "query, expected_id",
    [
        ("كيف اضمن خصوصيه التحاليل الحساسه", "faq::14"),
        ("تحليل السكر التراكمي يحتاج صيام او لا", "faq::16"),
        ("هل السكر التراكمي يحتاج صيام", "faq::16"),
        ("تحليل الغدة الدرقية يحتاج صيام", "faq::18"),
        ("هل تحليل TSH يحتاج صيام", "faq::18"),
    ],
)
def test_missed_faq_phrasings_resolve_to_expected_canonical_faq(
    query, expected_id, faq_runtime_file_canonical_missed_cases
):
    answer, meta = message_service._resolve_faq_response(query)
    assert isinstance(answer, str) and answer.strip()
    assert meta is not None
    assert meta.get("id") == expected_id
    assert meta.get("_match_method") == "faq_intent_canonical"
