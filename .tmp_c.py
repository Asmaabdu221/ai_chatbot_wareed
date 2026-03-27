import json,re
from pathlib import Path
from collections import Counter
p=Path('app/data/runtime/rag/results_clean.jsonl')
c=Counter()
for l in p.open('r',encoding='utf-8'):
 if not l.strip(): continue
 o=json.loads(l)
 c[str(o.get('reference_type') or '').strip().lower()]+=1
print(c)
