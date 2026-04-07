import json
from pathlib import Path


BIZ_PREFIXES = [
    "analysis::259_",
    "analysis::564_",
    "analysis::508_",
    "analysis::330_",
    "analysis::67_",
    "analysis::20_",
    "analysis::19_",
]

CLEAN_IDS = [
    "4bca74616ec1",
    "02cddfddcf79",
    "1b457edacf2c",
    "b77ad89c8f71",
    "e510df4dca5a",
]


def load_jsonl(path: str) -> list[dict]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def print_val(key: str, value) -> None:
    if isinstance(value, str) and len(value) > 420:
        value = value[:420] + "..."
    print(f"{key}: {value}")


def main() -> None:
    biz = load_jsonl("app/data/runtime/rag/tests_business_clean.jsonl")
    clean = load_jsonl("app/data/runtime/rag/tests_clean.jsonl")

    print("=== BUSINESS SELECTED ===")
    for prefix in BIZ_PREFIXES:
        rec = next((r for r in biz if str(r.get("id", "")).startswith(prefix)), None)
        print(f"\n{prefix}")
        if not rec:
            print("NOT_FOUND")
            continue
        for key in [
            "id",
            "test_name_ar",
            "english_name",
            "benefit",
            "category",
            "symptoms",
            "preparation",
            "complementary_tests",
            "alternative_tests",
        ]:
            print_val(key, rec.get(key))

    print("\n=== CLEAN SELECTED ===")
    for cid in CLEAN_IDS:
        rec = next((r for r in clean if str(r.get("id", "")) == cid), None)
        print(f"\n{cid}")
        if not rec:
            print("NOT_FOUND")
            continue
        for key in ["id", "test_name_ar", "title", "h1", "summary_ar", "content_clean", "url"]:
            print_val(key, rec.get(key))


if __name__ == "__main__":
    main()
