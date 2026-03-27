import json
import re
import sys
import time
from pathlib import Path

p = Path("app/data/runtime/rag/results_clean.jsonl")
rows = [json.loads(l) for l in p.open("r", encoding="utf-8") if l.strip()]
print("rows", len(rows))
sys.stdout.flush()

QUAL = [
    "negative",
    "positive",
    "non reactive",
    "reactive",
    "nil",
    "normal",
    "abnormal",
    "trace",
    "clear",
    "brown",
    "present",
    "absent",
    "سلبي",
    "ايجابي",
    "إيجابي",
    "غير تفاعلي",
    "تفاعلي",
    "طبيعي",
    "غير طبيعي",
    "موجود",
    "غير موجود",
    "شفاف",
    "بني",
]
OP_RE = re.compile(r"(<=|>=|<|>|=)")
NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


out = []
start = time.time()
for idx, o in enumerate(rows, start=1):
    if idx % 50 == 0:
        print("at", idx, "elapsed", time.time() - start)
        sys.stdout.flush()
    ref = str(o.get("reference_type") or "").strip().lower()
    rules = o.get("rules") if isinstance(o.get("rules"), list) else []
    structured = []
    qvals = []
    has_minmax = False
    has_threshold = False
    bands = 0
    has_text = False
    for r in rules:
        if isinstance(r, dict):
            structured.append(
                {
                    "label": r.get("label"),
                    "status": r.get("status"),
                    "operator": r.get("operator"),
                    "min": r.get("min"),
                    "max": r.get("max"),
                    "value": r.get("value"),
                }
            )
            if is_num(r.get("min")) or is_num(r.get("max")):
                has_minmax = True
                bands += 1
            if r.get("operator") in ("<", "<=", ">", ">=", "==", "=") and is_num(r.get("value")):
                has_threshold = True
                bands += 1
            for k in ("label", "status"):
                v = str(r.get(k) or "").strip().lower()
                if v in QUAL:
                    qvals.append(v)
        elif isinstance(r, str):
            has_text = True
            t = r.lower()
            for q in QUAL:
                if q in t:
                    qvals.append(q)

    q2 = []
    seen = set()
    for q in qvals:
        if q and q not in seen:
            seen.add(q)
            q2.append(q)
    minv = o.get("min_value")
    maxv = o.get("max_value")
    has_range = is_num(minv) or is_num(maxv)
    if q2 and not (has_range or has_minmax or has_threshold):
        mode = "qualitative"
    elif ref == "mixed" or bands >= 2:
        mode = "multi_band"
    elif has_threshold and not (has_range or has_minmax):
        mode = "threshold"
    elif has_range or has_minmax:
        mode = "numeric_range"
    elif ref == "text_reference" and has_text:
        blob = " ".join([x for x in rules if isinstance(x, str)]).lower()
        if any(q in blob for q in QUAL):
            mode = "qualitative"
        elif OP_RE.search(blob) or NUM_RE.search(blob):
            mode = "threshold"
        else:
            mode = "qualitative"
    else:
        mode = "qualitative"
    o["structured_rules"] = structured
    o["interpretation_mode"] = mode
    o["qualitative_values"] = q2
    out.append(o)

print("processed", len(out), "elapsed", time.time() - start)
sys.stdout.flush()

with p.open("w", encoding="utf-8") as f:
    for i, o in enumerate(out, start=1):
        if i % 50 == 0:
            print("write", i, "elapsed", time.time() - start)
            sys.stdout.flush()
        f.write(json.dumps(o, ensure_ascii=False) + "\n")

print("done", time.time() - start)
