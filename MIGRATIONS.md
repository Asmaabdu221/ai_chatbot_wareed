# Database Migrations Guide

## Overview

WAREED uses Alembic for database schema migrations. This ensures safe, versioned, and reversible database changes.

---

## Quick Start

### 1. First Time Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Create database in PostgreSQL
psql -U postgres -c "CREATE DATABASE wareed_db;"
psql -U postgres -c "CREATE USER wareed_user WITH PASSWORD 'your_password';"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE wareed_db TO wareed_user;"

# Set DATABASE_URL in .env
DATABASE_URL=postgresql://wareed_user:your_password@localhost:5432/wareed_db

# Create initial migration
alembic revision --autogenerate -m "Initial migration"

# Apply migration
alembic upgrade head
```

### 2. Verify Migration

```bash
# Check current version
alembic current

# Should show:
# xxxxx (head)

# Verify tables in database
psql -U wareed_user -d wareed_db -c "\dt"
```

---

## Alembic Commands

### Check Current Version

```bash
alembic current
```

Shows the current database schema version.

### View Migration History

```bash
alembic history --verbose
```

Shows all migrations with details.

### Create New Migration (Auto-generate)

```bash
alembic revision --autogenerate -m "Add new feature"
```

Compares models with database and generates migration script.

**IMPORTANT:** Always review the generated migration before applying!

### Create Empty Migration (Manual)

```bash
alembic revision -m "Custom migration"
```

Creates empty migration template for manual operations.

### Upgrade Database

```bash
# Upgrade to latest version
alembic upgrade head

# Upgrade one step
alembic upgrade +1

# Upgrade to specific version
alembic upgrade xxxxx
```

### Downgrade Database

```bash
# Downgrade one step
alembic downgrade -1

# Downgrade to specific version
alembic downgrade xxxxx

# Downgrade to base (WARNING: deletes all data)
alembic downgrade base
```

### Show SQL Without Applying

```bash
# Show SQL for upgrade
alembic upgrade head --sql

