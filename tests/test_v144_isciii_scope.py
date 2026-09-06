from run_live_sample import build_parser
from sources import isciii_employment


def test_isciii_default_production_scope_is_one_page():
    args = build_parser().parse_args(["--source", "isciii"])
    assert args.isciii_pages == 1


def test_isciii_diag_labels_one_page_scope(monkeypatch):
    html = '''<html><body><a href="https://www.isciii.es/l/123">Role A Fecha de inicio: 01/08/2026 Fecha límite: 31/08/2026 Estado: Inicial</a></body></html>'''

    class Resp:
        status_code = 200
        url = "https://www.isciii.es/trabaja-isciii"
        text = html
        def raise_for_status(self):
            return None

    class Session:
        def get(self, *args, **kwargs):
            return Resp()

    monkeypatch.setattr(isciii_employment, "make_retry_session", lambda **kwargs: Session())
    diag = {}
    jobs = isciii_employment.collect(max_pages=1, enrich_detail=False, diagnostics=diag)
    assert len(jobs) == 1
    assert diag["coverage_scope"] == "newest_page_only"
    assert diag["coverage_complete"] is True
    assert diag["portal_full_coverage"] is False
