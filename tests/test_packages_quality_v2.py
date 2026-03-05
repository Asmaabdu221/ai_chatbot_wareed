from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.knowledge_engine.build_pipeline_v2 import BuildConfig, build_all


def test_packages_quality_v2(tmp_path: Path) -> None:
    analyses = tmp_path / "analyses_with_prices.xlsx"
    praacise = tmp_path / "praacise.xlsx"
    packages = tmp_path / "PAKAGE1.xlsx"
    faq = tmp_path / "faq.xlsx"
    branches = tmp_path / "branches.xlsx"
    runtime = tmp_path / "runtime"

    pd.DataFrame(
        [
            {"analysis_name_ar": "صورة الدم الكاملة", "analysis_name_en": "CBC", "price": 100},
            {"analysis_name_ar": "انزيم الكبد 1", "analysis_name_en": "AST", "price": 110},
            {"analysis_name_ar": "فحص البلمرة", "analysis_name_en": "PCR", "price": 120},
        ]
    ).to_excel(analyses, index=False)

    pd.DataFrame(
        [
            {"Arabic name": "صورة الدم الكاملة", "English name": "CBC", "price": 95},
            {"Arabic name": "انزيم الكبد 1", "English name": "AST", "price": 105},
            {"Arabic name": "فحص البلمرة", "English name": "PCR", "price": 115},
        ]
    ).to_excel(praacise, index=False)

    pd.DataFrame(
        [
            {
                "اسم الباقة": "باقة A",
                "وصف الباقة": "- اختبار صورة الدم الكاملة (CBC):\nيكشف عن فقر الدم\n- اختبار انزيم الكبد 1 (AST):\nيستخدم لمتابعة وظائف الكبد",
                "سعر الباقة": "185 ريال",
            },
            {
                "اسم الباقة": "باقة B",
                "وصف الباقة": "• اختبار PCR\nيقيس الحمل الفيروسي\n- تحليل CBC:",
                "سعر الباقة": "1,250",
            },
            {
                "اسم الباقة": "باقة C",
                "وصف الباقة": "- اختبار AST\nيتم جمع العينة صباحا",
                "سعر الباقة": 300,
            },
        ]
    ).to_excel(packages, index=False)

    pd.DataFrame([{"question": "س؟", "answer": "ج"}]).to_excel(faq, index=False)
    pd.DataFrame([{"city": "الرياض", "area": "الملز", "branch_name": "فرع الملز"}]).to_excel(branches, index=False)

    cfg = BuildConfig(
        analyses_path=analyses,
        praacise_path=praacise,
        packages_path=packages,
        faq_path=faq,
        branches_path=branches,
        runtime_dir=runtime,
    )
    build_all(config=cfg, write_embeddings=False)

    packages_data = json.loads((runtime / "packages.json").read_text(encoding="utf-8"))
    assert len(packages_data) >= 3

    forbidden = ("يكشف", "يستخدم", "يقيس")
    for rec in packages_data[:3]:
        assert rec["name"]
        assert len(rec["name"]) < 120
        assert rec["name"] != rec["description_long"]
        assert isinstance(rec["price"], (int, float))
        assert isinstance(rec["tests"], list)
        assert isinstance(rec["tests_mapped"], list)
        for t in rec["tests"]:
            assert all(word not in t for word in forbidden)

