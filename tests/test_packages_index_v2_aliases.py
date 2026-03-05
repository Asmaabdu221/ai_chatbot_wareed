from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.knowledge_engine.build_pipeline_v2 import BuildConfig, build_all


def test_packages_index_v2_alias_rules_and_conflicts(tmp_path: Path) -> None:
    analyses = tmp_path / "analyses_with_prices.xlsx"
    praacise = tmp_path / "praacise.xlsx"
    packages = tmp_path / "PAKAGE1.xlsx"
    faq = tmp_path / "faq.xlsx"
    branches = tmp_path / "branches.xlsx"
    runtime = tmp_path / "runtime"

    pd.DataFrame([{"analysis_name_ar": "تحليل سكر", "analysis_name_en": "Sugar", "price": 10}]).to_excel(analyses, index=False)
    pd.DataFrame([{"Arabic name": "تحليل سكر", "English name": "Sugar", "price": 9}]).to_excel(praacise, index=False)

    pd.DataFrame(
        [
            {"اسم الباقة": "باقة Alpha Beta / PCR", "وصف الباقة": "- اختبار CBC", "سعر الباقة": "100 ريال"},
            {"اسم الباقة": "باقة Alpha Beta / STD", "وصف الباقة": "- اختبار AST", "سعر الباقة": "150 ريال"},
            {"اسم الباقة": "باقة PCR", "وصف الباقة": "- اختبار PCR", "سعر الباقة": "90 ريال"},
        ]
    ).to_excel(packages, index=False)

    pd.DataFrame([{"question": "س", "answer": "ج"}]).to_excel(faq, index=False)
    pd.DataFrame([{"city": "الرياض", "area": "الملز", "branch_name": "فرع الملز"}]).to_excel(branches, index=False)

    cfg = BuildConfig(
        analyses_path=analyses,
        praacise_path=praacise,
        packages_path=packages,
        faq_path=faq,
        branches_path=branches,
        runtime_dir=runtime,
    )
    manifest = build_all(config=cfg, write_embeddings=False)

    idx = json.loads((runtime / "packages_index.json").read_text(encoding="utf-8"))
    assert idx["version"] == "packages_index_v2"
    assert idx["by_name"]
    assert all(len(k) <= 140 for k in idx["by_name"].keys())
    assert all(not any(p in k for p in ("،", "؛", "!", "?", "؟", ":", ".")) for k in idx["by_name"].keys())

    # blocked single-token alias must not appear
    assert "pcr" not in idx["aliases"]
    assert "std" not in idx["aliases"]

    # shared alias should be excluded and logged as conflict
    assert "alpha beta" not in idx["aliases"]
    assert "packages_alias_conflicts" in manifest
    assert "alpha beta" in manifest["packages_alias_conflicts"]


def test_dna_package_price_from_description_and_no_tests(tmp_path: Path) -> None:
    analyses = tmp_path / "analyses_with_prices.xlsx"
    praacise = tmp_path / "praacise.xlsx"
    packages = tmp_path / "PAKAGE1.xlsx"
    faq = tmp_path / "faq.xlsx"
    branches = tmp_path / "branches.xlsx"
    runtime = tmp_path / "runtime"

    pd.DataFrame([{"analysis_name_ar": "تحليل جين", "analysis_name_en": "DNA test", "price": 10}]).to_excel(analyses, index=False)
    pd.DataFrame([{"Arabic name": "تحليل جين", "English name": "DNA test", "price": 9}]).to_excel(praacise, index=False)

    pd.DataFrame(
        [
            {"اسم الباقه": "اسم الباقه", "وصف الباقه": "وصف الباقه", "سعر الباقه": "سعر الباقه"},
            {"اسم الباقه": "باقة DNA المتقدمة", "وصف الباقه": "تفاصيل التحليل\nالهدف\nالسعر: 1875 ريال", "سعر الباقه": None},
        ]
    ).to_excel(packages, index=False)

    pd.DataFrame([{"question": "س", "answer": "ج"}]).to_excel(faq, index=False)
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
    assert len(packages_data) == 1
    pkg = packages_data[0]
    assert pkg["name"].startswith("باقة DNA")
    assert pkg["price"] == 1875.0
    assert pkg["tests"] == []
