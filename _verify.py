content = open("app/services/message_service.py", encoding="utf-8").read()

paths = [
    "PATH=greeting", "PATH=faq", "PATH=price", "PATH=branches", "PATH=packages",
    "PATH=test_definition", "PATH=test_preparation", "PATH=test_symptoms",
    "PATH=site_fallback", "PATH=clarify",
]
print("=== PATH logs ===")
for p in paths:
    needle = 'print("' + p
    pos = content.find(needle)
    if pos == -1:
        print(f"  MISSING  {p}")
    else:
        line_no = content[:pos].count("\n") + 1
        print(f"  OK  line {line_no:4d}  {p}")

split = "history = get_conversation_history_for_ai"
idx = content.rfind(split)
tail = content[idx:]

print("\n=== Banned legacy items in routing tail ===")
banned = [
    "route_question(",
    "pending_price_contact_fallback",
    "PATH=runtime_rag tests",
    "PATH=runtime_lookup faq",
    "symptom_based_suggestion",
    "_greeting_reply()",
]
for b in banned:
    present = b in tail
    status = "STILL PRESENT (check!)" if present else "absent (good)"
    print(f"  {status:30s}  {b!r}")

print(f"\nTotal lines: {content.count(chr(10))}")
