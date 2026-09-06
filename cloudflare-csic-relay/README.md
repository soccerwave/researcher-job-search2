# CSIC Sede relay

Fixed-purpose Cloudflare Worker for the official CSIC Sede personnel board when GitHub-hosted runners cannot establish a direct connection to `sede.csic.gob.es`.

Routes:
- `GET /health` — public health check
- `GET /board?page=<0..50>` — authenticated relay for the official personnel listing pages
- `GET /convocatoria/<numeric-id>` — authenticated relay for one official CSIC vacancy page

The Worker is intentionally **not** a generic proxy. The upstream host and accepted paths are hard-coded.

Configuration:
1. Deploy this Worker.
2. Set Worker secret `CSIC_RELAY_TOKEN`.
3. Set GitHub repository variable `CSIC_RELAY_URL` to the Worker base URL (no trailing slash).
4. Set GitHub repository secret `CSIC_RELAY_TOKEN` to the same token.

V1.75 behavior:
- direct/local CSIC collection is unchanged when relay settings are absent;
- cloud collection uses the relay when both relay settings exist;
- one GitHub-side relay attempt is made per request;
- Worker upstream timeout is bounded at 12 seconds;
- canonical job URLs remain official `sede.csic.gob.es` URLs;
- the relay never accepts arbitrary upstream URLs.
