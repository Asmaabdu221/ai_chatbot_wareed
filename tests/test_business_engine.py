import os
import sys
import logging

logging.basicConfig(level=logging.DEBUG)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.runtime.tests_business_engine import _detect_query_type, _score_query_type, _PREPARATION_HINTS

print("SCORE PREP:", _score_query_type("ايش هي تحليل السكري", _PREPARATION_HINTS, ("تحضير", "استعداد", "لازم", "قبل")))
result = _detect_query_type("ايش هي تحليل السكري")
print("DETECT TYPE:", result)
