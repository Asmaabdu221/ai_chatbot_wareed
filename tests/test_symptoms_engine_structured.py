import json

from app.services.runtime import symptoms_engine


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_symptoms_engine_ranks_by_overlap(tmp_path, monkeypatch):
    dataset = tmp_path / "tests_clean.jsonl"
    _write_jsonl(
        dataset,
        [
            {
                "canonical_name_ar": "CBC",
                "symptoms": ["حمى", "إسهال"],
            },
            {
                "canonical_name_ar": "تحليل البراز",
                "symptoms": ["إسهال"],
            },
            {
                "canonical_name_ar": "CRP",
                "symptoms": ["حمى"],
            },
            {
                "canonical_name_ar": "TSH",
                "symptoms": ["خمول"],
            },
        ],
    )

    monkeypatch.setattr(symptoms_engine, "TESTS_JSONL_PATH", dataset)
    symptoms_engine.load_symptoms_mappings.cache_clear()

    result = symptoms_engine.handle_symptoms_query("عندي حمى واسهال")
    assert result is not None
    assert result.get("type") == "symptom_match"
    tests = list(result.get("tests") or [])
    assert tests[0] == "CBC"
    assert "تحليل البراز" in tests
    assert "CRP" in tests
    assert len(tests) <= 5


def test_symptoms_engine_weak_match_returns_none(tmp_path, monkeypatch):
    dataset = tmp_path / "tests_clean.jsonl"
    _write_jsonl(
        dataset,
        [
            {"canonical_name_ar": "CBC", "symptoms": ["حمى"]},
            {"canonical_name_ar": "CRP", "symptoms": ["التهاب"]},
        ],
    )

    monkeypatch.setattr(symptoms_engine, "TESTS_JSONL_PATH", dataset)
    symptoms_engine.load_symptoms_mappings.cache_clear()

    result = symptoms_engine.handle_symptoms_query("عندي دوخة")
    assert result is None
