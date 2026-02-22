from app.services.response_fallback_service import compose_context_fallback, sanitize_for_ui


def test_sanitize_removes_markdown_stars():
    raw = "**CBC**\n\n**TSH**"
    out = sanitize_for_ui(raw)
    assert "**" not in out
    assert "CBC" in out


def test_context_fallback_uses_context_and_not_generic_error():
    question = "هل تحليل HbA1c متوفر؟"
    context = "معلومات التحاليل ذات الصلة:\nHbA1c تحليل السكر التراكمي."
    out = compose_context_fallback(question, "test_availability", {}, context)
    assert "HbA1c" in out
    assert "خطأ في الاتصال" not in out


def test_context_fallback_contact_when_no_context():
    out = compose_context_fallback("كم سعر تحليل فيتامين د", "pricing_inquiry", {}, "")
    assert "800-122-1220" in out
