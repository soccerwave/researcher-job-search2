# V1.64 Cloud Production Architecture

## Decision

This production design intentionally separates the three responsibilities:

```text
Cloudflare Worker        -> scheduler + Telegram control plane
GitHub Actions            -> executes the Python job-search engine
Cloudflare R2             -> persistent state + latest/daily run data
Telegram                  -> private user interface + notifications + Excel download
```

The frozen research-fit scoring engine remains `V1.36_FINAL_SCORING_CLEANUP`.
V1.64 preserves the V1.63 deployment architecture and changes repository hygiene only; it does not change scoring, source collection,
availability, or dedupe behavior.

## Normal daily flow

```text
03:17 UTC every day
      |
      v
Cloudflare Cron
      |
      | workflow_dispatch
      v
GitHub Actions
      |
      +--> restore state/current/seen_jobs.json from R2
      +--> run all configured sources
      +--> update seen/history state
      +--> build job_search_report.xlsx
      +--> backup + publish state and outputs to R2
      +--> send Telegram completion summary
      `--> send Excel automatically when daily_actionable > 0
```

03:17 UTC corresponds to 05:17 in Spain during CEST and 04:17 during CET. The
run therefore stays at a low-traffic UTC time without any DST logic.

## Telegram control plane

Only numeric Telegram user IDs listed in `TELEGRAM_ALLOWED_USER_IDS` are
accepted, and commands are accepted only in private chats.

Supported controls:

- `/run` — manually trigger the same GitHub workflow used by the daily cron.
- `/status` — latest GitHub workflow state plus latest published bot summary.
- `/today` — latest production summary.
- `/file` — download the latest Excel report directly from R2.
- `/help` — show the control menu.

Inline buttons expose the same actions. A second `/run` while a workflow is
queued/running is rejected by the Worker; GitHub Actions also has a single
production concurrency group as a second safety layer.

## R2 object layout

```text
state/current/seen_jobs.json
state/backups/<timestamp>-<run-id>.json
state/bootstrap/<timestamp>.json

latest/run_summary.json
latest/job_search_report.xlsx
latest/daily_actionable.csv
latest/new_actionable.csv
latest/changed_or_reopened.csv
latest/actionable.csv
latest/needs_detail_review.csv
latest/source_summary.csv
latest/cloud_publish_manifest.json

runs/YYYY-MM-DD/<github-run-id>/...
```

The state is downloaded before collection and is uploaded only after a
successful production run. Every successful state update is backed up before
`state/current/seen_jobs.json` is replaced.

## First deployment: required values

### GitHub repository variables

- `R2_BUCKET` — recommended: `job-search-bot-data`
- `R2_ENDPOINT` — optional; normally `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`
- `MADS_REPO` — optional; defaults in the workflow to `MadsLorentzen/ai-job-search`
- `INFOJOBS_REPO` — required, `owner/repo` of the Spain fork used for InfoJobs
- `TELEGRAM_SEND_REPORT_ALWAYS` — optional; `true` to send Excel after every run

### GitHub repository secrets

- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_IDS` — comma-separated private chat IDs for the two recipients
- `EXTERNAL_REPO_TOKEN` — only needed when an external discovery repo is private

### Cloudflare Worker variables (`wrangler.toml`)

- `GITHUB_OWNER`
- `GITHUB_REPO`
- `GITHUB_WORKFLOW=production-job-search.yml`
- `GITHUB_REF=main`

### Cloudflare Worker secrets

Use `wrangler secret put <NAME>` for:

