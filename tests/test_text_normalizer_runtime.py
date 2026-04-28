from app.services.runtime.results_query_detector import analyze_result_query
from app.services.runtime.runtime_router import _looks_like_branch_query
from app.services.runtime.text_normalizer import normalize_for_match


def test_normalize_ar_letter_number_joining():
    assert normalize_for_match("فيتامين ب 12") == normalize_for_match("فيتامين ب12")


def test_normalize_en_letter_number_joining():
    assert normalize_for_match("Vitamin B 12") == normalize_for_match("Vitamin B12")


def test_normalize_punctuation():
    assert normalize_for_match("فيتامين د؟") == normalize_for_match("فيتامين د")


def test_normalize_arabic_variant():
    assert normalize_for_match("إسهال") == normalize_for_match("اسهال")


def test_normalize_hba1c_alias_shape():
    assert normalize_for_match("Hb A1c") == normalize_for_match("HbA1c")


def test_branch_query_still_detectable():
    assert _looks_like_branch_query("فروع جدة") is True


def test_result_query_still_detectable():
    result = analyze_result_query("Vitamin D نتيجتي 10")
    assert bool(result.get("decision")) is True


def test_b12_name_not_result_query():
    for q in ("فيتامين ب 12", "فيتامين ب12", "Vitamin B12", "B12"):
        result = analyze_result_query(q)
        assert bool(result.get("decision")) is False

