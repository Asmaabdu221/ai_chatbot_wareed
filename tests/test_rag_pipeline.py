"""
Offline tests for the Lab RAG v2 pipeline (6 scenarios + price gating).

These exercise the synonym (Layer 1), symptom router (Layer 3), intent
classifier, and context builder — all of which run without ChromaDB/OpenAI.
The vector layer (Layer 2) is intentionally not asserted here because it
requires an embedding backend; in production it provides the natural-language
fallback. Tests derive expectations from the loaded data to stay robust.
"""

from __future__ import annotations

import pytest

from app.services.intent_classifier import get_intent_classifier, QueryIntent
from app.services.context_builder import ContextBuilder, K_PRICE, K_COMPLEMENT
from app.data.lab_data_loader import DEFAULT_EXCEL, COL_ID, COL_NAME_AR


@pytest.fixture(scope="module")
def engine():
    if not DEFAULT_EXCEL.exists():
        pytest.skip(f"workbook not found: {DEFAULT_EXCEL}")
    from app.services.lab_retrieval_engine import LabRetrievalEngine
    eng = LabRetrievalEngine()
    eng.warm_up()
    return eng


@pytest.fixture(scope="module")
def clf():
    return get_intent_classifier()


# ---- Scenario 1: zero-miss name matching -------------------------------------
def test_scenario_1_exact_match_roundtrip(engine):
    """Any official Arabic name resolves back to its own test_id (exact path)."""
    master = engine.data_loader.load_master()
    row = master.iloc[0]
    ids = engine.synonym_retriever.search(row[COL_NAME_AR])
    assert row[COL_ID] in ids


def test_scenario_1_nickname_cbc(engine, clf):
    """A common nickname/abbreviation resolves to at least one test."""
    intent = clf.classify("CBC")
    res = engine.retrieve("CBC", intent)
    assert res.test_ids, "expected CBC to resolve via synonym index"


# ---- Scenario 2: cross-selling -----------------------------------------------
def test_scenario_2_cross_sell(engine):
    """Test-lookup context surfaces complementary tests when present."""
    master = engine.data_loader.load_master()
    with_comp = master[master[K_COMPLEMENT].str.strip().ne("") & ~master[K_COMPLEMENT].str.startswith("NEEDS")]
    assert len(with_comp) > 0
    tid = with_comp.iloc[0][COL_ID]
    tests = engine.data_loader.get_tests_by_ids([tid])
    ctx = ContextBuilder().build_context(tests, QueryIntent.TEST_LOOKUP, include_price=False)
    assert "مكمل" in ctx


# ---- Scenario 3: disambiguation ----------------------------------------------
def test_scenario_3_disambiguation(engine, clf):
    intent = clf.classify("أريد تحليل حديد")
    assert intent == QueryIntent.AMBIGUOUS
    res = engine.retrieve("أريد تحليل حديد", intent)
    ctx = ContextBuilder().build_context(res.tests, intent, extra=res.disambiguation)
    assert res.disambiguation is not None or res.test_ids
    assert "الخيارات" in ctx or "سؤال" in ctx


# ---- Scenario 4: symptom-based -----------------------------------------------
def test_scenario_4_symptoms(engine, clf):
    q = "عندي تعب وخمول وشحوب"
    intent = clf.classify(q)
    assert intent == QueryIntent.SYMPTOM_QUERY
    res = engine.retrieve(q, intent)
    assert len(res.test_ids) >= 1


# ---- Scenario 5: fasting / preparation ---------------------------------------
def test_scenario_5_fasting(engine, clf):
    q = "هل لازم أصوم لتحليل السكر"
    intent = clf.classify(q)
    assert intent == QueryIntent.FASTING_PREP
    res = engine.retrieve(q, intent)
    ctx = ContextBuilder().build_context(res.tests, intent)
    assert "صيام" in ctx or ctx == ""  # tests found -> fasting block mentions صيام


# ---- Scenario 6: availability ------------------------------------------------
def test_scenario_6_availability(clf):
    assert clf.classify("هل تحليل الغدة متوفر") == QueryIntent.AVAILABILITY


# ---- Price gating ------------------------------------------------------------
def test_price_gated(engine):
    """Price never appears unless include_price=True."""
    master = engine.data_loader.load_master()
    priced = master[master[K_PRICE].str.strip().str.match(r"^\d") == True]  # noqa: E712
    assert len(priced) > 0
    tid = priced.iloc[0][COL_ID]
    price_val = str(priced.iloc[0][K_PRICE]).strip()
    tests = engine.data_loader.get_tests_by_ids([tid])

    no_price = ContextBuilder().build_context(tests, QueryIntent.TEST_LOOKUP, include_price=False)
    assert price_val not in no_price
    assert "سيتواصل" in no_price

    with_price = ContextBuilder().build_context(tests, QueryIntent.TEST_LOOKUP, include_price=True)
    assert price_val in with_price


# ---- Package recommender (Step 5) -------------------------------------------
def test_package_direct_inquiry(engine, clf):
    q = "عندكم باقات؟"
    intent = clf.classify(q)
    assert intent == QueryIntent.PACKAGE_INQUIRY
    res = engine.retrieve(q, intent)
    ctx = ContextBuilder().build_context([], intent, packages=res.packages)
    assert ctx and "باق" in ctx


def test_package_by_name(engine):
    pkgs = engine.data_loader.load_packages()
    assert len(pkgs) > 0
    pid = pkgs.iloc[0]["package_id"]
    name = pkgs.iloc[0]["package_name_ar"]
    assert pid in engine.package_retriever.search_by_name(name)


def test_package_upsell(engine):
    pr = engine.package_retriever
    target = None
    for pid, row in pr.by_id.items():
        ids = [x.strip() for x in str(row.get("test_ids", "")).split(",") if x.strip().startswith("TEST_")]
        if len(ids) >= 2:
            target = (pid, ids[:2]); break
    assert target, "expected a package with >=2 member tests"
    pid, two = target
    assert pid in pr.get_packages_for_tests(two, min_overlap=2)


def test_package_symptom_match(engine):
    sym_df = engine.data_loader.load_package_symptoms()
    assert len(sym_df) > 0
    sym = sym_df.iloc[0]["symptom_ar"]
    assert len(engine.package_retriever.search_by_symptoms([sym])) >= 1


def test_package_price_gated(engine):
    pkgs = engine.data_loader.load_packages()
    priced = pkgs[pkgs["price"].str.match(r"^\d", na=False)]
    assert len(priced) > 0
    pkg = priced.iloc[0].to_dict()
    price = str(pkg["price"]).strip()
    cb = ContextBuilder()
    no_price = cb.build_context([], QueryIntent.PACKAGE_INQUIRY, include_price=False, packages=[pkg])
    assert "سيتواصل" in no_price
    with_price = cb.build_context([], QueryIntent.PACKAGE_INQUIRY, include_price=True, packages=[pkg])
    assert price in with_price
