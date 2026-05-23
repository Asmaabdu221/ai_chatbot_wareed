"""
Offline tests for the home-sampling (الزيارة المنزلية) city flow.

These exercise the pure decision logic in app.services.home_sampling and the
availability checker in app.data.home_sampling_cities. No Redis/DB/OpenAI is
required, matching the rest of the offline suite.
"""

from __future__ import annotations

import pytest

from app.services.home_sampling import (
    classify_city,
    resolve_city_reply,
    append_city_prompt,
    available_reply,
    CITY_PROMPT,
    UNAVAILABLE_REPLY,
    UNRECOGNIZED_REPLY,
)
from app.data.home_sampling_cities import check_city_availability


# ---- Test 1: served cities resolve as available -----------------------------
@pytest.mark.parametrize(
    "msg",
    ["الرياض", "رياض", "جدة", "جده", "مكه", "مكة المكرمة",
     "حفر الباطن", "حفر", "انا في الرياض", "ساكن في جدة"],
)
def test_available_cities(msg):
    outcome, name = classify_city(msg)
    assert outcome == "available", f"{msg!r} should be available, got {outcome}"
    assert name and not name.startswith("NEEDS")


# ---- Test 2: real-but-unserved cities resolve as unavailable -----------------
@pytest.mark.parametrize("msg", ["الخبر", "نيويورك", "تبوك", "ابها", "جيزان"])
def test_unavailable_cities(msg):
    outcome, _ = classify_city(msg)
    assert outcome == "unavailable", f"{msg!r} should be unavailable, got {outcome}"


def test_khobar_does_not_collide_with_kharj():
    """Regression: الخبر (not served) must NOT fuzzy-match الخرج (served)."""
    available, _ = check_city_availability("الخبر")
    assert available is False
    available_kharj, name = check_city_availability("الخرج")
    assert available_kharj is True and name == "الخرج"


# ---- Test 3: non-city input is unrecognized (stay in flow) -------------------
@pytest.mark.parametrize(
    "msg", ["مدري", "وش الخدمة", "كم سعر التحليل", "؟؟", "", "لا اعرف"]
)
def test_unrecognized_input(msg):
    outcome, _ = classify_city(msg)
    assert outcome == "unrecognized", f"{msg!r} should be unrecognized, got {outcome}"


# ---- Test 4: lead CTA gating (only when available) ---------------------------
def test_reply_cta_gating():
    # available -> success carries the phone CTA + the canonical city name
    outcome, reply = resolve_city_reply("الرياض")
    assert outcome == "available"
    assert "اكتب رقم جوالك" in reply
    assert "الرياض" in reply

    # unavailable -> apology + support number, NO phone CTA
    outcome, reply = resolve_city_reply("الخبر")
    assert outcome == "unavailable"
    assert "اكتب رقم جوالك" not in reply
    assert "8001221220" in reply
    assert reply == UNAVAILABLE_REPLY

    # unrecognized -> re-ask, NO phone CTA
    outcome, reply = resolve_city_reply("مدري")
    assert outcome == "unrecognized"
    assert "اكتب رقم جوالك" not in reply
    assert reply == UNRECOGNIZED_REPLY


# ---- Test 5: city prompt is appended to the home-visit answer ----------------
def test_append_city_prompt():
    base = "متوفر لدينا خدمة سحب العينات من المنزل."
    out = append_city_prompt(base)
    assert out.startswith(base)
    assert CITY_PROMPT in out
    # empty base falls back to just the prompt
    assert append_city_prompt("") == CITY_PROMPT
    # available_reply embeds the city name passed to it
    assert "الطائف" in available_reply("الطائف")
