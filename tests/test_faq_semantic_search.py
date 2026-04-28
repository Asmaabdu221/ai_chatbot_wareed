from app.services.runtime import faq_semantic_search as semantic


def test_build_faq_document_contains_core_fields():
    record = {
        "id": "faq::2",
        "question": "هل عندكم زيارة منزلية",
        "q_norm": "هل عندكم زيارة منزلية",
        "answer": "نعم نوفر خدمة الزيارة المنزلية.",
        "aliases": ["هل في سحب عينات من البيت"],
    }
    doc = semantic._build_faq_document(record)
    assert "question:" in doc
    assert "normalized_question:" in doc
    assert "aliases:" in doc
    assert "answer_summary:" in doc


def test_find_best_semantic_match_graceful_fallback_when_unavailable(monkeypatch):
    class _StubService:
        available = False

        def build_or_refresh(self, faq_records):
            return None

        def query(self, text, faq_records_by_id, top_k=5):
            return []

    monkeypatch.setattr(semantic, "get_faq_semantic_search", lambda: _StubService())
    out = semantic.find_best_faq_semantic_match(
        "تجون للبيت؟",
        [{"id": "faq::2", "question": "هل عندكم زيارة منزلية", "q_norm": "هل عندكم زيارة منزلية", "answer": "x"}],
    )
    assert out is None

