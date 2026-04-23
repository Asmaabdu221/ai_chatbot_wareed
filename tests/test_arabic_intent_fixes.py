import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.question_router import _heuristic_intent
from app.services.message_service import _format_compact_test_fallback_reply

def test_intent_classification():
    queries = [
        "ايش هي تحليل السكري",
        "وش هو تحليل السكري",
        "شنو هي تحليل السكري",
        "ماهو تحليل فيتامين د",
        "وش معنى تحليل الحديد",
        "ابي اعرف تحليل الغدة",
        "معلومات عن فحص الزواج"
    ]
    
    for q in queries:
        intent, score = _heuristic_intent(q)
        print(f"Query: '{q}' -> Intent: {intent} (Score: {score})")
        assert intent == "test_definition", f"Expected test_definition, got {intent} for '{q}'"

def test_fallback_logic():
    # Test 1: Both desc and prep present
    res = _format_compact_test_fallback_reply("ماهو تحليل السكري", [{"test": {"analysis_name_ar": "السكري", "description": "يقيس السكر", "preparation": "صيام 8 ساعات"}}])
    print(f"Test 1 Fallback: {res}")
    assert "يقيس السكر" in res

    # Test 2: Only prep present
    res2 = _format_compact_test_fallback_reply("ماهو تحليل السكري", [{"test": {"analysis_name_ar": "السكري", "preparation": "صيام 8 ساعات"}}])
    print(f"Test 2 Fallback: {res2}")
    assert "عذراً، الوصف الدقيق غير متوفر" in res2
    assert "صيام 8 ساعات" in res2
    
    # Test 3: Neither present
    res3 = _format_compact_test_fallback_reply("ماهو تحليل فيتامين د", [{"test": {"analysis_name_ar": "فيتامين د"}}])
    print(f"Test 3 Fallback: {res3}")
    assert "عذراً، الوصف الدقيق غير متوفر" in res3

if __name__ == "__main__":
    test_intent_classification()
    test_fallback_logic()
    print("ALL TESTS PASSED")
