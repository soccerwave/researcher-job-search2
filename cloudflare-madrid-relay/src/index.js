const POEM_OFFERS_API =
  "https://apiscm.comunidad.madrid/t/ciudadanos.comunidad.madrid/educacion/portal-empleo/v1.1/ofertas";

const UPSTREAM_TIMEOUT_MS = 6000;
const MAX_ATTEMPTS = 1;
function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

async function fetchOffer(upstream) {
  const response = await fetch(upstream, {
    method: "GET",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "application-credentials": "true",
      "x-trace-id": crypto.randomUUID().replaceAll("-", ""),
      Origin: "https://gestiona.comunidad.madrid",
      Referer: "https://gestiona.comunidad.madrid/poem_webapp/",
      "User-Agent": "Mozilla/5.0",
    },
    signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
  });

  return { response, attempts: MAX_ATTEMPTS };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return json({ ok: true, service: "madrid-api-relay" });
    }

    if (request.method !== "GET") {
      return json({ ok: false, error: "method_not_allowed" }, 405);
    }

    const expected = String(env.MADRID_RELAY_TOKEN || "");
    const provided = String(request.headers.get("Authorization") || "");
    if (!expected || provided !== `Bearer ${expected}`) {
      return json({ ok: false, error: "unauthorized" }, 401);
    }

    const match = url.pathname.match(/^\/offer\/(\d{1,10})$/);
    if (!match) {
      return json({ ok: false, error: "not_found" }, 404);
    }

    const offerId = match[1];
    const upstream = `${POEM_OFFERS_API}/${offerId}`;

    try {
      const { response, attempts } = await fetchOffer(upstream);
      const body = await response.arrayBuffer();
      return new Response(body, {
        status: response.status,
        headers: {
          "Content-Type": response.headers.get("content-type") || "application/json",
          "Cache-Control": "no-store",
          "X-Madrid-Relay-Attempts": String(attempts),
        },
      });
    } catch (error) {
      return json(
        {
          ok: false,
          error: "upstream_unavailable",
          detail: `${error.name}: ${error.message}`,
          attempts: MAX_ATTEMPTS,
        },
        504,
      );
    }
  },
};
