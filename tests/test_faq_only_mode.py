import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import message_service


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


@pytest.fixture()
def faq_runtime_only(tmp_path, monkeypatch):
    faq_path = tmp_path / "faq_clean.jsonl"
    rows = [
        {
            "id": "faq::6",
            "question": "\u0647\u0644 \u064a\u062a\u0645 \u0625\u0631\u0633\u0627\u0644 \u0627\u0644\u0646\u062a\u0627\u0626\u062c \u0625\u0644\u0643\u062a\u0631\u0648\u0646\u064a\u0627\u061f",
            "answer": "\u0646\u0639\u0645\u060c \u064a\u0645\u0643\u0646 \u0625\u0631\u0633\u0627\u0644 \u0627\u0644\u0646\u062a\u0627\u0626\u062c \u0639\u0628\u0631 \u0627\u0644\u0648\u0627\u062a\u0633\u0627\u0628 \u0648\u0627\u0644\u062a\u0637\u0628\u064a\u0642 \u0648\u0627\u0644\u0628\u0631\u064a\u062f \u0627\u0644\u0625\u0644\u0643\u062a\u0631\u0648\u0646\u064a.",
            "q_norm": "\u0647\u0644 \u064a\u062a\u0645 \u0627\u0631\u0633\u0627\u0644 \u0627\u0644\u0646\u062a\u0627\u0626\u062c \u0627\u0644\u0643\u062a\u0631\u0648\u0646\u064a\u0627",
        },
        {
            "id": "faq::13",
            "question": "\u0647\u0644 \u0646\u062a\u0627\u0626\u062c \u0627\u0644\u062a\u062d\u0627\u0644\u064a\u0644 \u0633\u0631\u064a\u0629\u061f",
            "answer": "\u0646\u0639\u0645\u060c \u0646\u062a\u0627\u0626\u062c \u0627\u0644\u062a\u062d\u0627\u0644\u064a\u0644 \u0633\u0631\u064a\u0629 \u0648\u064a\u062a\u0645 \u062d\u0641\u0638\u0647\u0627 \u0636\u0645\u0646 \u0646\u0638\u0627\u0645 \u0622\u0645\u0646.",
            "q_norm": "\u0647\u0644 \u0646\u062a\u0627\u0626\u062c \u0627\u0644\u062a\u062d\u0627\u0644\u064a\u0644 \u0633\u0631\u064a\u0647",
        },
    ]
    _write_jsonl(faq_path, rows)
    monkeypatch.setattr(message_service, "FAQ_CLEAN_PATH", faq_path)
    message_service._FAQ_CACHE = None
    message_service._FAQ_INTENT_CANONICAL_CACHE = None
    message_service._FAQ_INTENT_CANONICAL_CACHE_KEY = None
    message_service._FAQ_SEMANTIC_ROUTER_CACHE = None
    message_service._FAQ_SEMANTIC_ROUTER_CACHE_KEY = None
    yield faq_path


def test_faq_only_mode_enabled():
    assert message_service.FAQ_ONLY_RUNTIME_MODE is True


def test_faq_only_mode_returns_faq_answer_for_faq_query(faq_runtime_only):
    reply, meta = message_service._route_faq_only_response(
        "\u0647\u0644 \u064a\u062a\u0645 \u0625\u0631\u0633\u0627\u0644 \u0627\u0644\u0646\u062a\u0627\u0626\u062c \u0625\u0644\u0643\u062a\u0631\u0648\u0646\u064a\u0627\u061f"
    )
    assert isinstance(reply, str) and reply.strip()
    assert "\u0627\u0644\u0648\u0627\u062a\u0633\u0627\u0628" in reply
    assert meta.get("id") == "faq::6"


def test_faq_only_mode_non_faq_returns_safe_fallback_and_no_other_sources_used(faq_runtime_only, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("non-FAQ source should not be called in FAQ-only mode")

    for name in (
        "_branch_lookup_bypass_reply",
        "_package_lookup_bypass_reply",
        "_runtime_tests_rag_reply",
        "_symptoms_rag_bypass_reply",
        "get_site_fallback_context",
        "expand_query_with_synonyms",
    ):
        monkeypatch.setattr(message_service, name, _boom)

    class _Result:
        def scalar(self):
            return 0

    class _FakeDB:
        def execute(self, *args, **kwargs):
            return _Result()

        def commit(self):
            return None

        def refresh(self, _obj):
            return None

    fake_conv = SimpleNamespace(user=None)

    monkeypatch.setattr(message_service, "get_conversation_for_user", lambda *args, **kwargs: fake_conv)
    monkeypatch.setattr(message_service, "set_conversation_title_from_first_message", lambda *args, **kwargs: None)

    _messages = []

    def _fake_add_message(db, conversation_id, role, content, token_count=0):
        msg = SimpleNamespace(id=uuid4(), role=role, content=content)
        _messages.append(msg)
        return msg

    monkeypatch.setattr(message_service, "add_message", _fake_add_message)

    out = message_service.send_message_with_attachment(
        db=_FakeDB(),
        conversation_id=uuid4(),
        user_id=uuid4(),
        content="\u0643\u0645 \u0633\u0639\u0631 \u062a\u062d\u0644\u064a\u0644 \u0641\u064a\u062a\u0627\u0645\u064a\u0646 \u062f\u061f",
    )

    assert out is not None
    _user_msg, assistant_msg = out
    assert assistant_msg.content == message_service.FAQ_ONLY_FALLBACK_REPLY
