from app.services.runtime.faq_followup_rewriter import rewrite_faq_query
from app.services.runtime.faq_resolver import resolve_faq


def show(label: str, result):
    if not result:
        print(label, "=>", None)
        return
    print(label, "=>", result.get("faq_id"), "|", result.get("question"))


history_hba1c = [
    {"role": "user", "content": "ما هو رمز السكر التراكمي"},
    {"role": "assistant", "content": "رمز تحليل السكر التراكمي هو HbA1c"},
]
show("hba1c fasting", resolve_faq("هل يحتاج صيام؟", recent_runtime_messages=history_hba1c))
show("duration override", resolve_faq("طيب كم مدته؟", recent_runtime_messages=history_hba1c))
r1 = rewrite_faq_query("طيب كم مدته؟", recent_runtime_messages=history_hba1c)
print("rewrite duration:", r1.intent_hint, r1.intent_source, r1.rewritten_query)

history_safety = [
    {"role": "user", "content": "هل التحاليل آمنة للأطفال؟"},
    {"role": "assistant", "content": "نعم، التحاليل آمنة للأطفال وكبار السن."},
]
show("safety followup", resolve_faq("ولكبار السن؟", recent_runtime_messages=history_safety))

history_privacy = [
    {"role": "user", "content": "هل نتائجي سرية؟"},
    {"role": "assistant", "content": "نعم، النتائج سرية."},
]
show("privacy followup", resolve_faq("يعني محد يقدر يشوفها؟", recent_runtime_messages=history_privacy))
r2 = rewrite_faq_query("يعني محد يقدر يشوفها؟", recent_runtime_messages=history_privacy)
print("rewrite privacy:", r2.intent_hint, r2.intent_source, r2.rewritten_query)
