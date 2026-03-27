# -*- coding: utf-8 -*-
import json
from app.services.runtime import results_engine as re

re.load_results_records.cache_clear()
records=re.load_results_records()
queries=[
    "Vitamin D 10",
    "Vitamin D 50",
    "نتيجتي فيتامين د 12",
]
for q in queries:
    rec=re._match_record(q,records)
    print('INPUT:', q)
    if not rec:
        print('MATCHED: None')
    else:
        out={k:rec.get(k) for k in ['test_name','aliases','reference_type','min_value','max_value','rules','ai_ready_level']}
        print(json.dumps(out,ensure_ascii=False))
    print('---')
