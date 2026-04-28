from app.services.runtime.runtime_router import route_runtime_message


def _route(text: str) -> str:
    result = route_runtime_message(text, faq_only_runtime_mode=True)
    return str(result.get("route") or "")


def test_faq_priority_children_suitability():
    route = _route("هل التحاليل مناسبه للاطفال")
    assert route.startswith("faq_") or route == "faq_only"


def test_faq_priority_home_visit():
    route = _route("هل عندكم زيارة منزلية")
    assert route.startswith("faq_") or route == "faq_only"


def test_faq_priority_services():
    route = _route("ايش خدماتكم")
    assert route.startswith("faq_") or route == "faq_only"


def test_results_tsh_numeric_pattern():
    route = _route("TSH 5.5")
    assert route == "results_interpretation"


def test_results_vitamin_d_numeric_pattern():
    route = _route("Vitamin D 10")
    assert route == "results_interpretation"


def test_symptoms_query():
    route = _route("عندي تعب")
    assert route in {"symptoms_suggestions", "symptoms_clarification"}


def test_packages_query():
    route = _route("ايش الباقات")
    assert route.startswith("packages")
