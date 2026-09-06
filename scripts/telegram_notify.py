from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import requests


class TelegramTransientError(RuntimeError):
    """Temporary Telegram/network failure that may succeed on retry."""


class TelegramPermanentError(RuntimeError):
    """Non-retryable Telegram configuration/API failure."""


def _chat_ids() -> list[str]:
    raw = str(os.environ.get("TELEGRAM_CHAT_IDS") or "")
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


def _token() -> str:
    return str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def format_summary(summary: dict) -> str:
    rec = summary.get("recommendations") or {}
    runs = summary.get("source_runs") or {}
    statuses = {"OK": 0, "PARTIAL": 0, "ERROR": 0}
    for item in runs.values():
        status = str(item.get("status") or "ERROR").upper()
        statuses[status if status in statuses else "ERROR"] += 1
    daily = int(summary.get("daily_actionable", 0) or 0)
    needs_detail_total = int(summary.get("needs_detail_review", 0) or 0)
    madrid_needs_detail = int((runs.get("madrid") or {}).get("needs_detail_review", 0) or 0)
    other_needs_detail = max(0, needs_detail_total - madrid_needs_detail)
    tail = "No new actionable opportunities today." if daily == 0 else f"Today's actionable opportunities: {daily}"
    return "\n".join([
        "✅ Job search completed",
        f"Date: {summary.get('availability_as_of', '')}",
        f"Current actionable: {summary.get('current_actionable', 0)}",
        f"New actionable: {summary.get('new_actionable', 0)}",
        f"Changed/reopened actionable: {summary.get('changed_or_reopened_actionable', 0)}",
        f"APPLY: {rec.get('APPLY', 0)} | REVIEW: {rec.get('REVIEW', 0)} | LOW: {rec.get('LOW_PRIORITY', 0)}",
        f"Needs detail: {needs_detail_total} | Madrid: {madrid_needs_detail} | Other: {other_needs_detail}",
        f"Sources: ✅ {statuses['OK']} | ⚠️ {statuses['PARTIAL']} | ❌ {statuses['ERROR']}",
        tail,
    ])


def _sleep_seconds(attempt: int, response: requests.Response | None = None) -> float:
    if response is not None:
        try:
            payload = response.json()
            retry_after = (payload.get("parameters") or {}).get("retry_after")
            if retry_after is not None:
                return min(30.0, max(1.0, float(retry_after)))
        except (ValueError, TypeError, AttributeError):
            pass
        header_retry = response.headers.get("Retry-After")
        if header_retry:
            try:
                return min(30.0, max(1.0, float(header_retry)))
            except ValueError:
                pass
    return min(8.0, float(2 ** (attempt - 1)))


def _safe_api_error(response: requests.Response, method: str) -> str:
    description = ""
    try:
        payload = response.json()
        description = str(payload.get("description") or "").strip()
    except ValueError:
        pass
    suffix = f": {description}" if description else ""
    return f"Telegram API HTTP {response.status_code} for {method}{suffix}"


