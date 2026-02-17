# WAREED V1 - Database Schema Documentation

## Overview

The WAREED Medical AI Chatbot uses PostgreSQL as the production database with a clean, normalized schema designed for scalability and data integrity.

## Database Architecture

```
┌─────────────┐
│    users    │
└──────┬──────┘
       │ 1
       │
       │ N
┌──────┴──────────────┐
│   conversations     │
└──────┬──────────────┘
       │ 1
       │
       │ N
┌──────┴──────────────┐
│     messages        │
└─────────────────────┘
```

---

## Tables

### 1. users

Represents a user of the chatbot system.

| Column          | Type                     | Constraints           | Description                          |
|-----------------|--------------------------|-----------------------|--------------------------------------|
| id              | UUID                     | PK                    | Unique user identifier               |
| created_at      | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now()| User creation timestamp (UTC)        |
| last_active_at  | TIMESTAMP WITH TIME ZONE | NOT NULL              | Last interaction timestamp           |
| is_active       | BOOLEAN                  | NOT NULL, DEFAULT true| Account active status                |

**Indexes:**
- `PRIMARY KEY (id)`
- `INDEX idx_users_created_at ON created_at`

**Relationships:**
- One user → Many conversations (CASCADE DELETE)

**Notes:**
- Uses UUIDv4 for security (prevents user enumeration)
- `last_active_at` updated on each interaction
- Soft delete via `is_active` flag for user retention

---

### 2. conversations

Represents a chat conversation between a user and the AI assistant.

| Column          | Type                     | Constraints                    | Description                          |
|-----------------|--------------------------|--------------------------------|--------------------------------------|
| id              | UUID                     | PK                             | Unique conversation identifier       |
| user_id         | UUID                     | FK → users.id, NOT NULL        | Owner user ID                        |
| title           | VARCHAR(255)             | NULL                           | Conversation title (auto-generated)  |
| created_at      | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now()        | Conversation creation timestamp (UTC)|
| updated_at      | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now()        | Last message timestamp (UTC)         |
| is_archived     | BOOLEAN                  | NOT NULL, DEFAULT false        | Soft delete flag                     |

**Indexes:**
- `PRIMARY KEY (id)`
- `INDEX idx_conversations_user_id ON user_id`
- `INDEX idx_conversations_is_archived ON is_archived`
- `INDEX idx_conversations_created_at ON created_at`
- `COMPOSITE INDEX idx_conversations_user_archived ON (user_id, is_archived)`

**Relationships:**
- Many conversations → One user
- One conversation → Many messages (CASCADE DELETE)

**Foreign Keys:**
- `user_id REFERENCES users(id) ON DELETE CASCADE`

**Notes:**
- `title` auto-generated from first message (first 50 chars)
- `updated_at` updated on each new message
- `is_archived` enables soft delete (data retained for analytics)
- Archived conversations not shown in user's conversation list

---

### 3. messages

Represents individual messages within a conversation.

| Column          | Type                     | Constraints                    | Description                          |
|-----------------|--------------------------|--------------------------------|--------------------------------------|
| id              | UUID                     | PK                             | Unique message identifier            |
| conversation_id | UUID                     | FK → conversations.id, NOT NULL| Parent conversation ID               |
| role            | ENUM('user', 'assistant', 'system') | NOT NULL    | Message sender role                  |
| content         | TEXT                     | NOT NULL                       | Message content (supports long text) |
| token_count     | INTEGER                  | NULL                           | Token count (for cost tracking)      |
| created_at      | TIMESTAMP WITH TIME ZONE | NOT NULL, DEFAULT now()        | Message creation timestamp (UTC)     |

**Indexes:**
- `PRIMARY KEY (id)`
- `INDEX idx_messages_conversation_id ON conversation_id`
- `INDEX idx_messages_role ON role`
- `INDEX idx_messages_created_at ON created_at`
- `COMPOSITE INDEX idx_messages_conversation_created ON (conversation_id, created_at)`

**Relationships:**
- Many messages → One conversation

**Foreign Keys:**
- `conversation_id REFERENCES conversations(id) ON DELETE CASCADE`

**ENUM Types:**
- `message_role`: `'user'`, `'assistant'`, `'system'`

**Notes:**
- `role = 'user'`: Message from the user
- `role = 'assistant'`: AI-generated response
- `role = 'system'`: System messages (future use)
- `token_count` tracked for OpenAI cost monitoring
- `content` uses TEXT type to support long medical responses
- Messages ordered by `created_at` within conversations

---

## Data Flow

### 1. New User Chat Flow

```
1. POST /api/chat (no user_id)
   ↓
2. Backend creates new User
   → user_id generated
   ↓
3. Backend creates new Conversation
   → conversation_id generated
   → title set from first message
   ↓
4. Backend saves user Message
   → role='user'
   → content=user's message
   ↓
5. Backend calls OpenAI API
   ↓
6. Backend saves assistant Message
   → role='assistant'
   → content=AI response
   → token_count=tokens used
   ↓
7. Response includes conversation_id, message_id
```

### 2. Continuing Conversation Flow

```
1. POST /api/chat (with conversation_id)
   ↓
2. Backend loads User from database
   → updates last_active_at
   ↓
3. Backend loads Conversation
   → verifies user ownership
   → updates updated_at
   ↓
4. Backend loads all Messages for context
   → ordered by created_at ASC
   ↓
5. Backend saves new user Message
   ↓
6. Backend sends messages to OpenAI
   ↓
7. Backend saves assistant Message
   ↓
8. Frontend reloads conversation
```

