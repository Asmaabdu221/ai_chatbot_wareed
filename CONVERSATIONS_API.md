# Conversation & Messages API

## Security

- **Authentication:** All endpoints require `Authorization: Bearer <access_token>`. User is **never** taken from body or query; the JWT subject is the single source of truth.
- **Ownership:** A user can only access their own conversations and messages. Every operation checks `conversation.user_id == current_user.id`. Any mismatch returns **403 Forbidden** (never 404 for another user’s resource, to avoid enumeration).
- **Validation:** All inputs use Pydantic schemas (request body and query params).

## Ownership enforcement

- **Service layer:** `conversation_service.get_conversation_for_user(db, conversation_id, user_id)` returns the conversation only if it belongs to that user; otherwise `None`. All conversation/message operations use this (or the same pattern) before proceeding.
- **Router layer:** Routers call services with `current_user.id` (from JWT). If a service returns `None` (not found or not owner), the API returns **403 Forbidden** with a safe message (e.g. "لا صلاحية للوصول لهذه المحادثة").

## Endpoints (prefix `/api`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/conversations` | Create conversation (optional title) |
| GET | `/conversations` | List my conversations |
| GET | `/conversations/{conversation_id}` | Get one conversation (403 if not owner) |
| DELETE | `/conversations/{conversation_id}` | Soft-delete (archive) conversation |
| POST | `/conversations/{conversation_id}/messages` | Send message, get AI reply (user + assistant stored) |
| GET | `/conversations/{conversation_id}/messages` | List messages (403 if not owner) |

Same behaviour for Web and Mobile; JSON only, no cookies or platform-specific logic.
