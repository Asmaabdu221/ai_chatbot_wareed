"""
Build packages KB documents for semantic fallback search.

Usage:
  python -m app.data.build_packages_kb
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PACKAGES_INDEX_PATH = Path(__file__).resolve().parent / "packages_index.json"
PACKAGES_KB_PATH = Path(__file__).resolve().parent / "packages_kb.json"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_packages_kb(
    source_path: Path = PACKAGES_INDEX_PATH,
    output_path: Path = PACKAGES_KB_PATH,
) -> list[dict[str, Any]]:
    if not source_path.exists():
        raise FileNotFoundError(f"packages_index.json not found: {source_path}")

    records = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("packages_index.json must contain a list")

    docs: list[dict[str, Any]] = []
    for rec in records:
        content_parts = [
            _clean(rec.get("name_raw")),
            _clean(rec.get("description_raw")),
            _clean(rec.get("includes_text")),
            _clean(rec.get("sample_type_text")),
            _clean(rec.get("turnaround_text")),
            _clean(rec.get("audience_text")),
        ]
        content = "\n".join([p for p in content_parts if p]).strip()
        docs.append(
            {
                "id": rec.get("id"),
                "name": rec.get("name_raw"),
                "section": rec.get("section"),
                "content": content,
            }
        )

    output_path.write_text(
        json.dumps(docs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return docs


def main() -> None:
    docs = build_packages_kb()
    print(f"packages kb docs: {len(docs)}")
    print(f"output: {PACKAGES_KB_PATH}")


if __name__ == "__main__":
    main()