def _post(method: str, *, max_attempts: int = 4, **kwargs):
    token = _token()
    if not token:
        raise TelegramPermanentError("TELEGRAM_BOT_TOKEN is missing")

    url = f"https://api.telegram.org/bot{token}/{method}"
    last_transient: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(url, timeout=(15, 60), **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_transient = exc
            if attempt >= max_attempts:
                raise TelegramTransientError(
                    f"Telegram network unavailable during {method} after {max_attempts} attempts: {type(exc).__name__}"
                ) from exc
            time.sleep(_sleep_seconds(attempt))
            continue

        if response.status_code == 429 or response.status_code >= 500:
            if attempt >= max_attempts:
                raise TelegramTransientError(
                    f"Telegram API temporarily unavailable during {method}: HTTP {response.status_code} after {max_attempts} attempts"
                )
            time.sleep(_sleep_seconds(attempt, response))
            continue

        if response.status_code >= 400:
            raise TelegramPermanentError(_safe_api_error(response, method))

        try:
            payload = response.json()
        except ValueError as exc:
            if attempt >= max_attempts:
                raise TelegramTransientError(
                    f"Telegram returned an invalid response during {method} after {max_attempts} attempts"
                ) from exc
            time.sleep(_sleep_seconds(attempt))
            continue

        if not payload.get("ok"):
            error_code = int(payload.get("error_code") or 0)
            if error_code == 429 or error_code >= 500:
                if attempt >= max_attempts:
                    raise TelegramTransientError(
                        f"Telegram API temporarily unavailable during {method}: error {error_code} after {max_attempts} attempts"
                    )
                time.sleep(_sleep_seconds(attempt, response))
                continue
            description = str(payload.get("description") or "Telegram API rejected the request")
            raise TelegramPermanentError(f"Telegram API error during {method}: {description}")

        return payload

    raise TelegramTransientError(
        f"Telegram network unavailable during {method}: {type(last_transient).__name__ if last_transient else 'unknown transient error'}"
    )


def check_configuration(*, send_test: bool = False, allow_transient_unavailable: bool = False) -> dict:
    chats = _chat_ids()
    if not _token():
        raise TelegramPermanentError("TELEGRAM_BOT_TOKEN is missing")
    if not chats:
        raise TelegramPermanentError("TELEGRAM_CHAT_IDS is missing")

    try:
        bot = _post("getMe")
        bot_info = bot.get("result") or {}
        for chat_id in chats:
            _post("getChat", data={"chat_id": chat_id})
            if send_test:
                _post(
                    "sendMessage",
                    data={
                        "chat_id": chat_id,
                        "text": "✅ Telegram diagnostic passed\nJob Search Bot can reach this chat.",
                    },
                )
    except TelegramTransientError as exc:
        if not allow_transient_unavailable:
            raise
        return {
            "ok": False,
            "transient_unavailable": True,
            "warning": str(exc),
            "chat_count": len(chats),
            "test_message_sent": False,
        }

    return {
        "ok": True,
        "bot_username": bot_info.get("username") or "",
        "chat_count": len(chats),
        "test_message_sent": bool(send_test),
    }


def send_success(summary_path: Path, report_path: Path | None) -> None:
    chats = _chat_ids()
    if not chats:
        raise TelegramPermanentError("TELEGRAM_CHAT_IDS is missing")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    text = format_summary(summary)
    send_always = str(os.environ.get("TELEGRAM_SEND_REPORT_ALWAYS") or "").strip().lower() in {"1", "true", "yes"}
    send_report = send_always or int(summary.get("daily_actionable", 0) or 0) > 0
    for chat_id in chats:
        _post("sendMessage", data={"chat_id": chat_id, "text": text})
        if send_report and report_path and report_path.exists():
            with report_path.open("rb") as f:
                _post(
                    "sendDocument",
                    data={"chat_id": chat_id, "caption": "Job Search Bot report"},
                    files={"document": (report_path.name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                )


def send_failure(message: str) -> None:
    chats = _chat_ids()
    if not chats or not _token():
        return
    for chat_id in chats:
        _post("sendMessage", data={"chat_id": chat_id, "text": f"❌ Job search failed\n{message}"})


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram notifications for cloud production runs")
    parser.add_argument("--summary")
    parser.add_argument("--report")
    parser.add_argument("--failure")
    parser.add_argument("--check", action="store_true", help="Validate bot token and configured chat IDs without running the job search")
    parser.add_argument("--send-test", action="store_true", help="With --check, send a short diagnostic message to each configured chat")
    parser.add_argument(
        "--allow-transient-unavailable",
        action="store_true",
        help="With --check, do not block production when Telegram has a temporary network/5xx/429 failure. Permanent token/chat errors still fail.",
    )
    args = parser.parse_args()
    if args.send_test and not args.check:
        parser.error("--send-test requires --check")
    if args.allow_transient_unavailable and not args.check:
        parser.error("--allow-transient-unavailable requires --check")
    if args.check:
        print(
            json.dumps(
                check_configuration(
                    send_test=args.send_test,
                    allow_transient_unavailable=args.allow_transient_unavailable,
                ),
                ensure_ascii=False,
            )
        )
    elif args.failure:
        send_failure(args.failure)
    else:
        if not args.summary:
            parser.error("--summary is required unless --failure or --check is used")
        send_success(Path(args.summary), Path(args.report) if args.report else None)


if __name__ == "__main__":
    main()
