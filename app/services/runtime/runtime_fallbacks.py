"""Safe runtime fallback messages for rebuild and staged runtime phases."""

from __future__ import annotations


def get_guided_examples() -> tuple[str, ...]:
    """Return short example questions to guide the user."""
    return (
        "هل يحتاج صيام؟",
        "هل فيه سحب منزلي؟",
        "كيف أستلم النتيجة؟",
    )


def _format_examples_inline() -> str:
    """Return guided examples as one readable inline string."""
    return "، ".join(get_guided_examples())


def get_rebuild_mode_message() -> str:
    """Return a concise message for full system rebuild mode."""
    return "المساعد حالياً تحت التحديث والتحسين، وسيكون متاحًا بشكل كامل قريبًا."


def get_faq_no_match_message() -> str:
    """Return a safe fallback when FAQ-only mode cannot find a confident match."""
    return (
        "ما فهمت سؤالك بشكل كافٍ ضمن الأسئلة العامة الحالية للمختبر. "
        f"جرب تكتب سؤالك بشكل أوضح، مثل: {_format_examples_inline()}"
    )


def get_out_of_scope_message() -> str:
    """Return a safe message when the question is outside the enabled runtime scope."""
    return (
        "هذا النوع من الأسئلة غير مفعّل بعد في النسخة الحالية. "
        "حالياً أقدر أساعدك فقط في الأسئلة العامة الخاصة بالمختبر."
    )


def get_branch_not_enabled_message() -> str:
    """Return a safe message for branch-specific questions before branches layer is enabled."""
    return (
        "تفاصيل الفروع والمواقع الدقيقة ما زالت غير مفعّلة بعد. "
        "حالياً أقدر أساعدك فقط في السؤال العام عن وجود الفروع."
    )


def get_prices_not_enabled_message() -> str:
    """Return a safe message for price questions before prices layer is enabled."""
    return (
        "الاستفسار عن الأسعار لم يتم تفعيله بعد في هذه النسخة. "
        "حالياً أقدر أساعدك فقط في الأسئلة العامة الخاصة بالمختبر."
    )


if __name__ == "__main__":
    print("REBUILD MODE MESSAGE:")
    print(get_rebuild_mode_message())
    print("-" * 48)

    print("FAQ NO-MATCH MESSAGE:")
    print(get_faq_no_match_message())
    print("-" * 48)

    print("OUT OF SCOPE MESSAGE:")
    print(get_out_of_scope_message())
    print("-" * 48)

    print("BRANCH NOT ENABLED MESSAGE:")
    print(get_branch_not_enabled_message())
    print("-" * 48)

    print("PRICES NOT ENABLED MESSAGE:")
    print(get_prices_not_enabled_message())
