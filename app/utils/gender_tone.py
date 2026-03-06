from __future__ import annotations


def guess_gender(name: str | None) -> str:
    """Conservative gender guesser: returns male/female/unknown."""
    if not name:
        return "unknown"

    value = str(name).strip()
    if not value:
        return "unknown"

    female_names = {
        "فاطمة",
        "سارة",
        "هند",
        "نورة",
        "ريم",
        "العنود",
        "أمل",
    }
    male_names = {
        "محمد",
        "أحمد",
        "عبدالله",
        "خالد",
        "سعود",
        "ناصر",
    }

    if value in female_names:
        return "female"
    if value in male_names:
        return "male"

    # Conservative suffix heuristic only for a tiny whitelist.
    female_suffix_whitelist = {
        "فاطمة",
        "أميرة",
        "جميلة",
        "مدينة",
        "رفيدة",
    }
    if value.endswith("ة") and value in female_suffix_whitelist:
        return "female"

    return "unknown"


def apply_gender_variant(text_male: str, text_female: str, text_neutral: str, gender: str) -> str:
    if gender == "female":
        return text_female
    if gender == "male":
        return text_male
    return text_neutral


def safe_clarify_message(contact_phone: str, gender: str = "unknown") -> str:
    text_male = (
        "ممكن توضح طلبك أكثر؟ ما قدرنا نفهم الرسالة بالشكل الكافي. "
        f"إذا تفضل، تواصل مع فريق مختبر وريد على الرقم: {contact_phone} ونساعدك مباشرة."
    )
    text_female = (
        "ممكن توضحين طلبك أكثر؟ ما قدرنا نفهم الرسالة بالشكل الكافي. "
        f"إذا تفضلين، تواصلي مع فريق مختبر وريد على الرقم: {contact_phone} ونساعدك مباشرة."
    )
    text_neutral = (
        "ممكن توضح طلبك أكثر؟ ما قدرنا نفهم الرسالة بالشكل الكافي. "
        f"إذا تفضل، تواصل مع فريق مختبر وريد على الرقم: {contact_phone} ونساعدك مباشرة."
    )
    return apply_gender_variant(text_male, text_female, text_neutral, gender)


if __name__ == "__main__":
    phone = "920003694"
    print("male:", safe_clarify_message(phone, "male"))
    print("female:", safe_clarify_message(phone, "female"))
    print("unknown:", safe_clarify_message(phone, "unknown"))
