# Public repository safety

This snapshot is prepared for a public GitHub repository.

- No runtime state, job-result archives, local `.wrangler` cache, `.env` files, or Git history are included.
- Credentials remain GitHub Actions / Cloudflare secrets and are never committed.
- GitHub Actions artifact upload steps are disabled automatically when the repository is public. Production reports and state remain in private Cloudflare R2 / Telegram delivery paths.
- Temporary EURAXESS calibration/probe workflows were omitted from this public snapshot.

Before first production run, configure the repository secrets and variables documented in `docs/CLOUD_PRODUCTION.md`.
Never commit real values into `.env`, `.dev.vars`, workflow YAML, or `wrangler.toml`.
