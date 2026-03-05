import hashlib
import importlib.util
import json
import sys
from pathlib import Path

OUT_PATH = Path("app/data/runtime/rag/packages_clean.jsonl")
EXTRACTOR_PATH = Path("tools/tmp_extract_packages_report_v2.py")


def load_extract_rows():
    spec = importlib.util.spec_from_file_location("tmp_extract_packages_report_v2", EXTRACTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load extractor module from {EXTRACTOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.extract_rows


def make_id(main_category: str, package_name: str, price_raw: str) -> str:
    base = f"{main_category}|{package_name}|{price_raw}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def build_tags(main_category: str, package_name: str) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()

    def add_tag(value: str) -> None:
        v = (value or "").strip()
        if not v:
            return
        key = v.lower()
        if key in seen:
            return
        seen.add(key)
        tags.append(v)

    add_tag(main_category)
    add_tag(package_name)
    for token in package_name.split():
        add_tag(token)
    return tags


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    extract_rows = load_extract_rows()
    rows = extract_rows()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for rec in rows:
            obj = {
                "id": make_id(rec["main_category"], rec["package_name"], rec["price_raw"]),
                "source_type": "excel",
                "lang": "ar",
                "page_type": "package",
                "main_category": rec["main_category"],
                "package_name": rec["package_name"],
                "description": rec["description"],  # full text
                "price_raw": rec["price_raw"],
                "price_number": rec["price_number"],
                "currency": rec["currency"] or "SAR",
                "included_count": rec.get("included_count"),
                "tags": build_tags(rec["main_category"], rec["package_name"]),
            }
            line = json.dumps(obj, ensure_ascii=False)
            fh.write(line + "\n")
            if len(lines) < 5:
                lines.append(line)

    print(f"output_path: {OUT_PATH}")
    print(f"total_rows_written: {len(rows)}")
    print("first_5_json_lines:")
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
