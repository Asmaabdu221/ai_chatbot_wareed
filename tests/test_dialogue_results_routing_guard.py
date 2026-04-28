from app.services.dialogue_manager import DialogueManager
from app.services.runtime.results_query_detector import analyze_result_query


def _u(s: str) -> str:
    return s.encode("utf-8").decode("unicode_escape")


def test_standalone_test_names_are_not_results_query():
    for q in (
        _u("\\u0641\\u064a\\u062a\\u0627\\u0645\\u064a\\u0646 \\u062f"),      # فيتامين د
        _u("\\u0641\\u064a\\u062a\\u0627\\u0645\\u064a\\u0646 \\u062812"),     # فيتامين ب12
        "Vitamin D",
        "Vitamin B12",
        "CBC",
        "TSH",
    ):
        result = analyze_result_query(q)
        assert bool(result.get("decision")) is False


def test_explicit_result_query_still_detected():
    q = "Vitamin D " + _u("\\u0646\\u062a\\u064a\\u062c\\u062a\\u064a") + " 10"
    result = analyze_result_query(q)
    assert bool(result.get("decision")) is True


def test_dialogue_state_replaces_active_test_with_new_standalone_test():
    dm = DialogueManager()
    conversation_id = "dialogue-test-replace-active-test"

    # First test query
    dm.update_after_response(
        conversation_id,
        {"matched": True, "source": "tests", "meta": {"matched_test_name": _u("\\u0641\\u064a\\u062a\\u0627\\u0645\\u064a\\u0646 \\u062812")}},
        user_text=_u("\\u0641\\u064a\\u062a\\u0627\\u0645\\u064a\\u0646 \\u062812"),
    )

    # New standalone test query should replace old active test
    dm.update_after_response(
        conversation_id,
        {"matched": True, "source": "tests", "meta": {"matched_test_name": _u("\\u0641\\u064a\\u062a\\u0627\\u0645\\u064a\\u0646 \\u062f")}},
        user_text=_u("\\u0641\\u064a\\u062a\\u0627\\u0645\\u064a\\u0646 \\u062f"),
    )

    state = dm.load_state(conversation_id)
    assert state.get("active_domain") == "test"
    assert state.get("active_entity_name") == _u("\\u0641\\u064a\\u062a\\u0627\\u0645\\u064a\\u0646 \\u062f")

    rewritten = dm.resolve_followup(_u("\\u0647\\u0644 \\u064a\\u062d\\u062a\\u0627\\u062c \\u0635\\u064a\\u0627\\u0645\\u061f"), state)
    assert _u("\\u0641\\u064a\\u062a\\u0627\\u0645\\u064a\\u0646 \\u062f") in rewritten
