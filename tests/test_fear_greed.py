"""
Tests for bot/insights/fear_greed.py — Fear & Greed Index (CH5B).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from bot.insights.fear_greed import fetch_fear_greed_index, format_fear_greed_message


class TestFormatFearGreedMessage:
    """Pure-computation formatting tests — no I/O."""

    def _data(self, score: int, label: str, yesterday_score: int = 68,
              last_week_score: int = 45) -> dict:
        return {
            "current": {"value": score, "label": label},
            "yesterday": {"value": yesterday_score, "label": "GREED"},
            "last_week": {"value": last_week_score, "label": "FEAR"},
        }

    def test_contains_score(self):
        msg = format_fear_greed_message(self._data(72, "Greed"))
        assert "72" in msg

    def test_contains_label(self):
        msg = format_fear_greed_message(self._data(72, "Greed"))
        assert "Greed" in msg

    def test_greed_emoji_present(self):
        msg = format_fear_greed_message(self._data(72, "Greed"))
        assert "🟢" in msg

    def test_extreme_fear_emoji(self):
        msg = format_fear_greed_message(self._data(10, "Extreme Fear"))
        assert "🔴" in msg

    def test_extreme_greed_emoji(self):
        msg = format_fear_greed_message(self._data(90, "Extreme Greed"))
        assert "🟣" in msg

    def test_yesterday_in_output(self):
        msg = format_fear_greed_message(self._data(72, "Greed", yesterday_score=68))
        assert "Yesterday" in msg
        assert "68" in msg

    def test_last_week_in_output(self):
        msg = format_fear_greed_message(self._data(72, "Greed", last_week_score=45))
        assert "Last Week" in msg
        assert "45" in msg

    def test_extreme_greed_advice(self):
        msg = format_fear_greed_message(self._data(90, "Extreme Greed"))
        assert "Extreme greed" in msg or "stop-losses" in msg

    def test_extreme_fear_advice(self):
        msg = format_fear_greed_message(self._data(10, "Extreme Fear"))
        assert "fear" in msg.lower() or "buying" in msg.lower()

    def test_header_present(self):
        msg = format_fear_greed_message(self._data(50, "Neutral"))
        assert "FEAR" in msg.upper() and "GREED" in msg.upper()

    def test_no_yesterday_key(self):
        """When yesterday data is absent, message should still render."""
        data = {"current": {"value": 55, "label": "Greed"}}
        msg = format_fear_greed_message(data)
        assert "55" in msg
        assert "Yesterday" not in msg


class TestFetchFearGreedIndex:
    """Network-layer tests using mocked requests."""

    def _mock_response(self, body: list) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": body}
        mock_resp.raise_for_status.return_value = None
        return mock_resp

    def test_returns_current_score(self):
        body = [{"value": "72", "value_classification": "Greed"}]
        with patch("bot.insights.fear_greed.requests.get", return_value=self._mock_response(body)):
            result = fetch_fear_greed_index()
        assert result is not None
        assert result["current"]["value"] == 72
        assert result["current"]["label"] == "Greed"

    def test_returns_yesterday_when_available(self):
        body = [
            {"value": "72", "value_classification": "Greed"},
            {"value": "68", "value_classification": "Greed"},
        ]
        with patch("bot.insights.fear_greed.requests.get", return_value=self._mock_response(body)):
            result = fetch_fear_greed_index()
        assert "yesterday" in result
        assert result["yesterday"]["value"] == 68

    def test_returns_last_week_when_7_entries(self):
        body = [{"value": str(i * 10), "value_classification": "Greed"} for i in range(1, 8)]
        with patch("bot.insights.fear_greed.requests.get", return_value=self._mock_response(body)):
            result = fetch_fear_greed_index()
        assert "last_week" in result

    def test_returns_none_on_request_error(self):
        import requests as req_lib
        with patch("bot.insights.fear_greed.requests.get", side_effect=req_lib.RequestException("err")):
            result = fetch_fear_greed_index()
        assert result is None

    def test_returns_none_on_empty_body(self):
        with patch("bot.insights.fear_greed.requests.get", return_value=self._mock_response([])):
            result = fetch_fear_greed_index()
        assert result is None
