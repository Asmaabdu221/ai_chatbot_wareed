# WAREED V1 - Production Deployment Guide

This guide covers the complete production deployment process for the WAREED Medical AI Chatbot with PostgreSQL database persistence.

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Database Setup](#database-setup)
3. [Environment Configuration](#environment-configuration)
4. [Database Migrations](#database-migrations)
5. [Backend Deployment](#backend-deployment)
6. [Frontend Deployment](#frontend-deployment)
7. [Health Verification](#health-verification)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software
- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- Git

### Required Credentials
- OpenAI API Key (required)
- PostgreSQL database credentials

---

## Database Setup

### 1. Install PostgreSQL

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**Windows:**
- Download installer from https://www.postgresql.org/download/windows/
- Install with default settings
- Remember the password for `postgres` user

**macOS:**
```bash
brew install postgresql@14
brew services start postgresql@14
```

### 2. Create Database and User

Connect to PostgreSQL:
```bash
sudo -u postgres psql
```

Create database and user:
```sql
-- Create database
CREATE DATABASE wareed_db;

-- Create user with password
CREATE USER wareed_user WITH PASSWORD 'your_secure_password_here';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE wareed_db TO wareed_user;

-- Grant schema privileges (PostgreSQL 15+)
\c wareed_db
GRANT ALL ON SCHEMA public TO wareed_user;

-- Exit
\q
```

### 3. Verify Connection

Test the connection:
```bash
psql -h localhost -U wareed_user -d wareed_db
```

---

## Environment Configuration

### 1. Backend Environment

Copy the example file:
```bash
cd ai_chatbot_wareed
cp .env.example .env
```

Edit `.env` with your values:
```env
# ============================================
# PRODUCTION ENVIRONMENT VARIABLES
# ============================================

# OpenAI API Configuration (REQUIRED)
OPENAI_API_KEY=sk-your-actual-openai-api-key-here
OPENAI_MODEL=gpt-4
OPENAI_MAX_TOKENS=500
OPENAI_TEMPERATURE=0.7

# Application Settings
APP_NAME=Wareed AI Medical Assistant
APP_VERSION=1.0.0
DEBUG=False

# Database Configuration (REQUIRED)
# Format: postgresql://user:password@host:port/database
DATABASE_URL=postgresql://wareed_user:your_secure_password_here@localhost:5432/wareed_db

# Database Connection Pool Settings
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600

# Logging Configuration
LOG_LEVEL=INFO
LOG_FILE=logs/wareed_app.log
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=5

# Security - CORS Origins
CORS_ORIGINS=http://localhost:3000,http://localhost:8000,https://your-production-domain.com

# Rate Limiting
RATE_LIMIT_PER_MINUTE=20
```

### 2. Frontend Environment

```bash
cd frontend-react
cp .env.example .env
```

Edit `frontend-react/.env`:
```env
REACT_APP_API_URL=http://localhost:8000
# For production: REACT_APP_API_URL=https://api.your-domain.com
```

---

## Database Migrations

### 1. Install Dependencies

Activate virtual environment and install packages:
```bash
# Create virtual environment (if not exists)
python -m venv venv

# Activate virtual environment
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Windows CMD:
.\venv\Scripts\activate.bat
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Create Initial Migration

Generate the migration from models:
```bash
alembic revision --autogenerate -m "Initial migration: users, conversations, messages"
```

This creates a migration file in `alembic/versions/`.

### 3. Review Migration

**IMPORTANT:** Always review the generated migration file before applying!

Open `alembic/versions/xxxx_initial_migration.py` and verify:
- All tables are created (users, conversations, messages)
- All columns have correct types
- Foreign keys are properly defined
- Indexes are created
- ENUM types are created correctly

### 4. Apply Migration

Run the migration:
```bash
alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade  -> xxxxx, Initial migration: users, conversations, messages
```

### 5. Verify Database Schema

Connect to database and verify:
```bash
psql -h localhost -U wareed_user -d wareed_db
```

```sql
-- List all tables
\dt

-- Should show:
--  Schema |       Name       | Type  |    Owner
-- --------+------------------+-------+-------------
--  public | alembic_version  | table | wareed_user
--  public | conversations    | table | wareed_user
--  public | messages         | table | wareed_user
--  public | users            | table | wareed_user

-- View table structure
\d users
\d conversations
\d messages

-- Exit
\q
```

---

## Backend Deployment

### 1. Production Server Setup

Install production server:
```bash
pip install gunicorn  # Linux/Mac
# or
pip install waitress  # Windows
```

### 2. Start Backend Server

**Using Uvicorn (Development/Testing):**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Using Gunicorn (Production - Linux/Mac):**
```bash
gunicorn app.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log \
  --log-level info
```

**Using Waitress (Production - Windows):**
```bash
waitress-serve --host 0.0.0.0 --port 8000 app.main:app
```

### 3. Verify Backend

Test the API:
```bash
# Health check
curl http://localhost:8000/api/health

# Expected response:
# {"api_status":"healthy","openai_configured":true}
```

---

## Frontend Deployment

### 1. Install Dependencies

```bash
cd frontend-react
npm install
```

### 2. Development Server

```bash
npm start
```

Access at: http://localhost:3000

### 3. Production Build

```bash
npm run build
```

This creates an optimized build in `frontend-react/build/`.

### 4. Deploy Production Build

**Option 1: Serve with Node.js**
```bash
npm install -g serve
serve -s build -l 3000
```

**Option 2: Nginx**
```nginx
server {
    listen 80;
    server_name your-domain.com;
    root /path/to/frontend-react/build;
    index index.html;

    location / {
        try_files $uri /index.html;
    }

    location /api {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Option 3: Cloud Platforms**
- Vercel: `vercel deploy`
- Netlify: `netlify deploy --prod`
- AWS S3 + CloudFront

---

## Health Verification

### 1. Backend Health Checks

```bash
# Basic health
curl http://localhost:8000/

# API health
curl http://localhost:8000/api/health

# Chat service health
curl http://localhost:8000/api/chat/health
```

### 2. Database Connection

```bash
# Check database tables
psql -h localhost -U wareed_user -d wareed_db -c "\dt"

# Count records
psql -h localhost -U wareed_user -d wareed_db -c "SELECT COUNT(*) FROM users;"
```

### 3. End-to-End Test

Test the complete flow:
```bash
# Send a test message
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"مرحبا", "include_knowledge":true}'
```

Expected response should include:
- `conversation_id`
- `message_id`
- `reply`
- `success: true`

---

## Troubleshooting

### Database Connection Errors

**Error:** `could not connect to server`
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql  # Linux
brew services list  # Mac

# Start if not running
sudo systemctl start postgresql  # Linux
brew services start postgresql@14  # Mac
```

**Error:** `password authentication failed`
- Verify DATABASE_URL in `.env`
- Check PostgreSQL user password
- Reset password if needed:
  ```sql
  ALTER USER wareed_user WITH PASSWORD 'new_password';
  ```

### Migration Errors

**Error:** `Target database is not up to date`
```bash
# Check current version
alembic current

# See migration history
alembic history

# Upgrade to latest
alembic upgrade head
```

**Error:** `Can't locate revision identified by 'xxxxx'`
```bash
# Stamp database to specific revision
alembic stamp head
```

### Backend Errors

**Error:** `ModuleNotFoundError: No module named 'app'`
```bash
# Ensure you're in the project root
cd ai_chatbot_wareed

# Verify PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"  # Linux/Mac
$env:PYTHONPATH = "$(pwd)"  # Windows PowerShell
```

**Error:** `OPENAI_API_KEY field required`
- Verify `.env` file exists
- Check OPENAI_API_KEY is set
- Restart server after updating .env

### Frontend Errors

**Error:** `Failed to fetch`
- Verify backend is running on correct port
- Check REACT_APP_API_URL in .env
- Check CORS_ORIGINS includes frontend URL

**Error:** `Conversations not loading`
- Check browser console for errors
- Verify backend /api/conversations endpoint works
- Check database has data: `SELECT * FROM conversations;`

---

## Production Checklist

- [ ] PostgreSQL installed and running
- [ ] Database `wareed_db` created
- [ ] User `wareed_user` created with proper privileges
- [ ] `.env` file configured with production values
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Database migrations applied (`alembic upgrade head`)
- [ ] Backend server running and healthy
- [ ] Frontend built and deployed
- [ ] CORS configured for production domain
- [ ] HTTPS/SSL configured (production only)
- [ ] Logging directory exists (`logs/`)
- [ ] Firewall rules configured (ports 8000, 5432)
- [ ] Backup strategy implemented
- [ ] Monitoring/alerting configured

---

## Production Best Practices

1. **Security**
   - Use strong passwords
   - Enable PostgreSQL SSL
   - Use HTTPS for all endpoints
   - Rotate API keys regularly
   - Enable database backups

2. **Performance**
   - Monitor database connection pool
   - Set up database indexes
   - Enable response caching
   - Use CDN for frontend

3. **Monitoring**
   - Set up error tracking (Sentry)
   - Monitor API response times
   - Track database query performance
   - Alert on high error rates

4. **Backup**
   - Daily PostgreSQL backups
   - Store backups off-site
   - Test restore procedures
   - Keep 30 days of backups

---

## Support

For issues or questions:
1. Check logs: `tail -f logs/wareed_app.log`
2. Review PostgreSQL logs: `sudo tail -f /var/log/postgresql/postgresql-14-main.log`
3. Check database status: `psql -U wareed_user -d wareed_db`

---

**Last Updated:** 2026-02-02  
**Version:** 1.0.0
