# تحديث نظام RAG - دليل التفعيل

## ملخص التعديلات

تم تنفيذ التحديثات التالية على نظام RAG:

### 1️⃣ مصدر المعرفة الوحيد
- **الملف:** `app/data/analysis_file.xlsx`
- تم حذف الاعتماد على مصادر أخرى
- إعادة بناء Vector Database بالكامل من هذا الملف فقط

### 2️⃣ منع الهلوسة (Hallucination Prevention)
- **Strict Retrieval:** الإجابة فقط من المعلومات المسترجعة
- **Similarity Threshold:** 0.75 (قابل للتعديل عبر `RAG_SIMILARITY_THRESHOLD`)
- إذا لم تُوجد نتيجة فوق الحد → "عذرًا، لا توجد معلومات متاحة حول هذا الموضوع في النظام حالياً."
- لا حقن معرفة خارجية

### 3️⃣ مطابقة الأسعار
- دمج الأسعار من `knowledge_base_with_faq.json` (الملف القديم)
- تقنيات المطابقة: Fuzzy, Levenshtein, Arabic normalization
- لا تخمين أو اختراع أسعار

### 4️⃣ دعم العربية
- تطبيع النص: إزالة التشكيل، توحيد الألف والياء
- Semantic search مع embeddings
- Fuzzy query handling

### 5️⃣ بنية RAG
- Data Preprocessing
- Document Chunking (تحليل واحد = chunk واحد)
- Embedding: text-embedding-3-small (أو text-embedding-3-large)
- Vector Similarity Search (cosine)
- Response Generation (Grounded Only)

---

## خطوات التفعيل

### 1. إضافة ملف التحاليل
ضع الملف `analysis_file.xlsx` في المسار:
```
app/data/analysis_file.xlsx
```

### 2. تنسيق الملف المتوقع
الأعمدة المدعومة (بالعربية أو الإنجليزية):

| العمود (عربي) | العمود (إنجليزي) | الحقل |
|---------------|------------------|-------|
| اسم التحليل بالعربية | analysis_name_ar | **مطلوب** |
| Unnamed: 0 / english_name | analysis_name_en | اختياري |
| فائدة التحليل | description | اختياري |
| التحاليل المكملة | complementary_tests | اختياري |
| تحاليل قريبة | related_tests | اختياري |
| تحاليل بديلة | alternative_tests | اختياري |
| نوع العينة | sample_type | اختياري |
| تصنيف التحليل | category | اختياري |
| الأعراض | symptoms | اختياري |
| التحضير قبل التحليل | preparation | اختياري |

### 3. بناء نظام RAG
من جذر المشروع:
```bash
python -m app.data.build_rag_system
```

سيقوم السكربت بـ:
1. تحميل `analysis_file.xlsx`
2. مطابقة الأسعار من الملف القديم
3. حفظ `rag_knowledge_base.json`
4. إنشاء embeddings
5. حفظ `rag_embeddings.json`
6. حذف الفهرس القديم

### 4. تشغيل التطبيق
```bash
uvicorn app.main:app --reload
```

---

## إعدادات البيئة (.env)

```bash
# حد التشابه الأدنى (0.0 - 1.0)
RAG_SIMILARITY_THRESHOLD=0.75

# نموذج الـ embedding (اختياري)
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
# أو للنموذج الأكبر:
# OPENAI_EMBEDDING_MODEL=text-embedding-3-large
```

---

## الملفات الجديدة

| الملف | الوصف |
|-------|-------|
| `app/utils/arabic_normalizer.py` | تطبيع النص العربي |
| `app/data/analysis_loader.py` | تحميل Excel + مطابقة الأسعار |
| `app/data/rag_pipeline.py` | خط أنابيب RAG مع حد التشابه |
| `app/data/build_rag_system.py` | سكربت البناء |
| `app/data/rag_knowledge_base.json` | قاعدة المعرفة (مخرجات) |
| `app/data/rag_embeddings.json` | الـ embeddings (مخرجات) |

---

## إعادة التحميل

بعد تحديث `analysis_file.xlsx`:
```bash
# عبر API
POST /api/chat/knowledge/reload

# أو عبر السكربت
python -m app.data.build_rag_system
```

---

## ملاحظات

- **الملف القديم** `knowledge_base_with_faq.json` يُستخدم فقط لمطابقة الأسعار عند البناء. يمكن حذفه بعد التأكد من نجاح المطابقة.
- إذا لم يُبنَ نظام RAG بعد، سيرد الشاتبوت بـ "عذرًا، لا توجد معلومات متاحة..." حتى يتم تشغيل سكربت البناء.
