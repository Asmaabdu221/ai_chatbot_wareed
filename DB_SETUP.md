# إعداد قاعدة البيانات والـ Migrations — chat.wareed.com.sa

دليل إعداد اتصال PostgreSQL وتشغيل الـ migrations حسب بيانات السيرفر في Plesk.

---

## 1. بيانات قاعدة البيانات (من Plesk)

| البند | القيمة |
|--------|--------|
| **اسم القاعدة** | `chat_user` |
| **السيرفر/المنفذ** | `localhost:5432` (على نفس السيرفر) أو `chat.wareed.com.sa:5432` (اتصال عن بُعد) |
| **اسم المستخدم** | `chat_user` |
| **كلمة المرور** | (من Plesk — لا تُدرج في الكود أو المستودع) |
| **الموقع المرتبط** | chat.wareed.com.sa |

---

## 2. إعداد ملف `.env`

1. انسخ `.env.example` إلى `.env` إذا لم يكن موجوداً:
   ```bash
   copy .env.example .env
   ```
2. عدّل في `.env` السطر:
   ```env
   DATABASE_URL=postgresql://chat_user:YOUR_DB_PASSWORD@localhost:5432/chat_user
   ```
3. استبدل `YOUR_DB_PASSWORD` بكلمة المرور الفعلية من Plesk.
4. **إذا كانت كلمة المرور تحتوي على رموز خاصة** يجب ترميزها في الرابط:
   - `#` → `%23`
   - `~` → `%7E`
   - مثال: إذا كانت كلمة المرور `abc#~123` استخدم في الرابط: `abc%23%7E123`

**اتصال عن بُعد (من جهازك إلى السيرفر):**

- غيّر `localhost` إلى `chat.wareed.com.sa` في `DATABASE_URL`.
- تأكد في Plesk من تفعيل **Remote access** للقاعدة وسماح عنوان IP جهازك (أو استخدام قواعد الجدار الناري كما في إعداداتك).

**مثال نهائي (بدون كلمة مرور حقيقية):**

```env
DATABASE_URL=postgresql://chat_user:كلمة_المرور_مرمزة@localhost:5432/chat_user
```

---

## 3. تشغيل الـ Migrations

من جذر المشروع (حيث يوجد `alembic.ini`):

```bash
# التأكد من تفعيل البيئة الافتراضية إن وُجدت
# Windows:
venv\Scripts\activate
# Linux/macOS:
# source venv/bin/activate

# تطبيق كل الـ migrations وإنشاء الجداول (users, conversations, messages)
alembic upgrade head
```

يجب أن ترى رسالة مثل: `INFO [alembic.runtime.migration] Running upgrade  -> 8e2be79a3ff3, Initial schema...`

---

## 4. التحقق من الاتصال

تشغيل التطبيق:

```bash
uvicorn app.main:app --reload
```

إذا كان `DATABASE_URL` مضبوطاً بشكل صحيح ستظهر في السجل رسالة مثل:
`✅ Database connection validated successfully`

إذا لم تضبط `DATABASE_URL` أو تركتها فارغة سيعمل التطبيق بدون قاعدة بيانات (وضع تجريبي):
`⚠️ Database disabled - DATABASE_URL not set (demo mode)`

---

## 5. أوامر مفيدة لـ Alembic

| الأمر | الوظيفة |
|--------|----------|
| `alembic upgrade head` | تطبيق كل الـ migrations حتى آخر نسخة |
| `alembic current` | عرض النسخة الحالية للمigration على القاعدة |
| `alembic history` | عرض سجل الـ revisions |
| `alembic downgrade -1` | الرجوع migration واحدة للخلف (للتجربة فقط) |

---

## 6. الجداول بعد أول Migration

بعد `alembic upgrade head` ستُنشأ الجداول التالية:

- **users** — المستخدمون (id, created_at, last_active_at, is_active)
- **conversations** — المحادثات (id, user_id, title, created_at, updated_at, is_archived)
- **messages** — الرسائل (id, conversation_id, role, content, token_count, created_at, deleted_at)

---

## 7. ملاحظات أمنية

- لا ترفع ملف `.env` إلى Git (يجب أن يكون في `.gitignore`).
- لا تضع كلمة مرور القاعدة في الكود أو في المستودع.
- على السيرفر استخدم متغيرات البيئة أو ملف `.env` آمن وصوله محدود.

يمكنك استخدام هذا الملف كمرجع لفريقك أو لتوثيق خطوات النشر على chat.wareed.com.sa.
