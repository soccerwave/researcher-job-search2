from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from jobbot.production import PRODUCTION_VERSION
from scripts import telegram_notify

ROOT = Path(__file__).resolve().parents[1]


def test_v184_production_version():
    assert PRODUCTION_VERSION == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"


def test_production_preflight_allows_only_transient_telegram_unavailability():
    text = (ROOT / ".github" / "workflows" / "production-job-search.yml").read_text(encoding="utf-8")
    assert "python scripts/telegram_notify.py --check --allow-transient-unavailable" in text


def test_post_retries_connection_reset_then_succeeds(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    response = Mock(status_code=200, headers={})
    response.json.return_value = {"ok": True, "result": {"username": "bot"}}
    with patch.object(
        telegram_notify.requests,
        "post",
        side_effect=[requests.ConnectionError("reset"), response],
    ) as post, patch.object(telegram_notify.time, "sleep") as sleep:
        result = telegram_notify._post("getMe")
    assert result["ok"] is True
    assert post.call_count == 2
    sleep.assert_called_once()


def test_soft_check_does_not_block_on_transient_network_failure(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "111,222")
    with patch.object(
        telegram_notify,
        "_post",
        side_effect=telegram_notify.TelegramTransientError("temporary reset"),
    ):
        result = telegram_notify.check_configuration(allow_transient_unavailable=True)
    assert result == {
        "ok": False,
        "transient_unavailable": True,
        "warning": "temporary reset",
        "chat_count": 2,
        "test_message_sent": False,
    }


def test_soft_check_still_fails_on_permanent_telegram_error(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bad-token")
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "111")
    with patch.object(
        telegram_notify,
        "_post",
        side_effect=telegram_notify.TelegramPermanentError("HTTP 401"),
    ), pytest.raises(telegram_notify.TelegramPermanentError, match="401"):
        telegram_notify.check_configuration(allow_transient_unavailable=True)
