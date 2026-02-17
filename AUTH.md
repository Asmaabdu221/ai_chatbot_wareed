# المصادقة — JWT Bearer (ويب + جوال)

نظام مصادقة واحد لجميع المنصات: **ويب** و **جوال (iOS/Android)**. لا كوكيز ولا جلسات من جهة السيرفر.

## القواعد

- **الاعتماد على التوكن فقط:** `Authorization: Bearer <access_token>`
- **لا استخدام:** كوكيز، جلسات من جهة السيرفر
- **تخزين التوكن (من مسؤولية العميل):**
  - **جوال:** تخزين آمن (Keychain / Keystore)
  - **ويب:** ذاكرة أو تخزين آمن (مثلاً `sessionStorage` أو تخزين مشفّر)

## الواجهات

| الطريقة | المسار | الوصف |
|--------|--------|--------|
| POST | `/api/auth/register` | تسجيل: `{"email":"...","password":"..."}` → يُرجع `access_token` و `refresh_token` |
| POST | `/api/auth/login` | دخول: نفس الجسم → نفس الاستجابة |
| POST | `/api/auth/refresh` | تجديد: `{"refresh_token":"..."}` → `access_token` جديد (واختياريًا `refresh_token`) |
| GET | `/api/auth/me` | المستخدم الحالي (يتطلب `Authorization: Bearer <access_token>`) |

## تدفق العميل (ويب أو جوال)

1. **تسجيل/دخول:** استدعاء `POST /api/auth/register` أو `POST /api/auth/login` بإرسال `email` و `password`.
2. **حفظ التوكنات:** حفظ `access_token` و `refresh_token` في التخزين الآمن أو الذاكرة.
3. **الطلبات التالية:** إرسال الهيدر في كل طلب:
   ```http
   Authorization: Bearer <access_token>
   ```
4. **عند انتهاء صلاحية access_token:** استدعاء `POST /api/auth/refresh` مع `refresh_token`، واستبدال `access_token` بالجديد (وربما `refresh_token` إن وُجد).
5. **التحقق من الجلسة:** استدعاء `GET /api/auth/me` مع نفس الهيدر للحصول على بيانات المستخدم الحالي.

## الشات والمحادثات

- **مع توكن:** إرسال `Authorization: Bearer <access_token>` مع طلب الشات؛ يُربط المستخدم تلقائيًا من التوكن (لا حاجة لإرسال `user_id` في الجسم إن أردت).
- **بدون توكن:** الطلب يعمل كضيف (وضع مجهول) مع `user_id` و `conversation_id` اختياريين في الجسم.

## إعدادات البيئة (.env)

```env
SECRET_KEY=قيمة-سرية-طويلة-عشوائية
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7
```

في الإنتاج استخدم مفتاحًا قويًا (مثلاً: `openssl rand -hex 32`).

## ملاحظات

- المصادقة تتطلب تفعيل قاعدة البيانات (`DATABASE_URL`).
- نفس التدفق للويب والجوال؛ لا منطق مختلف حسب المنصة.
