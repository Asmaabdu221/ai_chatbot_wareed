"""Safe runtime fallback messages for rebuild and FAQ-only phases."""

from __future__ import annotations


def get_rebuild_mode_message() -> str:
    """Return a concise message for full system rebuild mode."""
    return "المساعد حالياً في مرحلة تحسين وإعادة بناء، وسيكون متاحاً بالكامل قريباً."


def get_faq_no_match_message() -> str:
    """Return a safe fallback message when FAQ-only mode cannot find a match."""
    return (
        "حالياً أقدر أساعدك فقط في الأسئلة العامة الخاصة بالمختبر. "
        "ممكن تعيد صياغة سؤالك بشكل أوضح؟ "
        "مثال: هل يحتاج صيام؟ هل فيه سحب منزلي؟ كيف أستلم النتيجة؟"
    )


if __name__ == "__main__":
    print("REBUILD MODE MESSAGE:")
    print(get_rebuild_mode_message())
    print("-" * 48)
    print("FAQ NO-MATCH MESSAGE:")
    print(get_faq_no_match_message())
