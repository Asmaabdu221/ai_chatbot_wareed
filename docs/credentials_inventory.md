# Credentials Inventory (Safe, Internal)

## Overview
This inventory lists environment variable names and configuration requirements discovered in this repository, with references.
No secret values are shown. Any detected value is treated as `[REDACTED]`.

## Section A: AI Providers
| Name | Purpose | Files (line) | Required | Default |
|---|---|---|---|---|
| `OPENAI_API_KEY` | OpenAI authentication for chat/embeddings/vision flows | `app/core/config.py:39`, `app/services/openai_service.py:33`, `app/services/embeddings_service.py:25`, `app/services/prescription_vision_service.py:142`, `app/services/question_router.py:362`, `app/main.py:147` | Yes for AI calls | `""` |
| `OPENAI_MODEL` | Chat/completions model | `app/core/config.py:42`, `app/services/openai_service.py:34`, `app/services/question_router.py:369` | Optional | `gpt-4o-mini` |
| `OPENAI_MAX_TOKENS` | Max completion tokens | `app/core/config.py:43`, `app/services/openai_service.py:35` | Optional | `1000` |
| `OPENAI_TEMPERATURE` | Generation temperature | `app/core/config.py:44`, `app/services/openai_service.py:36` | Optional | `0.3` |
| `OPENAI_EMBEDDING_MODEL` | Embedding model for retrieval/style vectors | `app/core/config.py:45`, `app/services/embeddings_service.py:52`, `app/data/build_style_system.py:230` | Optional | `text-embedding-3-small` |
| `OPENAI_VISION_MODEL` | Vision model for prescription analysis | `app/core/config.py:55`, `app/services/prescription_vision_service.py:39` | Optional | `gpt-4o-mini` |
| `RAG_SIMILARITY_THRESHOLD` | Retrieval grounding threshold | `app/core/config.py:51`, `app/api/chat.py:311`, `app/services/message_service.py:273` | Optional | `0.3` |
| `ENABLE_STYLE_RAG` | Enable style retrieval path | `app/core/config.py:129`, `app/services/message_service.py:298` | Optional | `true` |
| `STYLE_TOP_K` | Style examples candidate count | `app/core/config.py:130`, `app/services/message_service.py:303` | Optional | `3` |
| `STYLE_MIN_SCORE` | Style retrieval minimum score | `app/core/config.py:131`, `app/data/style_pipeline.py:178` | Optional | `0.35` |
| `STYLE_MAX_CHARS_PER_EXAMPLE` | Style sample truncation | `app/core/config.py:132`, `app/data/style_pipeline.py:99` | Optional | `320` |
| `STYLE_FALLBACK_LEXICAL` | Enable lexical fallback for style retrieval | `app/core/config.py:133`, `app/data/style_pipeline.py:110` | Optional | `true` |
| `STYLE_FALLBACK_MIN_SCORE` | Min score for style lexical fallback | `app/core/config.py:134`, `app/data/style_pipeline.py:112` | Optional | `0.25` |

Notes:
- No active Ollama, OCR vendor key, STT key, or TTS key env vars were found in backend runtime code.

## Section B: Database / Storage
| Name | Purpose | Files (line) | Required | Default |
|---|---|---|---|---|
| `DATABASE_URL` | Primary SQLAlchemy/PostgreSQL DSN | `app/core/config.py:62`, `app/db/session.py:27`, `alembic/env.py:31` | Required for DB-backed features | `""` |
| `DB_POOL_SIZE` | DB pool size | `app/core/config.py:68`, `app/db/session.py:42` | Optional | `5` |
| `DB_MAX_OVERFLOW` | DB pool overflow | `app/core/config.py:69`, `app/db/session.py:43` | Optional | `10` |
| `DB_POOL_TIMEOUT` | DB checkout timeout (sec) | `app/core/config.py:70`, `app/db/session.py:44` | Optional | `30` |
| `DB_POOL_RECYCLE` | DB connection recycle (sec) | `app/core/config.py:71`, `app/db/session.py:45` | Optional | `3600` |

