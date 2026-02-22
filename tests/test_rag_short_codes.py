from app.data.rag_pipeline import retrieve


def _assert_top_match(query: str, expected_code: str) -> None:
    results, has_sufficient = retrieve(query, max_results=3)
    assert has_sufficient is True
    assert results, "Expected retrieval results"
    top_name = (results[0]["test"].get("analysis_name_en") or "").upper()
    assert expected_code in top_name


def test_retrieve_short_code_hba1c():
    _assert_top_match("عندكم HbA1c؟", "HBA1C")


def test_retrieve_short_code_cea_definition():
    _assert_top_match("وش معنى تحليل CEA؟", "CEA")


def test_retrieve_short_code_tsh_definition():
    _assert_top_match("شرح تحليل TSH", "TSH")


def test_retrieve_short_code_cbc_availability():
    _assert_top_match("هل CBC متوفر؟", "CBC")
