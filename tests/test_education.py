"""Tests for bot/channels/education.py"""
from __future__ import annotations

from bot.channels.education import (
    GLOSSARY,
    LESSONS,
    PatternResult,
    detect_pattern_btc_4h,
    format_lesson_message,
    format_pattern_message,
    get_next_lesson,
    get_target_channel_id,
    lookup_glossary,
)

# ── Lesson rotation ───────────────────────────────────────────────────────────


class TestLessonRotation:
    def test_30_or_more_lessons_defined(self):
        assert len(LESSONS) >= 30

    def test_each_lesson_has_required_fields(self):
        for lesson in LESSONS:
            assert "title" in lesson
            assert "content" in lesson
            assert "category" in lesson

    def test_get_next_lesson_returns_dict(self):
        lesson = get_next_lesson()
        assert isinstance(lesson, dict)
        assert "title" in lesson

    def test_lesson_rotation_cycles(self):
        """After iterating all lessons, it wraps back to the start."""
        import bot.channels.education as edu_mod

        # Reset index to a known position near end
        start_index = len(LESSONS) - 1
        edu_mod._lesson_index = start_index
        _last = get_next_lesson()
        _first_again = get_next_lesson()
        assert edu_mod._lesson_index == 1  # wrapped

    def test_format_lesson_message_structure(self):
        lesson = LESSONS[0]
        msg = format_lesson_message(lesson, lesson_number=1)
        assert "TRADING LESSON #1" in msg
        assert lesson["title"] in msg
        assert lesson["content"] in msg
        assert lesson["category"] in msg

    def test_format_lesson_message_pro_tip(self):
        lesson = {
            "title": "Test Lesson",
            "content": "Test content",
            "category": "Test",
            "pro_tip": "A useful tip",
            "related": "Something",
        }
        msg = format_lesson_message(lesson, lesson_number=5)
        assert "Pro Tip" in msg
        assert "A useful tip" in msg
        assert "Related" in msg


# ── Glossary lookup ───────────────────────────────────────────────────────────


class TestGlossaryLookup:
    def test_20_or_more_terms(self):
        assert len(GLOSSARY) >= 20

    def test_fvg_defined(self):
        assert "FVG" in GLOSSARY

    def test_ob_defined(self):
        assert "OB" in GLOSSARY

    def test_mss_defined(self):
        assert "MSS" in GLOSSARY

    def test_bos_defined(self):
        assert "BOS" in GLOSSARY

    def test_lookup_existing_term(self):
        result = lookup_glossary("FVG")
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 10

    def test_lookup_lowercase(self):
        result = lookup_glossary("fvg")
        assert result is not None

    def test_lookup_with_spaces(self):
        result = lookup_glossary("  RSI  ")
        assert result is not None

    def test_lookup_unknown_term(self):
        result = lookup_glossary("NONEXISTENTTERM123")
        assert result is None


# ── Pattern detection ─────────────────────────────────────────────────────────


def _make_candles(n: int = 20, trend: str = "up", base: float = 100.0) -> list[dict]:
    """Generate simple candle data for testing."""
    candles = []
    for i in range(n):
        if trend == "up":
            o = base + i * 0.5
            c = o + 0.4
            h = c + 0.2
            lo = o - 0.1
        else:
            o = base - i * 0.5
            c = o - 0.4
            h = o + 0.1
            lo = c - 0.2
        candles.append({"open": o, "high": h, "low": lo, "close": c, "volume": 1000.0})
    return candles


class TestPatternDetection:
    def test_returns_pattern_result(self):
        candles = _make_candles(20)
        result = detect_pattern_btc_4h(candles)
        assert isinstance(result, PatternResult)
        assert result.name
        assert result.description

    def test_insufficient_candles(self):
        candles = _make_candles(5)
        result = detect_pattern_btc_4h(candles)
        assert result.name == "No Clear Pattern"

    def test_empty_candles(self):
        result = detect_pattern_btc_4h([])
        assert result.name == "No Clear Pattern"

    def test_bull_flag_detection(self):
        """Create candles that look like a bull flag: strong up-candle then tight range."""
        # Pole candle (large bullish)
        candles = []
        # Rising pole
        for i in range(10):
            o = 100.0 + i * 2
            c = o + 1.8
            candles.append({"open": o, "high": c + 0.2, "low": o - 0.1, "close": c, "volume": 1000.0})
        # Flag: tight range, slightly declining
        base = candles[-1]["close"]
        for j in range(10):
            o = base - j * 0.1
            c = o + 0.08
            candles.append({"open": o, "high": o + 0.15, "low": o - 0.1, "close": c, "volume": 800.0})

        result = detect_pattern_btc_4h(candles)
        assert isinstance(result, PatternResult)
        assert result.timeframe == "4H"

    def test_double_top_detection(self):
        """Candles forming a double top — two peaks at same level."""
        candles = []
        # First peak
        for i in range(5):
            o = 100.0 + i
            c = o + 0.5
            candles.append({"open": o, "high": c + 0.2, "low": o - 0.1, "close": c, "volume": 1000.0})
        # Dip
        for i in range(3):
            o = 103.0 - i * 0.5
            candles.append({"open": o, "high": o + 0.1, "low": o - 0.5, "close": o - 0.3, "volume": 800.0})
        # Second peak at same level
        for i in range(5):
            o = 101.5 + i * 0.5
            c = o + 0.4
            candles.append({"open": o, "high": c + 0.1, "low": o - 0.1, "close": c, "volume": 900.0})
        # Drop below
        for i in range(2):
            o = 103.5 - i
            candles.append({"open": o, "high": o + 0.1, "low": o - 1.5, "close": o - 1.2, "volume": 1200.0})

        result = detect_pattern_btc_4h(candles)
        assert isinstance(result, PatternResult)


# ── Pattern message format ────────────────────────────────────────────────────


class TestFormatPatternMessage:
    def test_format_contains_pattern_name(self):
        pattern = PatternResult(name="Bull Flag", description="Test description")
        msg = format_pattern_message(pattern)
        assert "Bull Flag" in msg
        assert "4H" in msg
        assert "Test description" in msg

    def test_format_no_clear_pattern(self):
        pattern = PatternResult(name="No Clear Pattern", description="Nothing detected")
        msg = format_pattern_message(pattern)
        assert "No Clear Pattern" in msg


# ── Channel ID guard ──────────────────────────────────────────────────────────


class TestGetTargetChannelId:
    def test_returns_int(self):
        cid = get_target_channel_id()
        assert isinstance(cid, int)