- `GITHUB_TOKEN` — fine-grained token with Actions read/write on this repository
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET`
- `TELEGRAM_ALLOWED_USER_IDS` — comma-separated numeric IDs of the two authorized users

The Worker also needs the R2 binding named `REPORTS` configured in
`wrangler.toml`.

## Critical first-run rule

Do **not** trigger the cloud production workflow before the current validated
local state has been bootstrapped to R2.

The workflow deliberately fails closed when
`state/current/seen_jobs.json` is missing. This prevents the first cloud run
from silently treating the whole market as NEW.

After R2 credentials are configured, bootstrap the current local state with:

```powershell
$env:R2_ACCOUNT_ID="..."
$env:R2_ACCESS_KEY_ID="..."
$env:R2_SECRET_ACCESS_KEY="..."
$env:R2_BUCKET="job-search-bot-data"
py .\scripts\r2_store.py bootstrap-state --file "$env:USERPROFILE\.job-search-bot\seen_jobs.json"
```

The current local state should be the durable file created by V1.62, not an
older recovered copy.

## Telegram setup order

1. Create a bot with BotFather and copy the bot token.
2. Before setting a webhook, each authorized person sends one message to the bot.
3. Run `cloudflare-worker/get_telegram_ids.ps1` to obtain the numeric user/chat IDs.
4. Put those user IDs in the Worker secret `TELEGRAM_ALLOWED_USER_IDS` and the
   private chat IDs in GitHub secret `TELEGRAM_CHAT_IDS`.
5. Deploy the Worker.
6. Set the webhook with `cloudflare-worker/set_telegram_webhook.ps1` using a random
   `TELEGRAM_WEBHOOK_SECRET`.

### Telegram GitHub preflight

After `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_IDS` are present under **GitHub → Settings → Secrets and variables → Actions → Repository secrets**, run **Actions → Telegram Diagnostic → Run workflow**. The diagnostic validates the bot token, verifies every configured private chat, and sends a short test message. Production also runs the same validation before cloning external transports or starting the 22-source scan, so Telegram configuration errors fail fast instead of appearing after a 20-minute search.

## Validation sequence

Production rollout should be done in this order:

1. Upload repository and configure GitHub variables/secrets.
2. Create R2 bucket and configure R2 credentials/binding.
3. Bootstrap the current validated state to R2.
4. Manually run the GitHub workflow once with `workflow_dispatch`.
5. Compare cloud source diagnostics against the latest local production run.
6. Deploy Cloudflare Worker and Telegram webhook.
7. Test `/status`, `/file`, and one manual `/run`.
8. Leave the daily 03:17 UTC Cron enabled.

If the cloud execution differs materially from the validated local collectors,
fix that deployment/environment issue before enabling the daily Cron. Do not
retune the frozen scoring engine for a cloud transport problem.

## V1.80 consolidated control-plane deployment

For the current deployment, the separate Worker/webhook/control-command validation steps are consolidated into one GitHub Action: **Deploy Telegram Control Plane**.

It uses the existing `R2_ACCOUNT_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`, and `R2_BUCKET`, plus two deployment credentials:

- `CLOUDFLARE_API_TOKEN` — Cloudflare API token able to deploy/update this Worker and its R2 binding.
- `GH_CONTROL_TOKEN` — long-lived fine-grained GitHub token for this repository with Actions read/write access, used by the Worker after the GitHub deployment job has finished.

The action deploys the Worker, installs Worker secrets, generates the Telegram webhook secret, sets the Telegram webhook and command menu, verifies `/health` and authenticated `/ready`, and finally routes a `/status` update through the Worker. A green workflow therefore validates the whole control path in one pass; there is no need to separately test each Telegram command before normal use.

## Complete canonical history archive (V1.83)
Each successful production run persists the full canonical market snapshot separately from the Telegram-facing report:

```text
runs/YYYY-MM-DD/<run-id>/all_canonical.csv.gz
latest/all_canonical.csv.gz
```

The per-run gzip object is immutable and contains all canonical rows, including `SKIP` and `CLOSED`. This is the long-term analytical archive. The `latest/` object is only a convenience pointer and is overwritten each run. Telegram does not send this archive file; it continues to deliver the compact `job_search_report.xlsx` according to the existing notification rules.
