from app.services.dialogue_manager import DialogueManager


def _u(s: str) -> str:
    return s.encode("utf-8").decode("unicode_escape")


def test_new_test_with_conversational_prefix_replaces_old_active_test():
    dm = DialogueManager()
    cid = "dialogue-prefix-replace-vitd"

    dm.update_after_response(
        cid,
        {"matched": True, "source": "tests", "meta": {"matched_test_name": _u("\\u0641\\u064a\\u062a\\u0627\\u0645\\u064a\\u0646 \\u062812")}},
        user_text=_u("\\u0641\\u064a\\u062a\\u0627\\u0645\\u064a\\u0646 \\u062812"),
    )
    # Simulate runtime matched test answer where matched_test_name is absent.
    dm.update_after_response(
        cid,
        {"matched": True, "source": "tests", "meta": {}},
        user_text=_u("\\u0637\\u064a\\u0628 \\u0648 \\u0641\\u064a\\u062a\\u0627\\u0645\\u064a\\u0646 \\u062f"),
    )

    state = dm.load_state(cid)
    assert state.get("active_domain") == "test"
    assert state.get("active_entity_name") == _u("\\u0641\\u064a\\u062a\\u0627\\u0645\\u064a\\u0646 \\u062f")

    rewritten = dm.resolve_followup(_u("\\u0647\\u0644 \\u064a\\u062d\\u062a\\u0627\\u062c \\u0635\\u064a\\u0627\\u0645\\u061f"), state)
    assert _u("\\u0641\\u064a\\u062a\\u0627\\u0645\\u064a\\u0646 \\u062f") in rewritten


def test_new_test_with_wa_prefix_replaces_old_active_test():
    dm = DialogueManager()
    cid = "dialogue-prefix-replace-tsh"

    dm.update_after_response(
        cid,
        {"matched": True, "source": "tests", "meta": {"matched_test_name": "cbc"}},
        user_text="cbc",
    )
    # Simulate runtime matched test answer where matched_test_name is absent.
    dm.update_after_response(
        cid,
        {"matched": True, "source": "tests_business", "meta": {}},
        user_text="و TSH",
    )

    state = dm.load_state(cid)
    assert state.get("active_domain") == "test"
    assert state.get("active_entity_name") == "TSH"

    rewritten = dm.resolve_followup(_u("\\u0627\\u0644\\u0639\\u064a\\u0646\\u0629"), state)
    assert "TSH" in rewritten
