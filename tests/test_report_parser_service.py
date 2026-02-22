from app.services.report_parser_service import parse_lab_report_text, compose_report_summary, is_report_explanation_request


def test_parse_lab_report_text_pipe_rows():
    text = """
    Test | Result | Unit | Reference Range | Flag
    HbA1c | 6.1 | % | 4.0-5.6 | H
    Vitamin D | 18.2 | ng/mL | 30-100 | L
    TSH | 2.3 | uIU/mL | 0.4-4.0 |
    """
    rows = parse_lab_report_text(text)
    assert len(rows) >= 3
    assert rows[0]["test_name"]
    assert rows[0]["result_value"]


def test_parse_lab_report_text_spaced_rows():
    text = """
    HbA1c      6.1    %      4.0-5.6 H
    Vitamin D  18.2   ng/mL  30-100 L
    TSH        2.3    uIU/mL 0.4-4.0
    """
    rows = parse_lab_report_text(text)
    assert len(rows) >= 2
    assert any("TSH" in r["test_name"] for r in rows)


def test_compose_summary_has_required_sections():
    rows = [
        {
            "test_name": "HbA1c",
            "result_value": "6.1",
            "unit": "%",
            "reference_range": "4.0-5.6",
            "flags_if_present": "H",
        }
    ]
    out = compose_report_summary(rows)
    assert "اسم الفحص" in out
    assert "النتيجة" in out
    assert "المدى المرجعي" in out
    assert "**" not in out


def test_is_report_explanation_request():
    assert is_report_explanation_request("اشرح التحاليل")
    assert is_report_explanation_request("وش معنى النتيجة؟")
    assert not is_report_explanation_request("ابي رقم خدمة العملاء")
