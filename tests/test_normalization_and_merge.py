from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.knowledge_engine.build_pipeline_v2 import BuildConfig, build_all


def test_praacise_price_overrides_analyses_when_matched(tmp_path: Path) -> None:
    analyses = tmp_path / "analyses_with_prices.xlsx"
    praacise = tmp_path / "praacise.xlsx"
    packages = tmp_path / "PAKAGE1.xlsx"
    faq = tmp_path / "faq.xlsx"
    branches = tmp_path / "branches.xlsx"
    runtime = tmp_path / "runtime"

    pd.DataFrame(
        [
            {
                "analysis_name_ar": "تحليل سكر",
                "analysis_name_en": "Blood  Sugar!",
                "price": 120,
                "description": "desc",
            }
        ]
    ).to_excel(analyses, index=False)

    pd.DataFrame(
        [
            {"Arabic name": "تحليل سكر صائم", "English name": "blood sugar", "price": 90},
        ]
    ).to_excel(praacise, index=False)

    pd.DataFrame([{"name": "باقة 1", "description": "اختبار سكر", "price": 10}]).to_excel(packages, index=False)
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

    tests_kb = json.loads((runtime / "tests_kb.json").read_text(encoding="utf-8"))
    assert len(tests_kb) == 1
    rec = tests_kb[0]
    assert rec["price_final"] == 90.0
    assert rec["name_ar_final"] == "تحليل سكر صائم"

