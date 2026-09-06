from pathlib import Path
from unittest.mock import Mock, patch

from jobbot.production import PRODUCTION_VERSION
from scripts import telegram_notify

ROOT = Path(__file__).resolve().parents[1]


def test_v179_production_version():
    assert PRODUCTION_VERSION == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"


def test_telegram_diagnostic_workflow_uses_exact_production_notifier():
    text = (ROOT / ".github" / "workflows" / "telegram-diagnostic.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}" in text
    assert "TELEGRAM_CHAT_IDS: ${{ secrets.TELEGRAM_CHAT_IDS }}" in text
    assert "python scripts/telegram_notify.py --check --send-test" in text


def test_production_preflight_runs_before_expensive_collection():
    text = (ROOT / ".github" / "workflows" / "production-job-search.yml").read_text(encoding="utf-8")
    preflight = text.index("Verify Telegram configuration")
    collection = text.index("Run all production sources")
    assert preflight < collection
    assert "python scripts/telegram_notify.py --check" in text


def test_check_configuration_validates_bot_and_each_chat_without_leaking_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "111; 222")

    calls = []

    def fake_post(method, **kwargs):
        calls.append((method, kwargs))
        if method == "getMe":
            return {"ok": True, "result": {"username": "job_search_test_bot"}}
        return {"ok": True, "result": {}}

    with patch.object(telegram_notify, "_post", side_effect=fake_post):
        result = telegram_notify.check_configuration(send_test=False)

    assert result == {
        "ok": True,
        "bot_username": "job_search_test_bot",
        "chat_count": 2,
        "test_message_sent": False,
    }
    assert [name for name, _ in calls] == ["getMe", "getChat", "getChat"]


def test_check_configuration_send_test_messages(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_IDS", "111,222")
    with patch.object(telegram_notify, "_post", return_value={"ok": True, "result": {}}) as post:
        result = telegram_notify.check_configuration(send_test=True)
    assert result["chat_count"] == 2
    assert result["test_message_sent"] is True
    methods = [call.args[0] for call in post.call_args_list]
    assert methods == ["getMe", "getChat", "sendMessage", "getChat", "sendMessage"]
