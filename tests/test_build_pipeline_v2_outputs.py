from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.knowledge_engine.build_pipeline_v2 import BuildConfig, build_all


def _write_fixture_excels(root: Path) -> BuildConfig:
    analyses = root / "analyses_with_prices.xlsx"
    praacise = root / "praacise.xlsx"
    packages = root / "PAKAGE1.xlsx"
    faq = root / "faq.xlsx"
    branches = root / "branches.xlsx"
    runtime = root / "runtime"

    pd.DataFrame(
        [
            {
                "analysis_name_ar": "تحليل سكر",
                "analysis_name_en": "Blood Sugar",
                "description": "وصف اختبار السكر",
                "symptoms": "دوخة",
                "preparation": "صيام",
                "sample_type": "دم",
                "category": "تحاليل عامة",
                "price": 110,
            },
            {
                "analysis_name_ar": "تحليل فيتامين د",
                "analysis_name_en": "Vitamin D",
                "description": "وصف فيتامين د",
                "category": "فيتامينات",
                "price": 210,
            },
        ]
    ).to_excel(analyses, index=False)

    pd.DataFrame(
        [
            {"Arabic name": "تحليل سكر صائم", "English name": "blood sugar", "price": 95},
            {"Arabic name": "تحليل فيتامين د", "English name": "vitamin d", "price": 205},
        ]
    ).to_excel(praacise, index=False)

    pd.DataFrame(
        [
            {
                "name": "باقة فحص شامل",
                "description": "- اختبار سكر\n- PCR Test\nSerology (IgG)\nنص إضافي",
                "price": 499,
            }
        ]
    ).to_excel(packages, index=False)

    pd.DataFrame(
        [
            {"question": "ما هو تحليل السكر؟", "answer": "فحص لمستوى السكر في الدم"},
            {"question": "هل يلزم صيام؟", "answer": "نعم لبعض الفحوصات"},
        ]
    ).to_excel(faq, index=False)

    pd.DataFrame(
        [
            {"city": "الرياض", "area": "النخيل", "branch_name": "فرع النخيل"},
            {"city": "جدة", "area": "الروضة", "branch_name": "فرع الروضة"},
        ]
    ).to_excel(branches, index=False)

    return BuildConfig(
        analyses_path=analyses,
        praacise_path=praacise,
        packages_path=packages,
        faq_path=faq,
        branches_path=branches,
        runtime_dir=runtime,
    )


def test_build_pipeline_v2_outputs(tmp_path: Path) -> None:
    config = _write_fixture_excels(tmp_path)
    manifest = build_all(config=config, write_embeddings=True)

    expected_files = [
        "tests_kb.json",
        "packages.json",
        "packages_index.json",
        "faq_index.json",
        "branches_index.json",
        "manifest.json",
        "tests_embeddings.json",
    ]
    for filename in expected_files:
        assert (config.runtime_dir / filename).exists(), filename

    tests_kb = json.loads((config.runtime_dir / "tests_kb.json").read_text(encoding="utf-8"))
    assert isinstance(tests_kb, list) and tests_kb
    assert {"id", "name_ar_final", "name_en_final", "price_final"}.issubset(tests_kb[0].keys())

    packages = json.loads((config.runtime_dir / "packages.json").read_text(encoding="utf-8"))
    assert packages and {"id", "name", "description_long", "description_short", "tests", "tests_mapped"}.issubset(packages[0].keys())
    display_keys = {"id", "name", "price", "description_short", "tests"}
    from app.knowledge_engine.build_pipeline_v2 import make_package_display
    assert display_keys.issubset(make_package_display(packages[0]).keys())

    packages_index = json.loads((config.runtime_dir / "packages_index.json").read_text(encoding="utf-8"))
    assert packages_index.get("version") == "packages_index_v2"
    assert isinstance(packages_index.get("by_name"), dict)
    assert isinstance(packages_index.get("aliases"), dict)
    assert all(len(k) <= 140 for k in packages_index["by_name"].keys())

    faq_index = json.loads((config.runtime_dir / "faq_index.json").read_text(encoding="utf-8"))
    assert "items" in faq_index and faq_index["items"]

    branches_index = json.loads((config.runtime_dir / "branches_index.json").read_text(encoding="utf-8"))
    assert {"branches", "by_city", "by_area", "by_name"}.issubset(branches_index.keys())

    assert manifest["counts"]["tests_kb"] == len(tests_kb)
