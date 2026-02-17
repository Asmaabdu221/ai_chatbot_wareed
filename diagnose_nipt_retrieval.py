"""
NIPT Retrieval Diagnostic Script
================================
Run to get actual similarity scores for NIPT queries.
Usage: python diagnose_nipt_retrieval.py
Output: diagnose_nipt_results.txt
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "diagnose_nipt_results.txt")

def main():
    from app.data.rag_pipeline import load_rag_knowledge, load_embeddings, retrieve, DEFAULT_SIMILARITY_THRESHOLD
    
    queries = [
        "Do you have NIPT test?",
        "هل لديكم تحليل nipt",
        "هل لديكم تحليل NIPT",
        "NIPT",
        "nipt",
        "الفحص قبل الولادة غير الغازي",
        "Noninvasive prenatal testing",
    ]
    
    lines = []
    lines.append("=" * 70)
    lines.append("NIPT Retrieval Diagnostic")
    lines.append("=" * 70)
    lines.append(f"Similarity threshold: {DEFAULT_SIMILARITY_THRESHOLD}")
    lines.append("")
    
    tests, _ = load_rag_knowledge()
    emb_data = load_embeddings()
    if not emb_data:
        lines.append("ERROR: No embeddings found")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return
    
    nipt_indices = []
    for i, t in enumerate(tests):
        ar = (t.get("analysis_name_ar") or "").lower()
        en = (t.get("analysis_name_en") or "").lower()
        if "nipt" in ar or "nipt" in en or "الولادة غير الغازي" in (t.get("analysis_name_ar") or ""):
            nipt_indices.append((i, t.get("analysis_name_ar"), t.get("analysis_name_en")))
    
    lines.append(f"NIPT-related tests in KB: {len(nipt_indices)}")
    for idx, ar, en in nipt_indices:
        lines.append(f"  [{idx}] {ar} | {en}")
    lines.append("")
    
    for query in queries:
        lines.append("-" * 70)
        lines.append(f'Query: "{query}"')
        lines.append("-" * 70)
        
        results, has_sufficient = retrieve(
            query,
            max_results=10,
            similarity_threshold=0.0,
        )
        
        # Re-check at 0.75
        has_at_075 = any(r["score"] >= 0.75 for r in results)
        lines.append(f"has_sufficient at 0.75: {has_at_075}")
        lines.append("")
        lines.append("Top 10 results (scores):")
        for j, r in enumerate(results, 1):
            name_ar = r["test"].get("analysis_name_ar", "")
            name_en = r["test"].get("analysis_name_en", "")
            score = r["score"]
            is_nipt = "nipt" in (name_en or "").lower()
            marker = " <-- NIPT" if is_nipt else ""
            lines.append(f"  {j}. [{score:.4f}] {name_ar[:60]} | {name_en[:40]} {marker}")
        
        nipt_in_top = any(
            "nipt" in (r["test"].get("analysis_name_en") or "").lower()
            for r in results[:5]
        )
        lines.append(f"NIPT in top 5: {nipt_in_top}")
        lines.append("")
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Results written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
