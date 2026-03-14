import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.services import message_service


REAL_FAQ_PATH = Path("app/data/runtime/rag/faq_clean.jsonl")


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = (line or "").strip()
            if not raw:
                continue
            rows.append(json.loads(raw))
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


@pytest.fixture()
def faq_runtime_all_canonical(tmp_path, monkeypatch):
    rows = _read_jsonl(REAL_FAQ_PATH)
    faq_path = tmp_path / "faq_clean.jsonl"
    _write_jsonl(faq_path, rows)

    monkeypatch.setattr(message_service, "FAQ_CLEAN_PATH", faq_path)
    message_service._FAQ_CACHE = None
    message_service._FAQ_INTENT_CANONICAL_CACHE = None
    message_service._FAQ_INTENT_CANONICAL_CACHE_KEY = None
    message_service._FAQ_SEMANTIC_ROUTER_CACHE = None
    message_service._FAQ_SEMANTIC_ROUTER_CACHE_KEY = None

    yield faq_path

    message_service._FAQ_CACHE = None
    message_service._FAQ_INTENT_CANONICAL_CACHE = None
    message_service._FAQ_INTENT_CANONICAL_CACHE_KEY = None
    message_service._FAQ_SEMANTIC_ROUTER_CACHE = None
    message_service._FAQ_SEMANTIC_ROUTER_CACHE_KEY = None


def test_semantic_router_builds_intent_spec_per_faq(faq_runtime_all_canonical):
    faq_items = message_service.load_runtime_faq()
    router = message_service._build_faq_semantic_router()
    intents = router.get("intents") or {}

    assert len(faq_items) == 18
    assert len(intents) == len(faq_items)

    for intent_name, spec in intents.items():
        assert intent_name.startswith("faq_intent_")
        assert spec.get("intent_name") == intent_name
        assert str(spec.get("canonical_faq_id") or "").startswith("faq::")
        paraphrases = spec.get("paraphrases") or []
        assert isinstance(paraphrases, list)
        assert len(paraphrases) >= 3


def test_all_canonical_faq_records_resolve_from_question_and_qnorm(faq_runtime_all_canonical):
    faq_items = message_service.load_runtime_faq()

    for item in faq_items:
        for query in (item["question"], item["q_norm"]):
            answer, meta = message_service._resolve_faq_response(query)
            assert isinstance(answer, str) and answer.strip()
            assert meta is not None
            assert meta.get("id") == item["id"]
            assert meta.get("_match_method") in {"faq_semantic_intent", "faq_exact"}


def test_all_canonical_intents_are_lookupable_by_intent_name(faq_runtime_all_canonical):
    router = message_service._build_faq_semantic_router()
    intents = router.get("intents") or {}

    for intent_name, spec in intents.items():
        match = message_service._runtime_faq_lookup_by_intent(intent_name)
        assert match is not None
        assert match.get("id") == spec.get("canonical_faq_id")


@pytest.mark.parametrize(
    "query, expected_id",
    [
        ("كيف اضمن خصوصيه التحاليل الحساسه", "faq::14"),
        ("تحليل السكر التراكمي يحتاج صيام او لا", "faq::16"),
        ("هل السكر التراكمي يحتاج صيام", "faq::16"),
        ("تحليل الغدة الدرقية يحتاج صيام", "faq::18"),
        ("هل تحليل TSH يحتاج صيام", "faq::18"),
    ],
)
def test_missed_faq_phrasings_route_to_expected_canonical_ids(query, expected_id, faq_runtime_all_canonical):
    answer, meta = message_service._resolve_faq_response(query)
    assert isinstance(answer, str) and answer.strip()
    assert meta is not None
    assert meta.get("id") == expected_id
    assert meta.get("_match_method") == "faq_semantic_intent"


def test_low_confidence_query_returns_not_faq_and_continues_normal_routing(faq_runtime_all_canonical):
    query = "كم سعر تحليل فيتامين د"
    assert message_service._detect_faq_intent(query) == "not_faq"
    answer, meta = message_service._resolve_faq_response(query)
    assert answer is None
    assert meta is None


def test_high_confidence_faq_query_blocks_package_route(faq_runtime_all_canonical, monkeypatch):
    fake_record = {
        "id": "pkg::1",
        "name_raw": "باقة الغدة",
        "description_raw": "وصف",
        "price_raw": "100",
        "turnaround_text": "",
        "sample_type_text": "",
    }
    monkeypatch.setattr(message_service, "match_single_package", lambda _q: fake_record)
    monkeypatch.setattr(message_service, "search_packages", lambda _q, top_k=6: [fake_record])
    monkeypatch.setattr(message_service, "semantic_search_packages", lambda _q, top_k=3: [{"id": "pkg::1", "score": 0.99}])

    reply = message_service._package_lookup_bypass_reply("هل تحليل TSH يحتاج صيام", uuid4())
    assert reply is None


def test_optional_rephrase_keeps_answer_grounded_to_same_faq(monkeypatch, faq_runtime_all_canonical):
    monkeypatch.setattr(message_service, "_is_faq_rephrase_enabled", lambda: True)
    monkeypatch.setattr(
        message_service.openai_service,
        "generate_response",
        lambda **kwargs: {
            "success": True,
            "response": "لا، تحليل السكر التراكمي HbA1c لا يحتاج صيام.",
            "model": "mock",
            "tokens_used": 0,
            "error": None,
        },
    )

    answer, meta = message_service._resolve_faq_response("هل السكر التراكمي يحتاج صيام")
    assert meta is not None
    assert meta.get("id") == "faq::16"
    assert isinstance(answer, str) and answer.strip()
