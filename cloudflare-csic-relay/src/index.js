const CSIC_ORIGIN = "https://sede.csic.gob.es";
const BOARD_PATH = "/tramites/convocatorias-de-personal";
const UPSTREAM_TIMEOUT_MS = 12000;

function json(data, status = 200) {
  return Response.json(data, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

async function fetchCsic(pathAndQuery) {
  const upstream = `${CSIC_ORIGIN}${pathAndQuery}`;
  const response = await fetch(upstream, {
    method: "GET",
    redirect: "follow",
    headers: {
      Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
      "Cache-Control": "no-cache",
      Pragma: "no-cache",
      "User-Agent": "Mozilla/5.0",
    },
    signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
  });
  return { response, upstream };
}

function proxiedResponse(response) {
  return response.arrayBuffer().then((body) => new Response(body, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") || "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "X-CSIC-Relay-Upstream-Status": String(response.status),
    },
  }));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return json({ ok: true, service: "csic-sede-relay" });
    }

    if (request.method !== "GET") {
      return json({ ok: false, error: "method_not_allowed" }, 405);
    }

    const expected = String(env.CSIC_RELAY_TOKEN || "");
    const provided = String(request.headers.get("Authorization") || "");
    if (!expected || provided !== `Bearer ${expected}`) {
      return json({ ok: false, error: "unauthorized" }, 401);
    }

    let pathAndQuery = "";
    if (url.pathname === "/board") {
      const rawPage = url.searchParams.get("page") || "0";
      if (!/^\d{1,2}$/.test(rawPage)) {
        return json({ ok: false, error: "invalid_page" }, 400);
      }
      const page = Number(rawPage);
      if (page < 0 || page > 50) {
        return json({ ok: false, error: "invalid_page" }, 400);
      }
      pathAndQuery = page === 0 ? BOARD_PATH : `${BOARD_PATH}?page=${page}`;
    } else {
      const match = url.pathname.match(/^\/convocatoria\/(\d{1,10})$/);
      if (!match) {
        return json({ ok: false, error: "not_found" }, 404);
      }
      pathAndQuery = `${BOARD_PATH}/convocatoria/${match[1]}`;
    }

    try {
      const { response } = await fetchCsic(pathAndQuery);
      return await proxiedResponse(response);
    } catch (error) {
      return json({
        ok: false,
        error: "upstream_unavailable",
        detail: `${error.name}: ${error.message}`,
      }, 504);
    }
  },
};
