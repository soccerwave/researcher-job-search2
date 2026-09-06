from pathlib import Path

from jobbot.production import PRODUCTION_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_v180_production_version():
    assert PRODUCTION_VERSION == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"


def test_one_click_deployment_workflow_covers_full_control_plane():
    text = (ROOT / ".github" / "workflows" / "deploy-telegram-control-plane.yml").read_text(encoding="utf-8")
    for expected in (
        "CLOUDFLARE_API_TOKEN",
        "GH_CONTROL_TOKEN",
        "npx wrangler deploy",
        "wrangler secret put GITHUB_TOKEN",
        "wrangler secret put TELEGRAM_BOT_TOKEN",
        "wrangler secret put TELEGRAM_WEBHOOK_SECRET",
        "wrangler secret put TELEGRAM_ALLOWED_USER_IDS",
        "setWebhook",
        "setMyCommands",
        '"$WORKER_URL/ready"',
        '"$WORKER_URL/telegram"',
        '"text": "/status"',
    ):
        assert expected in text


def test_worker_readiness_is_authenticated_and_checks_all_links():
    text = (ROOT / "cloudflare-worker" / "src" / "index.js").read_text(encoding="utf-8")
    assert 'url.pathname === "/ready"' in text
    assert 'request.headers.get("Authorization")' in text
    assert 'await listRuns(env)' in text
    assert 'env.REPORTS.get("latest/run_summary.json")' in text
    assert 'await tg(env, "getMe")' in text


def test_search_engine_files_are_not_touched_by_v180_deployment_scope():
    metadata = (ROOT / "PRODUCTION_VERSION.json").read_text(encoding="utf-8")
    assert '"search_engine_baseline": "V1.78_IDIBAPS_REPLACEMENT"' in metadata
    assert '"scoring_engine": "V1.36_FINAL_SCORING_CLEANUP"' in metadata
