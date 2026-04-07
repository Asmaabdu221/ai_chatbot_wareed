import json

from app.services.runtime.tests_business_engine import (
    _detect_query_type,
    _norm,
    _normalize_business_query_aliases,
    _rank_target_candidates,
    load_tests_business_records,
    resolve_tests_business_query,
)


QUERIES = [
    "\u0627\u064a\u0634 \u0627\u0644\u062a\u062d\u0627\u0644\u064a\u0644 \u0627\u0644\u0645\u0643\u0645\u0644\u0629 \u0644\u0641\u064a\u062a\u0627\u0645\u064a\u0646 \u062f",
    "\u0648\u0634 \u0627\u0644\u062a\u062d\u0627\u0644\u064a\u0644 \u0627\u0644\u0645\u0643\u0645\u0644\u0629 \u0644\u0644\u062d\u062f\u064a\u062f",
    "\u0627\u064a\u0634 \u064a\u0637\u0644\u0628 \u0645\u0639 \u062a\u062d\u0644\u064a\u0644 TSH",
    "\u0627\u064a\u0634 \u0627\u0644\u0628\u062f\u064a\u0644 \u0644\u062a\u062d\u0644\u064a\u0644 ANA",
    "\u062a\u062d\u0644\u064a\u0644 \u0642\u0631\u064a\u0628 \u0645\u0646 HbA1c",
    "\u0628\u062f\u0644 \u062a\u062d\u0644\u064a\u0644 \u0627\u0644\u062d\u062f\u064a\u062f \u0627\u064a\u0634 \u0645\u0645\u0643\u0646 \u0627\u0633\u0648\u064a",
]


def main() -> None:
    records = [r for r in load_tests_business_records() if bool(r.get("is_active", True))]
    rows = []
    for query in QUERIES:
        query_norm = _norm(query)
        query_type = _detect_query_type(query_norm)
        query_enriched = _normalize_business_query_aliases(query_norm)
        ranked = _rank_target_candidates(query_enriched, records)
        top_record = ranked[0][1] if ranked else {}
        top_score = float(ranked[0][0]) if ranked else 0.0

        field = ""
        raw_field = None
        if query_type == "test_complementary_query":
            field = "complementary_tests"
            raw_field = top_record.get("complementary_tests")
        elif query_type == "test_alternative_query":
            field = "alternative_tests"
            raw_field = top_record.get("alternative_tests")

        result = resolve_tests_business_query(query)
        meta = dict(result.get("meta") or {})
        rows.append(
            {
                "query": query,
                "matched_query_type": query_type,
                "matched_test_record": {
                    "id": top_record.get("id", ""),
                    "test_name_ar": top_record.get("test_name_ar", ""),
                    "score": round(top_score, 4),
                },
                "source_file": "app/data/runtime/rag/tests_business_clean.jsonl",
                "output_field_used": field,
                "raw_field_value": raw_field,
                "final_result": {
                    "route": result.get("route"),
                    "query_type": meta.get("query_type"),
                    "matched_test_id": meta.get("matched_test_id"),
                    "matched_test_name": meta.get("matched_test_name"),
                    "answer_preview": str(result.get("answer") or "")[:220],
                },
            }
        )

    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
