# Job Search Bot — Production

Validated research-job search system for Spain / remote-Europe coverage.

## Current production versions

- Deployment package: `V1.84_TELEGRAM_TRANSIENT_NETWORK_RESILIENCE`
- Frozen scoring engine: `V1.36_FINAL_SCORING_CLEANUP`
- Sources: 22
- Persistent history/state: Cloudflare R2 in cloud production; durable local state for local runs

V1.83 keeps the validated V1.78 22-source search engine unchanged. V1.79–V1.81 are deployment/control-plane changes, V1.82 is reporting-only, and V1.83 adds archive-only R2 persistence. The frozen V1.36 scoring engine and search/state semantics remain unchanged.

## Repository layout

```text
.github/workflows/        GitHub Actions execution workflow
cloudflare-worker/        Cloudflare scheduler + Telegram control plane
config/                   Search/profile/rule configuration
jobbot/                   Evaluation, dedupe, availability, state, orchestration
sources/                  22 production source collectors
scripts/                  R2 transport, Excel report, Telegram notification
tests/                    Regression and production tests
docs/                     Cloud deployment documentation
run_live_sample.py        Local / production runner
SCORING_FREEZE_V136.json  Frozen scoring integrity manifest
```

## Local validation

```powershell
py -m pip install -r requirements.txt
py -m pytest -q
py .\run_live_sample.py --state-preflight
py .\run_live_sample.py --source all
```

## Cloud production

The production architecture is:

```text
Cloudflare Cron / Telegram
          ↓
Cloudflare Worker
          ↓ workflow_dispatch
GitHub Actions
          ↓
22-source job search
          ↓
Cloudflare R2 (state + outputs)
          ↓
Telegram summary / Excel
```

GitHub Actions has **no scheduled cron**. Cloudflare is the scheduler. Telegram is the private control/reporting interface and may also trigger a manual run.

See [`docs/CLOUD_PRODUCTION.md`](docs/CLOUD_PRODUCTION.md) for the deployment sequence and required secrets/variables.

## Important production rule

Do not start the first cloud search before the validated local `seen_jobs.json` has been bootstrapped to R2. The workflow fails closed if cloud state is missing so the existing market cannot silently be classified as all-new.

## What is intentionally not in this repository

Historical development bundles, old validation manifests, replay/calibration CSVs, one-off probe scripts, caches, and previous version artifacts are excluded from the production repository. They belong to development archives, not the deployable codebase.

### V1.76 CSIC source note
The production source key `csic` no longer uses the central CSIC Sede endpoint. It now scans three official Barcelona-area institute boards (ICM-CSIC, IQAC-CSIC, and IMB-CNM-CSIC) with independent fail-soft board handling. This is a curated local/relevance-oriented subset and **does not claim full CSIC coverage**. `CSIC_RELAY_URL` and `CSIC_RELAY_TOKEN` are no longer required by production or diagnostics; the V1.75 relay code is retained only for historical rollback/reference.


### V1.77 UPF source note (superseded)
The V1.77 MELIS replacement remained blocked by UPF HTTP 403 from GitHub Actions, so UPF is no longer a production source in V1.78. The historical collectors remain in the repository for audit/rollback only.

### V1.78 IDIBAPS source note
The former `upf` production slot is now `idibaps`, targeting the official FRCB-IDIBAPS job-offers page. The board exposes explicit open/closed state and deadlines and links directly to official vacancy PDFs used as Full JD. IDIBAPS is a stronger domain fit for the target search because it regularly publishes neuroscience, biomedical, data-management, research-support and project-management roles in Barcelona. Validate with `Source Diagnostic -> idibaps` before the next full production run.


### V1.79 Telegram preflight note
The search engine remains frozen from V1.78. V1.79 adds a manual **Telegram Diagnostic** GitHub Action plus a fail-fast `--check` before cloud production collection. Run the diagnostic after configuring the two GitHub Actions secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_IDS`; a successful diagnostic sends a short test message to every configured private chat.

### V1.80 one-click Telegram control plane deployment
V1.80 does not change the frozen V1.78 search engine. It adds **Actions → Deploy Telegram Control Plane**, which deploys the Cloudflare Worker, copies the already-configured Telegram recipients into the Worker's authorization list, generates and installs a webhook secret, registers `/run`, `/status`, `/today`, `/file`, and `/help`, verifies GitHub + R2 + Telegram connectivity, and sends one end-to-end `/status` request through the Worker.

The deployment action reuses the existing `R2_ACCOUNT_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`, and `R2_BUCKET`. The only deployment credentials it additionally expects are `CLOUDFLARE_API_TOKEN` and `GH_CONTROL_TOKEN` (a long-lived fine-grained GitHub token allowed to read Actions runs and dispatch `production-job-search.yml`). Once those are present, one workflow run completes the control-plane setup; separate `/status`, `/file`, and `/run` diagnostics are not required.


### V1.81 Worker URL/propagation hotfix
V1.81 fixes the deployment-only 404 seen immediately after the V1.80 Worker deploy. The workflow no longer scrapes a `workers.dev` URL from Wrangler console output. It reads the account subdomain from Cloudflare's API, explicitly enables the production `workers.dev` route for the deployed script, constructs the canonical Worker URL, and waits/retries until `/health` is live before configuring and verifying Telegram. Search/scoring/state behavior remains frozen from V1.78.

### V1.82 Madrid needs-detail report separation
V1.82 is reporting-only. Madrid rows whose Full JD could not be resolved remain safely tracked as `NEEDS_DETAIL_REVIEW`, but the Excel report now puts them in a dedicated `MADRID_NEEDS_DETAIL` sheet. The main `NEEDS_DETAIL` sheet therefore contains only unresolved jobs from other sources. `CURRENT_ACTIONABLE` and `TODAY_ACTIONABLE` keep their existing semantics, so no job is hidden or removed from the underlying production result. The Summary sheet and Telegram summary explicitly show total / Madrid / other-source needs-detail counts.

### V1.83 complete canonical R2 archive
V1.83 adds an archive-only persistence layer and does not change search, scoring, state, scheduling, Excel contents, or Telegram delivery. Every successful production run now stores the complete `all_canonical.csv` snapshot as gzip in R2 at `runs/YYYY-MM-DD/<run-id>/all_canonical.csv.gz`, plus a replace-in-place convenience copy at `latest/all_canonical.csv.gz`. The immutable per-run object includes every canonical row, including `SKIP`, `CLOSED`, actionable, and needs-detail records, so later longitudinal analysis can reconstruct the full observed market rather than only the operational shortlist. Telegram continues to send only the compact Excel report; the full canonical archive is never attached automatically.

### V1.84 Telegram transient-network resilience

Production no longer aborts a scheduled job-search run because Telegram temporarily resets a TLS connection or returns 429/5xx. Telegram calls retry with bounded backoff. The preflight still fails for permanent configuration errors such as a missing/invalid bot token or invalid chat ID. Search/scoring/state/source/R2/archive behavior is unchanged from V1.83.
