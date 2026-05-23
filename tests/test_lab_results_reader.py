"""
Offline tests for the uploaded lab-results reader (Feature 1).

Exercise candidate parsing, SynonymRetriever matching, three-state
availability, and the formatted reply (disclaimer + lead CTA). Skips when the
rebuilt workbook is unavailable, like the rest of the offline suite.
"""

from __future__ import annotations

import pytest

from app.data.lab_data_loader import DEFAULT_EXCEL
from app.services.lab_results_reader import read_lab_results_from_text, OCR_UNREADABLE_MSG

pytestmark = pytest.mark.skipif(not DEFAULT_EXCEL.exists(), reason="workbook not found")


def test_empty_or_blank_returns_none():
    assert read_lab_results_from_text("") is None
    assert read_lab_results_from_text("   \n  ") is None


def test_non_lab_text_returns_none():
    # No recognisable test names -> let the existing pipeline handle it.
    assert read_lab_results_from_text("Grocery receipt total 50 SAR thank you") is None


def test_matched_reply_has_header_disclaimer_and_cta():
    out = read_lab_results_from_text("CBC\nTSH\nCA 125")
    assert out is not None
    assert "وجدت هذي التحاليل" in out          # header
    assert "هذي معلومات إرشادية عامة" in out    # disclaimer
    assert "اكتب رقم جوالك" in out              # lead CTA
    assert ("✅" in out) or ("⚠️" in out)        # at least one status marker


def test_three_state_markers_present():
    # CA 125 is is_available=Yes -> ✅ ; CBC is NEEDS_REVIEW -> ⚠️
    out = read_lab_results_from_text("CA 125\nCBC")
    assert out is not None
    assert "✅" in out
    assert "⚠️" in out


def test_header_and_noise_lines_excluded():
    out = read_lab_results_from_text("Laboratory Report\nPatient Name: Ahmad\nDate: 2026-05-01\nCBC")
    assert out is not None
    # header/PII lines must not appear as ❌ rows
    assert "Laboratory Report" not in out
    assert "Patient" not in out
