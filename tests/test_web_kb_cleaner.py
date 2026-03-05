from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from app.knowledge_engine.web_kb_cleaner_hard import clean_site_knowledge_jsonl


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def test_web_kb_hard_cleaner_rules(tmp_path: Path) -> None:
    in_path = tmp_path / "site_knowledge.jsonl"
    clean_path = tmp_path / "site_knowledge_clean_hard.jsonl"
    chunks_path = tmp_path / "site_knowledge_chunks_hard.jsonl"

    long_medical = (
        "تحليل HbA1c (HbA1c) يقيس متوسط السكر في الدم خلال 3 أشهر. "
        "يستخدم لتقييم التحكم بالسكري ومتابعة فعالية العلاج. "
        "يطلب الفحص عند الاشتباه باضطراب سكر الدم أو لمتابعة العلاج. "
        "التحضير: لا يحتاج صيام غالبا ويجب إبلاغ الطبيب بالأدوية. "
        "ملاحظة مهمة: تفسير النتيجة يكون مع التاريخ المرضي. "
        "احجز الآن وسيتم التواصل معك من قبل وريد لتأكيد الحجز عبر واتساب. "
    )
    # Repeat to force chunking.
    long_medical = " ".join([long_medical] * 6)

    rows = [
        {
            "type": "web_page",
            "page_type": "test_page",
            "url": "https://wareed.test/hemoglobin-a1c-hba1c-test",
            "status_code": 200,
            "title": "تحليل السكر التراكمي (HbA1c)",
            "h1": "تحليل السكر التراكمي",
            "lang": "ar",
            "content": long_medical,
            "error": "",
            "source": "unit-test",
        },
        {
            "type": "web_page",
            "page_type": "general_page",
            "url": "https://wareed.test/ovulation-fsh-lh-e2-psa-gfr-creatinine-calcium-phosphorus",
            "status_code": 200,
            "title": "تحليل هرمونات (FSH) و (LH) و (E2) و PSA",
            "h1": "فحص الخصوبة",
            "lang": "ar",
            "content": (
                "تحليل FSH و LH و E2 يساعد في تقييم الخصوبة. "
                "تحليل PSA يفيد في المتابعة. "
                "تحليل Creatinine و GFR و Calcium و Phosphorus لدعم التقييم. "
                "PCOS و SCURVY قد تظهر كاختصارات في النص العام. "
                "خدمة سحب من المنزل متوفرة داخل الفروع. "
                "التحضير: قد يطلب صيام حسب الحالة. "
                "ملاحظة: يجب تفسير النتائج مع الطبيب."
            ),
            "error": "",
            "source": "unit-test",
        },
        {
            "type": "web_page",
            "page_type": "test_page",
            "url": "https://wareed.test/bad",
            "status_code": 500,
            "title": "bad",
            "h1": "bad",
            "lang": "ar",
            "content": "bad",
            "error": "timeout",
            "source": "unit-test",
        },
    ]

    _write_jsonl(in_path, rows)
    summary = clean_site_knowledge_jsonl(in_path, clean_path, chunks_path)

    assert summary["input_rows"] == 3
    assert summary["kept_docs"] == 2
    assert summary["dropped_docs"] == 1

    docs = _read_jsonl(clean_path)
    chunks = _read_jsonl(chunks_path)
    assert len(docs) == 2
    assert len(chunks) >= 2

    banned_phrases = ["لتأكيد الحجز", "احجز", "سيتم التواصل", "واتساب", "من قبل وريد", "الطبية", "ضمن باقة", "تواصل"]
    banned_tags = {"مختبرات", "وريد", "الطبية"}

    found_tokens = set()
    for d in docs:
        assert set(d.keys()) == {
            "id",
            "source_type",
            "url",
            "lang",
            "page_type",
            "title",
            "h1",
            "test_name_ar",
            "test_code_tokens",
            "content_clean",
            "summary_ar",
            "tags",
        }
        assert d["source_type"] == "website"
        assert d["lang"] == "ar"
        assert 120 <= len(d["content_clean"]) <= 1200
        assert len(d["summary_ar"]) <= 280
        assert "|" not in d["title"]
        for p in banned_phrases:
            assert p not in d["content_clean"]
        assert not any(t in banned_tags for t in d["tags"])
        assert len(d["test_code_tokens"]) <= 2
        found_tokens.update(d["test_code_tokens"])

    assert "HbA1c" in found_tokens
    # Primary-only policy: avoid secondary body tokens.
    assert "GFR" not in found_tokens
    assert "Creatinine" not in found_tokens
    assert "PCOS" not in found_tokens
    assert "SCURVY" not in found_tokens

    by_doc_chunks: dict[str, list[dict]] = {}
    for ch in chunks:
        assert set(ch.keys()) == {
            "chunk_id",
            "doc_id",
            "url",
            "page_type",
            "test_name_ar",
            "test_code_tokens",
            "tags",
            "text",
        }
        assert re.match(r"^[0-9a-f]{12}_\d{3}$", ch["chunk_id"])
        assert re.match(r"^[0-9a-f]{12}$", ch["doc_id"])
        by_doc_chunks.setdefault(ch["doc_id"], []).append(ch)

    for doc_id, items in by_doc_chunks.items():
        items.sort(key=lambda x: x["chunk_id"])
        for i, ch in enumerate(items):
            n = len(ch["text"])
            assert n <= 900
            if i < len(items) - 1:
                assert n >= 200


