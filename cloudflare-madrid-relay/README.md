# Madrid API relay

Fixed-purpose Cloudflare Worker used only to relay authenticated POEM offer reads from GitHub Actions.

Routes:
- `GET /health` (public health check)
- `GET /offer/<numeric-id>` (requires `Authorization: Bearer <MADRID_RELAY_TOKEN>`)

The Worker is intentionally **not** a generic proxy: the upstream host/path is hard-coded to the public Madrid POEM offers API.
Set the Worker secret `MADRID_RELAY_TOKEN`, then configure GitHub Actions with:
- repository variable `MADRID_RELAY_URL` = Worker base URL, no trailing slash
- repository secret `MADRID_RELAY_TOKEN` = the same shared token

V1.73 relay behavior:
- one bounded upstream attempt per Worker invocation
- 6-second upstream timeout
- GitHub-side relay calls still bypass generic urllib3 5xx retries
- the Python Madrid collector performs one delayed second pass only for transient relay transport/429/5xx failures
- total relay attempt budget remains at most 2 per affected offer, with relay detail concurrency still capped at 3