# Show SQL for downgrade
alembic downgrade -1 --sql
```

---

## Migration File Structure

### Location

```
alembic/
├── versions/
│   └── xxxxx_initial_migration.py  # Migration files
├── env.py                          # Migration environment config
└── script.py.mako                  # Migration template
```

### Migration File Format

```python
"""Initial migration

Revision ID: xxxxx
Revises: 
Create Date: 2026-02-02 10:00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'xxxxx'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Upgrade operations
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    # Downgrade operations
    op.drop_table('users')
```

---

## Common Scenarios

### Scenario 1: Initial Production Deployment

```bash
# 1. Set up database
psql -U postgres < setup_database.sql

# 2. Configure environment
export DATABASE_URL="postgresql://wareed_user:password@localhost:5432/wareed_db"

# 3. Apply migrations
alembic upgrade head

# 4. Verify
alembic current
psql -U wareed_user -d wareed_db -c "SELECT COUNT(*) FROM users;"
```

### Scenario 2: Adding New Column

```bash
# 1. Update model in app/db/models.py
# Add: email: Mapped[str] = mapped_column(String(255), nullable=True)

# 2. Generate migration
alembic revision --autogenerate -m "Add email to users"

# 3. Review migration file
cat alembic/versions/xxxxx_add_email_to_users.py

# 4. Apply migration
alembic upgrade head

# 5. Verify
psql -U wareed_user -d wareed_db -c "\d users"
```

### Scenario 3: Modifying Existing Column

```bash
# 1. Update model
# Change: title: Mapped[str] = mapped_column(String(500), nullable=True)

# 2. Generate migration
alembic revision --autogenerate -m "Increase title length"

# 3. Review and edit if needed
# Alembic may not detect all changes (e.g., length change)
# Edit migration file manually if needed

# 4. Apply
alembic upgrade head
```

### Scenario 4: Rollback Failed Migration

```bash
# If migration fails halfway
alembic downgrade -1

# Fix the migration file
# Then re-apply
alembic upgrade head
```

### Scenario 5: Production Migration with Backup

```bash
# 1. Backup database
pg_dump -U wareed_user wareed_db > backup_before_migration.sql

# 2. Test migration on staging
# (on staging server)
alembic upgrade head

# 3. If successful, run on production
# (on production server)
alembic upgrade head

# 4. Verify
alembic current
# Test application functionality
```

---

## Best Practices

### 1. Always Review Auto-generated Migrations

Auto-generate is smart but not perfect:
- Check for unwanted changes
- Verify data migrations
- Add custom logic if needed

### 2. Use Descriptive Migration Messages

```bash
# Good
alembic revision --autogenerate -m "Add user preferences table"

# Bad
alembic revision --autogenerate -m "Update"
```

### 3. Test Migrations on Staging First

Never run migrations on production without testing:
1. Test on local development
2. Test on staging environment
3. Only then run on production

### 4. Backup Before Production Migrations

```bash
# Always backup before migration
pg_dump wareed_db > backup_$(date +%Y%m%d_%H%M%S).sql

# Then migrate
alembic upgrade head

# If something goes wrong
psql wareed_db < backup_20260202_100000.sql
```

### 5. Keep Migrations Small and Focused

One migration = one logical change:
- ✅ "Add email column to users"
- ❌ "Add email, refactor conversations, update indexes"

### 6. Don't Edit Applied Migrations

Once a migration is applied (especially in production):
- DON'T edit the migration file
- Create a NEW migration to fix issues

### 7. Handle Data Migrations Carefully

When adding non-nullable columns to existing tables:

```python
def upgrade() -> None:
    # Step 1: Add nullable column
    op.add_column('users', sa.Column('email', sa.String(255), nullable=True))
    
    # Step 2: Populate with default values
    op.execute("UPDATE users SET email = id::text || '@temp.com' WHERE email IS NULL")
    
    # Step 3: Make non-nullable
    op.alter_column('users', 'email', nullable=False)
```

---

## Troubleshooting

### Error: "Can't locate revision"

```bash
# Solution: Stamp database with current version
alembic stamp head
```

### Error: "Target database is not up to date"

```bash
# Check current version
alembic current

# Check history
alembic history

# Upgrade to head
alembic upgrade head
```

### Error: "Table already exists"

```bash
# Check database state
psql -U wareed_user -d wareed_db -c "\dt"

# If tables exist but alembic doesn't know about them
alembic stamp head
```

### Error: "Can't drop table, has dependent objects"

```bash
# Migration failed because of foreign keys
# Solution: Drop in correct order or use CASCADE

# In migration file:
def downgrade() -> None:
    op.drop_table('messages')      # Drop children first
    op.drop_table('conversations')
    op.drop_table('users')        # Drop parent last
```

### Error: "Column does not exist"

```bash
# Migration applied but column missing
# Check migration was actually applied
alembic current

# Check table structure
psql -U wareed_user -d wareed_db -c "\d table_name"

# Re-run migration
alembic downgrade -1
alembic upgrade head
```

---

## Development Workflow

### Daily Development

```bash
# 1. Pull latest code
git pull

# 2. Check if migrations need applying
alembic current
alembic history

# 3. Apply any new migrations
alembic upgrade head

# 4. Start working on new feature
# ... edit models ...

# 5. Create migration for your changes
alembic revision --autogenerate -m "Your feature"

# 6. Review migration
cat alembic/versions/xxxxx_your_feature.py

# 7. Test migration
alembic upgrade head

# 8. Test application
python -m pytest

# 9. Commit migration with code
git add alembic/versions/
git commit -m "Add feature X with migration"
```

---

## Production Deployment Checklist

- [ ] Backup production database
- [ ] Test migration on local copy of production data
- [ ] Test migration on staging environment
- [ ] Schedule maintenance window (if needed)
- [ ] Notify users of potential downtime
- [ ] Apply migration: `alembic upgrade head`
- [ ] Verify migration: `alembic current`
- [ ] Test application functionality
- [ ] Monitor error logs
- [ ] Keep backup for 24 hours
- [ ] Document migration in changelog

---

## Emergency Rollback

If migration causes critical issues in production:

```bash
# 1. Downgrade database immediately
alembic downgrade -1

# 2. Restart application with previous code version
git checkout previous_version
systemctl restart wareed-backend

# 3. Verify application is working
curl http://localhost:8000/api/health

# 4. Investigate issue
# Review migration file
# Check error logs

# 5. Fix migration
# Edit migration file or create new one

# 6. Test fix thoroughly on staging

# 7. Re-apply when ready
git checkout main
alembic upgrade head
systemctl restart wareed-backend
```

---

## References

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)

---

**Version:** 1.0.0  
**Last Updated:** 2026-02-02
