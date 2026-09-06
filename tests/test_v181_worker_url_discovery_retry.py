from pathlib import Path

from jobbot.production import PRODUCTION_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_v181_production_version():
    assert PRODUCTION_VERSION == "V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE"


def test_deploy_uses_cloudflare_subdomain_api_not_wrangler_url_scraping():
    text = (ROOT / ".github" / "workflows" / "deploy-telegram-control-plane.yml").read_text(encoding="utf-8")
    assert "/workers/subdomain" in text
    assert "/workers/scripts/$WORKER_NAME/subdomain" in text
    assert 'WORKER_URL="https://${WORKER_NAME}.${ACCOUNT_SUBDOMAIN}.workers.dev"' in text
    assert "grep -Eo 'https://[A-Za-z0-9.-]+\\.workers\\.dev'" not in text


def test_deploy_waits_for_worker_route_and_retries_readiness():
    text = (ROOT / ".github" / "workflows" / "deploy-telegram-control-plane.yml").read_text(encoding="utf-8")
    assert "Wait for Worker route" in text
    assert "seq 1 12" in text
    assert '"$WORKER_URL/health"' in text
    assert "seq 1 5" in text
    assert '"$WORKER_URL/ready"' in text
