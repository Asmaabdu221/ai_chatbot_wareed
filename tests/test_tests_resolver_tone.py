from app.services.runtime.tests_resolver import resolve_tests_query


def test_general_test_inquiry_uses_friendly_saudi_message():
    result = resolve_tests_query("ابغى اسئل عن تحليل")
    assert result.get("matched") is True
    assert result.get("route") == "tests_general"
    assert result.get("answer") == "عطيني اسم التحليل اللي حابب تستفسر عنه وبفيدك إن شاء الله."

