from uuid import uuid4

from app.services import message_service as m


def esc(text: str) -> str:
    return str(text).encode("unicode_escape").decode("ascii")


faq_queries = [
    "\u0647\u0644 \u0644\u062f\u064a\u0643\u0645 \u062e\u062f\u0645\u0629 \u0645\u0646\u0632\u0644\u064a\u0629\u061f",
    "\u0643\u064a\u0641 \u0623\u0633\u062a\u0644\u0645 \u0627\u0644\u0646\u062a\u0627\u0626\u062c\u061f",
    "\u0647\u0644 \u0627\u0644\u0646\u062a\u0627\u0626\u062c \u0633\u0631\u064a\u0629\u061f",
]

print("FAQ probes")
for q in faq_queries:
    match = m._runtime_faq_lookup(q)
    pkg = m._package_lookup_bypass_reply(q, uuid4())
    print("Q:", esc(q))
    print("  faq_match:", bool(match), (match or {}).get("id"), (match or {}).get("_match_method"))
    print("  package_reply:", bool(pkg))

print("Package probe")
package_q = "\u062a\u062d\u0644\u064a\u0644 \u0645\u0639\u062f\u0644 \u0627\u0644\u0628\u0631\u0648\u062a\u064a\u0646\u0627\u062a \u0627\u0644\u062c\u0632\u0626\u064a \u0641\u064a \u0627\u0644\u062f\u0645"
package_reply = m._package_lookup_bypass_reply(package_q, uuid4())
print("Q:", esc(package_q))
print("  package_reply:", bool(package_reply))
if package_reply:
    print("  package_head:", esc(package_reply[:120]))

package_positive_q = "\u0628\u0627\u0642\u0629"
package_positive_reply = m._package_lookup_bypass_reply(package_positive_q, uuid4())
print("Q:", esc(package_positive_q))
print("  package_reply:", bool(package_positive_reply))
if package_positive_reply:
    print("  package_head:", esc(package_positive_reply[:120]))

print("Mojibake probe")
sample = {
    "name_raw": "\u0628\u0627\u0642\u0629 \u062a\u062c\u0631\u064a\u0628\u064a\u0629",
    "price_raw": "50 \u0631\u064a\u0627\u0644",
    "description_raw": "\u062a\u0641\u0627\u0635\u064a\u0644 \u0628\u0627\u0642\u0629 \u062a\u062c\u0631\u064a\u0628\u064a\u0629",
    "turnaround_text": "",
    "sample_type_text": "",
}
formatted = m._format_package_details_strict(sample)
head = "\n".join(formatted.splitlines()[:3])
print("  has_mojibake_label:", "\u00d8\u00a7\u00d9\u201e\u00d8\u00b3\u00d8\u00b9\u00d8\u00b1" in head)
print("  head:", esc(head))
