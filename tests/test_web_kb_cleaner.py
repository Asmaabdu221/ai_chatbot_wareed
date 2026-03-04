from __future__ import annotations

import json
import re
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

    banned_phrases = ["لتأكيد الحجز", "احجز", "سيتم التواصل", "واتساب", "من قبل وريد"]
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
        for p in banned_phrases:
            assert p not in d["content_clean"]
        assert not any(t in banned_tags for t in d["tags"])
        found_tokens.update(d["test_code_tokens"])

    expected_some = {"HbA1c", "FSH", "LH", "E2", "PSA", "GFR", "Creatinine", "Calcium", "Phosphorus"}
    assert expected_some.issubset(found_tokens)
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
