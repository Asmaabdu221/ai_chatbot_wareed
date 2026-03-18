from app.services.runtime.faq_resolver import resolve_faq

samples = [
    ("وش الخدمات اللي عندكم", "faq::1"),
    ("متى تطلع نتيجتي", "faq::3"),
    ("هل التراكمي يحتاج صيام", "faq::16"),
    ("هل احد يقدر يشوف نتيجتي", "faq::13"),
    ("كيف اقدر ادفع", "faq::7"),
    ("وين فروعكم", "faq::10"),
    ("وين اقرب فرع بالرياض", None),
]

print("=== ACCEPTANCE ===")
for q, expected in samples:
    r = resolve_faq(q)
    got = (r or {}).get("faq_id")
    via = (r or {}).get("matched_via")
    print(f"{q} => got={got} expected={expected} via={via}")

print("=== FOLLOWUP HbA1c -> fasting ===")
history1 = [
    {"role": "user", "content": "ما هو رمز السكر التراكمي"},
    {"role": "assistant", "content": "رمز تحليل السكر التراكمي هو HbA1c"},
]
r1 = resolve_faq("هل يحتاج صيام؟", recent_runtime_messages=history1)
print("هل يحتاج صيام؟ =>", (r1 or {}).get("faq_id"), (r1 or {}).get("matched_via"))

print("=== FOLLOWUP children -> elderly ===")
history2 = [
    {"role": "user", "content": "هل التحاليل آمنة للأطفال؟"},
    {"role": "assistant", "content": "نعم، التحاليل آمنة للأطفال وكبار السن."},
]
r2 = resolve_faq("ولكبار السن؟", recent_runtime_messages=history2)
print("ولكبار السن؟ =>", (r2 or {}).get("faq_id"), (r2 or {}).get("matched_via"))
