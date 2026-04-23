import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.runtime.tests_resolver import resolve_tests_query

result = resolve_tests_query("ايش هي تحليل السكري")
with open("C:/Users/PC/.gemini/antigravity/brain/3e574ada-7a8c-48c4-b052-1c87cf53d453/scratch/resolver_result.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False)
