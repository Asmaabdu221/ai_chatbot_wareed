import json
from pathlib import Path
p=Path('app/data/runtime/rag/results_clean.jsonl')
count=0
for l in p.open('r',encoding='utf-8'):
    if l.strip():
        json.loads(l)
        count+=1
print(count)
