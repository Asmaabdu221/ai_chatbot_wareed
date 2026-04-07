import json
from pathlib import Path


TARGETS = {
    "HbA1c": ["hba1c", "\u0627\u0644\u0647\u064a\u0645\u0648\u063a\u0644\u0648\u0628\u064a\u0646 \u0627\u0644\u0633\u0643\u0631\u064a", "\u0633\u0643\u0631 \u062a\u0631\u0627\u0643\u0645\u064a", "a1c"],
    "Vitamin D": ["vitamin d", "\u0641\u064a\u062a\u0627\u0645\u064a\u0646 \u062f"],
    "TSH": ["tsh", "\u0627\u0644\u0647\u0631\u0645\u0648\u0646 \u0627\u0644\u0645\u062d\u0641\u0632 \u0644\u0644\u063a\u062f\u0629 \u0627\u0644\u062f\u0631\u0642\u064a\u0629"],
    "Iron": ["\u062d\u062f\u064a\u062f", "ferritin", "\u0641\u064a\u0631\u064a\u062a\u064a\u0646"],
    "ANA": ["ana", "\u0627\u0644\u0623\u062c\u0633\u0627\u0645 \u0627\u0644\u0645\u0636\u0627\u062f\u0629 \u0644\u0644\u0646\u0648\u0627\u0629", "\u0627\u0644\u0627\u062c\u0633\u0627\u0645 \u0627\u0644\u0645\u0636\u0627\u062f\u0629 \u0644\u0644\u0646\u0648\u0627\u0629"],
    "Aldosterone": ["aldosterone", "\u0627\u0644\u062f\u0648\u0633\u062a\u064a\u0631\u0648\u0646", "\u0623\u0644\u062f\u0648\u0633\u062a\u064a\u0631\u0648\u0646"],
    "Aldolase": ["aldolase", "\u0627\u0644\u062f\u0648\u0644\u0627\u0632", "\u0623\u0644\u062f\u0648\u0644\u0627\u0632"],
}

FILES = [
    "app/data/runtime/rag/tests_business_clean.jsonl",
    "app/data/runtime/rag/tests_clean.jsonl",
]

SHOW_FIELDS = ["id", "test_name_ar", "title", "h1", "benefit", "summary_ar", "content_clean", "url"]


def load_rows(fp: str) -> list[dict]:
    rows = []
    with Path(fp).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main() -> None:
    for fp in FILES:
        rows = load_rows(fp)
        print(f"\n=== FILE {fp} ===")
        for label, terms in TARGETS.items():
            found = None
            for obj in rows:
                blob = " ".join(
                    [
                        str(obj.get("test_name_ar", "")),
                        str(obj.get("title", "")),
                        str(obj.get("h1", "")),
                        str(obj.get("english_name", "")),
                        str(obj.get("code_alt_name", "")),
                        " ".join(str(x) for x in obj.get("match_terms", []))
                        if isinstance(obj.get("match_terms"), list)
                        else str(obj.get("match_terms", "")),
                        " ".join(str(x) for x in obj.get("match_terms_norm", []))
                        if isinstance(obj.get("match_terms_norm"), list)
                        else str(obj.get("match_terms_norm", "")),
                    ]
                ).lower()
                if any(t.lower() in blob for t in terms):
                    found = obj
                    break

            print(f"\n-- {label} --")
            if not found:
                print("NOT_FOUND")
                continue
            for field in SHOW_FIELDS:
                if field in found:
                    val = found.get(field)
                    if isinstance(val, str) and len(val) > 420:
                        val = val[:420] + "..."
                    print(f"{field}: {val}")


if __name__ == "__main__":
    main()
