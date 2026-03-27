import json, subprocess
from pathlib import Path
from collections import Counter

sel=[1,2,3,38,66,143,144,183,192,475]
cur=[json.loads(l) for l in Path('app/data/runtime/rag/results_clean.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
old_txt=subprocess.check_output(['git','show','HEAD:app/data/runtime/rag/results_clean.jsonl'], text=True, encoding='utf-8', errors='replace')
old=[json.loads(l) for l in old_txt.splitlines() if l.strip()]

mode_counts=Counter(str(o.get('interpretation_mode') or '') for o in cur)
ref_counts=Counter(str(o.get('reference_type') or '') for o in cur)

print('MODE',dict(mode_counts))
print('REF',dict(ref_counts))
for i in sel:
    b=old[i-1]; a=cur[i-1]
    out={
      'line':i,
      'test_name':a.get('test_name'),
      'before':{
        'reference_type':b.get('reference_type'),
        'has_structured_rules':'structured_rules' in b,
        'has_interpretation_mode':'interpretation_mode' in b,
        'has_qualitative_values':'qualitative_values' in b,
      },
      'after':{
        'reference_type':a.get('reference_type'),
        'interpretation_mode':a.get('interpretation_mode'),
        'structured_rules_count':len(a.get('structured_rules') or []),
        'qualitative_values':a.get('qualitative_values') or [],
        'ai_ready_level':a.get('ai_ready_level'),
      }
    }
    print(json.dumps(out,ensure_ascii=False))