def test_web_kb_full_output_quality_gate(tmp_path: Path) -> None:
    src = Path("app/data/sources/web/site_knowledge.jsonl")
    assert src.exists()

    clean_path = tmp_path / "site_knowledge_clean_hard.jsonl"
    chunks_path = tmp_path / "site_knowledge_chunks_hard.jsonl"
    summary = clean_site_knowledge_jsonl(src, clean_path, chunks_path)
    assert summary["input_rows"] > 0
    assert summary["kept_docs"] > 0

    banned_patterns = [
        r"\b\u0648\u0631\u064a\u062f\b",
        r"\u0645\u062e\u062a\u0628\u0631\u0627\u062a",
        r"\u0627\u0644\u0637\u0628\u064a\u0629",
        r"\u0641\u064a\s+\u0627\u0644\u0637\u0628\u064a\u0629",
        r"\u0623\u0642\u0631\u0628\s+\u0641\u0631\u0639",
        r"\u062e\u062f\u0645\u0629\s+\u0645\u0646\u0632\u0644\u064a\u0629",
        r"\u0627\u062d\u062c\u0632",
        r"\u062a\u0623\u0643\u064a\u062f\s+\u0627\u0644\u062d\u062c\u0632",
        r"\u0628\u0627\u0642\u0629\s+\u0627\u0644\u062a\u062d\u0627\u0644\u064a\u0644",
        r"\u0636\u0645\u0646\s+\u0628\u0627\u0642\u0629",
        r"\u062a\u0648\u0627\u0635\u0644",
        r"\u0646\u0636\u0645\u0646",
        r"\u062e\u0644\u0627\u0644\s*24",
        r"48\s+\u0633\u0627\u0639\u0629",
        r"\u0645\s+\u0629",
        r"\u0644\u0645\s+\u0629",
        r"\b\u0627\u0644\u0645\u0647\b",
        r"\b\u0627\u0644\u0623\u0637\u0639\b",
        r"\u0627\u0644\u0623\u0637\u0639\u0645\u0629\u0645\u0629",
        r"\b\u0645\u062a\u0642\u062f\b",
        r"\u0645\u062a\u0642\u062f\u0645\u0629\u0645",
        r"\b\u0645\u0642\u0627\u0648\b",
        r"\u0627\u0644\u0639[\u0640\s]\u0627",
    ]

    for path in [clean_path, chunks_path]:
        rows = _read_jsonl(path)
        for row in rows:
            scan_parts: list[str] = []
            for key, value in row.items():
                if key == "url":
                    continue
                if isinstance(value, list):
                    scan_parts.extend(str(x) for x in value)
                else:
                    scan_parts.append(str(value))
            text = " ".join(scan_parts)
            for pat in banned_patterns:
                assert re.search(pat, text, flags=re.IGNORECASE) is None, f"found banned pattern {pat} in {path}"
            # No duplicate lines in content/summary
            for field in ["content_clean", "summary_ar", "text"]:
                if field in row:
                    lines = [ln.strip() for ln in str(row[field]).splitlines() if ln.strip()]
                    norm = [re.sub(r"\s+", " ", ln) for ln in lines]
                    assert len(norm) == len(set(norm)), f"duplicate lines in {field} for {path}"
                    # Near-duplicate guard (fuzzy) for multiline content.
                    for i in range(len(norm)):
                        for j in range(i + 1, len(norm)):
                            ratio = SequenceMatcher(None, norm[i], norm[j]).ratio()
                            assert ratio < 0.92, f"near-duplicate lines in {field} for {path}"