Observed in local `.env` but not consumed by current backend settings:
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`

## Section C: Security/Auth/Admin
| Name | Purpose | Files (line) | Required | Default |
|---|---|---|---|---|
| `SECRET_KEY` | JWT signing key | `app/core/config.py:113`, `app/core/security.py:99` | Yes for auth safety | `change-this-in-production` |
| `JWT_ALGORITHM` | JWT algorithm | `app/core/config.py:117`, `app/core/security.py:100` | Optional | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime | `app/core/config.py:118`, `app/core/security.py:95`, `app/api/auth.py:99` | Optional | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime | `app/core/config.py:119`, `app/core/security.py:109` | Optional | `7` |
| `ADMIN_API_KEY` | Header-based protection for admin APIs | `app/api/admin.py:30`, `app/api/admin.py:34` | Optional but strongly recommended in prod | none |
| `RATE_LIMIT_PER_MINUTE` | API rate-limit config | `app/core/config.py:122` | Optional | `60` |

## Section D: Infra / Deploy / URLs
| Name | Purpose | Files (line) | Required | Default |
|---|---|---|---|---|
| `APP_NAME` | Service name in metadata/logging | `app/core/config.py:33`, `app/main.py:82` | Optional | `Wareed Medical Assistant` |
| `APP_VERSION` | Service version | `app/core/config.py:34`, `app/main.py:84` | Optional | `1.0.0` |
| `DEBUG` | Debug mode toggle | `app/core/config.py:36`, `app/main.py:94`, `app/db/session.py:34` | Optional | `false` |
| `CORS_ORIGINS` | Allowed frontend origins | `app/core/config.py:80` | Optional | localhost defaults |
| `LOG_LEVEL` | Logging level | `app/core/config.py:74`, `app/core/logging_config.py:23` | Optional | `INFO` |
| `LOG_FILE` | Log file path | `app/core/config.py:75`, `app/core/config.py:171` | Optional | `logs/wareed_api.log` |
| `LOG_MAX_BYTES` | Log rotation size | `app/core/config.py:76`, `app/core/config.py:172` | Optional | `10485760` |
| `LOG_BACKUP_COUNT` | Rotated log file count | `app/core/config.py:77`, `app/core/config.py:173` | Optional | `5` |
| `KB_AUTO_RELOAD_ENABLED` | Runtime KB reload switch | `app/core/config.py:125`, `app/services/kb_auto_reload.py:50` | Optional | `true` |
| `KB_AUTO_RELOAD_INTERVAL_SECONDS` | KB reload interval | `app/core/config.py:126`, `app/services/kb_auto_reload.py:63` | Optional | `30` |
| `CUSTOMER_SERVICE_PHONE` | Configurable customer-service contact | `app/core/config.py:135` | Optional | `+966920033402` |

Frontend/mobile env names also present in repo config files:
- React: `REACT_APP_API_BASE_URL`, `REACT_APP_API_URL`, `VITE_API_URL`, `HTTPS`, `CHOKIDAR_USEPOLLING`
- Expo/mobile: `EXPO_PUBLIC_API_URL`

## Webhooks & Third-Party Integrations
- No active backend env vars for WhatsApp Cloud API (`WHATSAPP_TOKEN`, `PHONE_NUMBER_ID`, etc.) were detected.
- No active backend env vars for WATI / EngageBay / SMTP were detected.
- No GitHub Actions workflow secrets references were found (`.github/workflows` not present).
- No `render.yaml` was found in this repository snapshot.

## How To Set Safely
1. Local development:
- Put local values in repo root `.env` (and `.env.local` if used by your workflow).
- Keep only placeholders in `.env.example`.

2. Server/production:
- Set env vars in your hosting platform secret manager (for example Render service environment settings).
- Do not commit production values to git.

3. Secure sharing:
- Share secrets only through an approved secret manager or one-time secure channel.
- Never share raw secrets in chat/email/docs; share variable names only.

4. Rotation basics:
- Generate a new secret/API key in provider console.
- Update secret manager value.
- Restart/redeploy service.
- Revoke old secret after verification.

## Reproducible Audit Command
Run from repo root:

```powershell
set PYTHONPATH=.
python scripts/audit_env_usage.py
```

Script output includes only variable names and file:line references, with any detected assignment values redacted as `[REDACTED]`.
