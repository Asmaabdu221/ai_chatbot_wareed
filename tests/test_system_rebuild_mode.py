from types import SimpleNamespace
from uuid import uuid4

from app.services import message_service


def test_system_rebuild_mode_returns_fixed_reply_and_skips_all_knowledge(monkeypatch):
    monkeypatch.setattr(message_service, "SYSTEM_REBUILD_MODE", True)

    def _boom(*args, **kwargs):
        raise AssertionError("knowledge/routing function should not be called in rebuild mode")

    for name in (
        "load_runtime_faq",
        "load_runtime_prices",
        "load_runtime_synonyms",
        "expand_query_with_synonyms",
        "_route_faq_only_response",
        "_resolve_faq_response",
        "_branch_lookup_bypass_reply",
        "_package_lookup_bypass_reply",
        "_runtime_tests_rag_reply",
        "_symptoms_rag_bypass_reply",
        "get_site_fallback_context",
        "retrieve",
        "get_grounded_context",
        "classify_intent",
        "route_question",
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

    messages = []

    def _fake_add_message(db, conversation_id, role, content, token_count=0):
        msg = SimpleNamespace(id=uuid4(), role=role, content=content)
        messages.append(msg)
        return msg

    monkeypatch.setattr(message_service, "add_message", _fake_add_message)

    result = message_service.send_message_with_attachment(
        db=_FakeDB(),
        conversation_id=uuid4(),
        user_id=uuid4(),
        content="مرحبا",
    )

    assert result is not None
    _user_msg, assistant_msg = result
    assert assistant_msg.content == message_service.SYSTEM_REBUILD_REPLY
    assert len(messages) == 2
