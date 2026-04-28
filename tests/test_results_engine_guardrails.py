from app.services.runtime.results_engine import interpret_result_query
from app.services.runtime import results_engine


def test_results_query_without_value_requests_test_and_value(monkeypatch):
    monkeypatch.setattr(results_engine, "load_results_records", lambda: [])
    reply = interpret_result_query("عندي نتيجة وابغى تفسير")
    assert "عطيني اسم التحليل مع النتيجة وبعطيك تفسير عام لها" in reply
    assert "مجرد إرشاد عام" in reply


def test_vitamin_d_numeric_result_is_safe_and_non_diagnostic(monkeypatch):
    def _mock_records():
        return [
            {
                "test_name": "Vitamin D",
                "terms_norm": ["vitamin d", "فيتامين د"],
                "safe_interpretation": True,
                "interpretation_mode": "numeric_range",
                "min_value": 30,
                "max_value": 100,
                "structured_rules": [],
                "rules": [],
            }
        ]

    monkeypatch.setattr(results_engine, "load_results_records", _mock_records)
    reply = interpret_result_query("Vitamin D 10")
    assert reply.startswith("منخفض")
    assert "هذا تفسير عام فقط، ويفضل مراجعة الطبيب للتقييم الدقيق." in reply
