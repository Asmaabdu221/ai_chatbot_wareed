import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi.testclient import TestClient
from app.main import app
import json

client = TestClient(app)

queries = [
    "ايش هي تحليل السكري",
    "هل تحليل السكري يحتاج صيام",
    "ماهو تحليل فيتامين د",
    "ايش هو تحليل الكالسيوم",
    "من مختبرات وريد الطبيه",
    "ايش هي مختبرات وريد"
]

results = []
for q in queries:
    response = client.post("/api/chat", json={
        "message": q,
        "include_knowledge": True
    })
    
    if response.status_code == 200:
        data = response.json()
        results.append({
            "query": q,
            "reply": data.get("reply"),
            "model": data.get("model")
        })
    else:
        results.append({
            "query": q,
            "error": response.text
        })

with open("C:/Users/PC/.gemini/antigravity/brain/3e574ada-7a8c-48c4-b052-1c87cf53d453/scratch/manual_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("WROTE RESULTS")
