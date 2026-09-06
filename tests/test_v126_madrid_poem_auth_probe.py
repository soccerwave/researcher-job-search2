from tests.legacy_tools.probe_madrid_poem_auth import _candidate_urls, _extract_api_bases, _headers


def test_extracts_app_and_split_offer_api_bases():
    js = 'x={API_URL:"https://apiscm.comunidad.madrid/t/ciudadanos.comunidad.madrid/educacion/portal-empleo/v1.1/"}; y="https://apiscm.comunidad.madrid/t/ciudadanos.comunidad.madrid/educacion/ofertas-portal-empleo/v1"'
    bases = _extract_api_bases(js)
    assert "https://apiscm.comunidad.madrid/t/ciudadanos.comunidad.madrid/educacion/portal-empleo/v1.1/" in bases
    assert "https://apiscm.comunidad.madrid/t/ciudadanos.comunidad.madrid/educacion/ofertas-portal-empleo/v1/" in bases


def test_primary_candidate_is_service_path_under_each_base():
    bases = ["https://example.test/v1.1/", "https://example.test/offers/v1/"]
    urls = _candidate_urls(bases, "63661")
    assert urls[0] == "https://example.test/v1.1/ofertas/63661"
    assert "https://example.test/offers/v1/ofertas/63661" in urls


def test_angular_anonymous_headers_match_bundle_semantics():
    h = _headers("angular_anonymous")
    assert h["application-credentials"] == "true"
    assert h["Content-Type"] == "application/json"
    assert h["x-trace-id"]