def test_web_kb_v31_title_tokens_and_marketing_cleanup(tmp_path: Path) -> None:
    in_path = tmp_path / "site_knowledge_v31.jsonl"
    clean_path = tmp_path / "site_knowledge_clean_hard.jsonl"
    chunks_path = tmp_path / "site_knowledge_chunks_hard.jsonl"

    rows = [
        {
            "type": "web_page",
            "page_type": "test_page",
            "url": "https://wareed.test/ldl-page",
            "status_code": 200,
            "title": "تحليل LDL | راقب قلبك واكتشف المخاطر بدقة عالية!",
            "h1": "تحليل LDL |",
            "lang": "ar",
            "content": (
                "تحليل LDL يقيس الكوليسترول الضار ويساعد في تقييم خطر أمراض القلب. "
                "يطلب الفحص ضمن متابعة دهون الدم ومراقبة الاستجابة للعلاج الغذائي والدوائي. "
                "التحضير: يفضل الصيام حسب تعليمات الطبيب. "
                "راقب قلبك واحم نفسك، نستخدم أحدث الأجهزة وبدقة تصل إلى 99%."
            ),
            "error": "",
            "source": "unit-test",
        },
        {
            "type": "web_page",
            "page_type": "test_page",
            "url": "https://wareed.test/insulin-resistance",
            "status_code": 200,
            "title": "تحليل مقاومة الانسولين | اكتشف بدقة عالية",
            "h1": "c تحليل فيتامين",
            "lang": "ar",
            "content": (
                "تحليل مقاومة الانسولين يساعد في التشخيص المبكر لاضطرابات السكر ومتابعة العلاج. "
                "يطلب الفحص عند وجود أعراض أو تاريخ مرضي متعلق بارتفاع السكر. "
                "التحضير: يفضل الصيام وفقا لتوجيهات الطبيب. "
                "رمز التحليل هو HOMA-IR. اختصار التحليل HOMA-IR."
            ),
            "error": "",
            "source": "unit-test",
        },
        {
            "type": "web_page",
            "page_type": "test_page",
            "url": "https://wareed.test/rbs-page",
            "status_code": 200,
            "title": "تحليل RBS",
            "h1": "تحليل السكر العشوائي",
            "lang": "ar",
            "content": (
                "تحليل السكر العشوائي يستخدم لتقييم مستوى الجلوكوز في الدم بسرعة خلال اليوم. "
                "يطلب الفحص عند الاشتباه باضطراب سكر الدم أو لمتابعة الخطة العلاجية. "
                "التحضير: لا يحتاج صيام غالبا. "
                "هذا النص يذكر FSH و LH و E2 داخل الشرح فقط دون نمط رمز واضح."
            ),
            "error": "",
            "source": "unit-test",
        },
    ]
    _write_jsonl(in_path, rows)
    summary = clean_site_knowledge_jsonl(in_path, clean_path, chunks_path)
    assert summary["kept_docs"] >= 2
    docs = _read_jsonl(clean_path)

    by_url = {d["url"]: d for d in docs}
    ldl = by_url["https://wareed.test/ldl-page"]
    assert "|" not in ldl["title"]
    assert "راقب قلبك" not in ldl["title"]
    assert "اكتشف" not in ldl["title"]
    assert "بدقة" not in ldl["content_clean"]

    ins = by_url["https://wareed.test/insulin-resistance"]
    assert "|" not in ins["title"]
    assert not ins["test_name_ar"].startswith("c ")
    assert ins["test_code_tokens"] == ["HOMA-IR"]
    assert len(ins["test_code_tokens"]) <= 2

    rbs = by_url["https://wareed.test/rbs-page"]
    assert "RBS" in rbs["test_code_tokens"]
    assert "FSH" not in rbs["test_code_tokens"]
    assert "LH" not in rbs["test_code_tokens"]
    assert "E2" not in rbs["test_code_tokens"]


def test_web_kb_v31_marketing_removed_from_known_pages(tmp_path: Path) -> None:
    src = Path("app/data/sources/web/site_knowledge.jsonl")
    clean_path = tmp_path / "site_knowledge_clean_hard.jsonl"
    chunks_path = tmp_path / "site_knowledge_chunks_hard.jsonl"
    clean_site_knowledge_jsonl(src, clean_path, chunks_path)
    docs = _read_jsonl(clean_path)
    by_url = {d["url"]: d for d in docs}

    targets = [
        "https://wareed.com.sa/ldl/",
        "https://wareed.com.sa/homocysteine/",
        "https://wareed.com.sa/insulin-resistance/",
    ]
    blocked = [
        "راقب قلبك",
        "احم نفسك",
        "اكتشف",
        "بدقة",
        "موثوقية",
        "سريعة",
        "الأحدث",
        "أحدث الأجهزة",
        "نستخدم أجهزة",
        "نوفر لك",
        "|",
    ]
    for url in targets:
        if url not in by_url:
            continue
        text = " ".join(
            [
                by_url[url]["title"],
                by_url[url]["h1"],
                by_url[url]["test_name_ar"],
                by_url[url]["content_clean"],
                by_url[url]["summary_ar"],
                " ".join(by_url[url]["tags"]),
            ]
        )
        for phrase in blocked:
            assert phrase not in text
