from tests.legacy_tools.probe_madrid_poem_api import _candidate_urls, _extract_method_suffix


def test_method_suffix_extraction_from_minified_service():
    ctx = 'n.prototype.getOfertaById=function(n){var t=this.getHeaders(),e=this.url+"oferta-completa/"+n;return this.http.get(e,{headers:t})}'
    assert _extract_method_suffix(ctx) == "oferta-completa/"


def test_candidate_urls_put_exact_discovered_path_first():
    urls = _candidate_urls(
        "https://api.example/v1/",
        "ofertas/",
        "oferta-completa/",
        "63661",
    )
    assert urls[0] == "https://api.example/v1/ofertas/oferta-completa/63661"
    assert len(urls) == len(set(urls))
