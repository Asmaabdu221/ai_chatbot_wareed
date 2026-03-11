import json

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
            "id": "faq::1",
            "question": "ما هي الخدمات التي يقدمها مختبر وريد؟",
            "answer": "يقدم المختبر خدمات متعددة.",
            "q_norm": "ما هي الخدمات التي يقدمها مختبر وريد",
        },
        {
            "id": "faq::16",
            "question": "هل تحليل السكر التراكمي يحتاج صيام؟",
            "answer": "لا، تحليل السكر التراكمي لا يحتاج صيام.",
            "q_norm": "هل تحليل السكر التراكمي يحتاج صيام",
        },
    ]
    _write_jsonl(faq_path, rows)
    monkeypatch.setattr(message_service, "FAQ_CLEAN_PATH", faq_path)
    message_service._FAQ_CACHE = None
    yield faq_path
    message_service._FAQ_CACHE = None


def test_runtime_faq_exact_match(faq_runtime_file):
    match = message_service._runtime_faq_lookup("ما هي الخدمات التي يقدمها مختبر وريد؟")
    assert match is not None
    assert match["id"] == "faq::1"
    assert match["answer"] == "يقدم المختبر خدمات متعددة."
    assert match["_match_method"] == "exact"
    assert match["_match_score"] == 1.0


def test_runtime_faq_high_confidence_paraphrase_match(faq_runtime_file):
    match = message_service._runtime_faq_lookup("هل تحليل السكر التراكمي يحتاج صيام ولا لا")
    assert match is not None
    assert match["id"] == "faq::16"
    assert match["answer"] == "لا، تحليل السكر التراكمي لا يحتاج صيام."


def test_runtime_faq_unrelated_query_no_match(faq_runtime_file):
    match = message_service._runtime_faq_lookup("كيف ارفع طلب تأمين طبي؟")
    assert match is None


def test_runtime_faq_price_query_not_hijacked(faq_runtime_file):
    match = message_service._runtime_faq_lookup("كم سعر تحليل السكر التراكمي؟")
    assert match is None


def test_runtime_faq_branch_detail_query_not_hijacked(faq_runtime_file):
    match = message_service._runtime_faq_lookup("وين أقرب فرع في الرياض حي النخيل؟")
    assert match is None


def test_runtime_faq_package_detail_query_not_hijacked(faq_runtime_file):
    match = message_service._runtime_faq_lookup("تفاصيل باقة السكري والدهون")
    assert match is None


def test_runtime_faq_symptoms_query_not_hijacked(faq_runtime_file):
    match = message_service._runtime_faq_lookup("عندي صداع ودوخة من أمس")
    assert match is None
