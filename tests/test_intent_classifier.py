import pytest

from app.services.question_router import classify_intent, route, INTENT_CATEGORIES


CASES = [
    ("السلام عليكم", "greeting"), ("مرحبا", "greeting"), ("هلا", "greeting"),
    ("ايش خدماتكم المتوفرة", "services_overview"), ("وش تقدمون", "services_overview"), ("what services do you provide", "services_overview"),
    ("هل تحليل HbA1c متوفر؟", "test_availability"), ("عندكم تحليل فيتامين د؟", "test_availability"), ("is cbc available", "test_availability"),
    ("ما هو تحليل CBC", "test_definition"), ("وش معنى فحص TSH", "test_definition"), ("يعني ايش تحليل ferritin", "test_definition"),
    ("هل يحتاج صيام تحليل الدهون", "test_preparation"), ("طريقة التحضير قبل تحليل السكر", "test_preparation"), ("preparation for lipid profile", "test_preparation"),
    ("نوع العينة لتحليل فيتامين د", "sample_type"), ("تحليل ferritin دم او بول", "sample_type"), ("what sample for hba1c", "sample_type"),
    ("كم سعر تحليل فيتامين د", "pricing_inquiry"), ("وش تكلفة فحص CBC", "pricing_inquiry"), ("price of tsh test", "pricing_inquiry"),
    ("أبغى أعرف الباقات", "packages_inquiry"), ("ما هي باقات وريد", "packages_inquiry"), ("packages available", "packages_inquiry"),
    ("فيه عروض اليوم", "offers_discounts"), ("هل فيه خصم", "offers_discounts"), ("any discount offer", "offers_discounts"),
    ("وين فرع الرياض", "branches_locations"), ("موقعكم في جدة", "branches_locations"), ("branch location", "branches_locations"),
    ("متى تفتحون", "working_hours"), ("ساعات الدوام", "working_hours"), ("وقت الدوام اليوم", "working_hours"),
    ("رقم خدمة العملاء", "contact_support"), ("ابي اتواصل معكم", "contact_support"), ("contact number", "contact_support"),
    ("عندكم زيارة منزلية", "home_visit"), ("ابي سحب منزلي", "home_visit"), ("home visit available", "home_visit"),
    ("أبغى حجز موعد", "booking_appointment"), ("كيف احجز", "booking_appointment"), ("book appointment", "booking_appointment"),
    ("اشرح التحاليل", "report_explanation"), ("فسر النتائج", "report_explanation"), ("وش معنى النتيجة", "report_explanation"),
    ("أرغب برفع صورة أو ملف تحليل/وصفة طبية.", "upload_report_guidance"), ("رفع ملف pdf", "upload_report_guidance"), ("ارفق صورة وصفة", "upload_report_guidance"),
    ("عندي تساقط شعر وش أسوي", "symptom_based_suggestion"), ("اعاني من دوخة وخمول", "symptom_based_suggestion"), ("i have fatigue symptoms", "symptom_based_suggestion"),
    ("هل تقبلون التأمين", "payment_insurance_privacy"), ("طرق الدفع المتاحة", "payment_insurance_privacy"), ("سياسة الخصوصية للبيانات", "payment_insurance_privacy"),
]


@pytest.mark.parametrize("message,expected_intent", CASES)
def test_intent_classification_18_categories(message, expected_intent):
    payload = classify_intent(message)
    assert payload["intent"] == expected_intent
    assert payload["intent"] in INTENT_CATEGORIES
    assert 0 <= payload["confidence"] <= 1
    assert isinstance(payload["slots"], dict)


@pytest.mark.parametrize(
    "message",
    ["ساعات الدوام", "الدوام", "متى تفتحون", "متى تقفلون", "وقت الدوام"],
)
def test_hours_keywords_route_to_working_hours(message):
    route_type, fixed = route(message)
    assert route_type == "working_hours"
    assert isinstance(fixed, str)
    assert fixed.strip() != ""


@pytest.mark.parametrize(
    "message,expected_intent,expected_code",
    [
        ("عندكم HbA1c؟", "test_availability", "HBA1C"),
        ("وش معنى تحليل CEA؟", "test_definition", "CEA"),
        ("وش معنى التحليل هذا CEA؟", "test_definition", "CEA"),
        ("شرح تحليل TSH", "test_definition", "TSH"),
        ("هل CBC متوفر؟", "test_availability", "CBC"),
    ],
)
def test_short_code_queries_detect_intent_and_slots(message, expected_intent, expected_code):
    payload = classify_intent(message)
    assert payload["intent"] == expected_intent
    assert payload["needs_clarification"] is False
    assert str(payload["slots"].get("analysis_name", "")).upper() == expected_code
