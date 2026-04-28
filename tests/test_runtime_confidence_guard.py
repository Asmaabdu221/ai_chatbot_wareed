from app.services.runtime.results_query_detector import analyze_result_query
from app.services.runtime.runtime_router import _confidence_guard_clarification


def test_confidence_guard_for_unclear_test_query():
    guard = _confidence_guard_clarification(
        text="فيتامين",
        is_numeric=False,
        is_branch_like=False,
        is_package_like=False,
        is_tests_like=True,
        is_symptoms_like=False,
        result_analysis=analyze_result_query("فيتامين"),
    )
    assert guard is not None
    assert guard[0] == "tests_confidence_guard"


def test_confidence_guard_for_unclear_symptoms_query():
    guard = _confidence_guard_clarification(
        text="عندي تعب",
        is_numeric=False,
        is_branch_like=False,
        is_package_like=False,
        is_tests_like=False,
        is_symptoms_like=True,
        result_analysis=analyze_result_query("عندي تعب"),
    )
    assert guard is not None
    assert guard[0] == "symptoms_confidence_guard"


def test_confidence_guard_for_result_query_missing_value_or_test():
    query = "هل النتيجة طبيعية"
    guard = _confidence_guard_clarification(
        text=query,
        is_numeric=False,
        is_branch_like=False,
        is_package_like=False,
        is_tests_like=False,
        is_symptoms_like=False,
        result_analysis=analyze_result_query(query),
    )
    assert guard is not None
    assert guard[0] == "results_confidence_guard"
