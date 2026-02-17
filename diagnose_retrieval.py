"""Diagnose RAG retrieval for user queries (sleep, mood, stomach, vitamin D)"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    from app.data.rag_pipeline import retrieve, DEFAULT_SIMILARITY_THRESHOLD

    queries = [
        "عندي اضطرابات بالنوم و تغير بالمزاج ايش التحاليل اللي ممكن اسويها",
        "عندي الالم بالمعده ماهي التحاليل اللي ممكن اسويها",
        "عندكم تحاليل فيتامين د",
    ]

    for q in queries:
        results, has_suff = retrieve(q, max_results=5, similarity_threshold=0.0)
        at_075 = any(r["score"] >= 0.75 for r in results)
        lex = any(r.get("source") == "lexical" for r in results)
        print(f"Query: {q[:55]}...")
        print(f"  has_sufficient@0.75: {at_075}, lexical_in_results: {lex}")
        for i, r in enumerate(results[:3], 1):
            name = r["test"].get("analysis_name_ar", "")[:50]
            src = r.get("source", "?")
            print(f"  {i}. [{r['score']:.3f}] {name} ({src})")
        print()

if __name__ == "__main__":
    main()
