import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.packages_service import (
    load_packages_index,
    match_single_package,
    normalize_query,
    search_packages,
)


def test_load_packages_index_has_records():
    records = load_packages_index()
    assert isinstance(records, list)
    assert len(records) > 0


def test_search_packages_finds_well_dna_silver():
    results = search_packages("Well DNA Silver", top_k=5)
    assert results
    assert any("Well DNA Silver" in (r.get("name_raw") or "") for r in results)

    top = results[0]
    assert "Well DNA Silver" in (top.get("name_raw") or "")


def test_search_packages_finds_marriage_non_saudi():
    result = match_single_package("الزواج للغير السعوديين")
    assert result is not None
    assert "فحص الزواج للغير السعوديين" in (result.get("name_raw") or "")


def test_search_packages_finds_liver_kidney():
    result = match_single_package("وظائف الكبد والكلى")
    assert result is not None
    assert "وظائف الكبد والكلى" in (result.get("name_raw") or "")


def test_normalization_handles_jeddah_variant():
    assert normalize_query("جدة") == normalize_query("جده")
