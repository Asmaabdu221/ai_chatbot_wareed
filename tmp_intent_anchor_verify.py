from app.services.runtime.faq_resolver import resolve_faq

samples = [
    "عندكم استشاره طبيه بعد تطلع النتائج",
    "هل ترسلون النتيجه اونلاين",
    "هل في زياره منزليه",
]

for s in samples:
    r = resolve_faq(s)
    print(s, "=>", None if not r else (r.get("faq_id"), r.get("question")))