### 3. Load Conversations Flow

```
1. GET /api/conversations/{user_id}
   ↓
2. Backend queries conversations
   → WHERE user_id = {user_id}
   → AND is_archived = false
   → ORDER BY updated_at DESC
   ↓
3. Backend joins messages for count
   ↓
4. Returns conversation summaries
```

---

## Query Examples

### Get Active Conversations for User

```sql
SELECT 
    c.id,
    c.title,
    c.created_at,
    c.updated_at,
    COUNT(m.id) as message_count
FROM conversations c
LEFT JOIN messages m ON m.conversation_id = c.id
WHERE c.user_id = '550e8400-e29b-41d4-a716-446655440000'
  AND c.is_archived = false
GROUP BY c.id
ORDER BY c.updated_at DESC
LIMIT 50;
```

### Get Conversation with Messages

```sql
SELECT 
    m.id,
    m.role,
    m.content,
    m.token_count,
    m.created_at
FROM messages m
WHERE m.conversation_id = '123e4567-e89b-12d3-a456-426614174000'
ORDER BY m.created_at ASC;
```

### Calculate Token Usage for User

```sql
SELECT 
    u.id,
    COUNT(DISTINCT c.id) as conversation_count,
    COUNT(m.id) as total_messages,
    SUM(CASE WHEN m.role = 'assistant' THEN m.token_count ELSE 0 END) as total_tokens
FROM users u
LEFT JOIN conversations c ON c.user_id = u.id
LEFT JOIN messages m ON m.conversation_id = c.id
WHERE u.id = '550e8400-e29b-41d4-a716-446655440000'
GROUP BY u.id;
```

### Archive Old Conversations

```sql
UPDATE conversations
SET 
    is_archived = true,
    updated_at = NOW()
WHERE user_id = '550e8400-e29b-41d4-a716-446655440000'
  AND updated_at < NOW() - INTERVAL '90 days'
  AND is_archived = false;
```

---

## Performance Considerations

### Index Strategy

1. **Foreign Keys**: All foreign keys are indexed for fast joins
2. **Timestamps**: `created_at` indexed for chronological queries
3. **Filters**: Common WHERE clauses indexed (`is_archived`, `user_id`)
4. **Composite Indexes**: Multi-column indexes for complex queries

### Connection Pooling

```python
# Configured in app/db/session.py
pool_size=5          # Persistent connections
max_overflow=10      # Additional connections when needed
pool_timeout=30      # Wait time for connection
pool_recycle=3600    # Recycle connections hourly
pool_pre_ping=True   # Test connections before use
```

### Query Optimization

- Use `selectin` loading for relationships (avoids N+1)
- Paginate long conversation lists (LIMIT/OFFSET)
- Eager load related data when needed
- Use database-level timestamps (`server_default=func.now()`)

---

## Data Integrity

### Referential Integrity

- **CASCADE DELETE**: Deleting user → deletes conversations → deletes messages
- **Foreign Key Constraints**: Enforced at database level
- **NOT NULL**: Critical fields cannot be null

### Transaction Safety

All chat operations wrapped in transactions:
```python
try:
    user = get_or_create_user(db, user_id)
    conversation = get_or_create_conversation(db, user, conv_id)
    user_msg = save_message(db, conversation, 'user', message)
    db.commit()  # Commit before OpenAI call
    
    ai_response = openai_service.generate_response(...)
    
    assistant_msg = save_message(db, conversation, 'assistant', ai_response)
    db.commit()  # Commit AI response
except Exception:
    db.rollback()  # Rollback on failure
    raise
```

---

## Backup & Recovery

### Backup Strategy

```bash
# Daily full backup
pg_dump -U wareed_user -d wareed_db -F c -f backup_$(date +%Y%m%d).dump

# Incremental WAL archiving
# Configure in postgresql.conf:
# wal_level = replica
# archive_mode = on
# archive_command = 'cp %p /backup/wal/%f'
```

### Restore

```bash
# Restore from dump
pg_restore -U wareed_user -d wareed_db -c backup_20260202.dump

# Point-in-time recovery
# Use WAL files to restore to specific timestamp
```

---

## Security

### Database Security

1. **User Privileges**: Minimal privileges for application user
2. **SSL Connections**: Required for production
3. **Password Policy**: Strong passwords enforced
4. **Network Access**: Firewall limits connections

### Application Security

1. **UUID Primary Keys**: Prevents ID enumeration
2. **Soft Delete**: Data retained for audit
3. **Input Validation**: Pydantic models validate all inputs
4. **SQL Injection**: SQLAlchemy ORM prevents SQL injection

---

## Monitoring Queries

### Active Connections

```sql
SELECT COUNT(*) FROM pg_stat_activity 
WHERE datname = 'wareed_db';
```

### Table Sizes

```sql
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### Slow Queries

```sql
SELECT 
    query,
    calls,
    total_time,
    mean_time,
    max_time
FROM pg_stat_statements
WHERE query LIKE '%conversations%'
ORDER BY mean_time DESC
LIMIT 10;
```

---

## Migration History

| Version | Date       | Description                                   |
|---------|------------|-----------------------------------------------|
| 001     | 2026-02-02 | Initial migration: users, conversations, messages |

---

**Schema Version:** 1.0.0  
**Last Updated:** 2026-02-02  
**Database:** PostgreSQL 14+
