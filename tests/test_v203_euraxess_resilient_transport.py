from types import SimpleNamespace
from unittest.mock import patch

from sources import euraxess
from sources import euraxess_transport as transport


class Response:
    def __init__(self, text='', url='https://euraxess.ec.europa.eu/jobs/search', status_code=200, headers=None):
        self.text = text
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


def card(job_id, country='Spain'):
    return f'<div><a href="/jobs/{job_id}">Research Project Manager {job_id}</a> JOB {country} Example University Posted on: 20 September 2026 Work Locations: {country}</div>'


FORM = '''<form action="/jobs/search"><select name="job_country[]"><option value="788">Spain</option></select><select name="offer_type[]"><option value="job_offer">Job Offer</option></select></form>'''
SELECTED = '''<form action="/jobs/search"><select name="job_country[]"><option value="788" selected>Spain</option></select><select name="offer_type[]"><option value="job_offer" selected>Job Offer</option></select></form>'''


def parse(html):
    import re
    rows=[]
    for m in re.finditer(r'/jobs/(\d+)', html):
        jid=m.group(1)
        country='Spain' if 'Spain' in html else 'Germany'
        rows.append({'id':jid,'url':f'https://euraxess.ec.europa.eu/jobs/{jid}','title':f'Research {jid}','location':country,'description':html,'date':'20 September 2026'})
    unique={r['id']:r for r in rows}
    return list(unique.values())


def is_spain(row):
    return row.get('location') == 'Spain'


def posted(_):
    from datetime import date
    return date(2026,9,20)


def test_dynamic_spain_and_job_offer_facets_are_required():
    assert transport._discover_facets(FORM)[:2] == ('job_country:788','offer_type:job_offer')
    assert transport._facet_active(SELECTED,'job_country:788','offer_type:job_offer') is True
    assert transport._facet_active(FORM,'job_country:788','offer_type:job_offer') is False


def test_global_pagination_uses_get_then_post_and_recovers_self_reset():
    page0 = card('100') + '<a rel="next" href="/jobs/search?page=1">Next</a>'
    page1 = card('101') + '<a rel="next" href="/jobs/search?page=1">Next</a>'
    page2 = card('102')
    calls=[]
    class Session:
        def get(self,url,**kwargs):
            calls.append(('GET',url))
            return Response(page0,url)
        def post(self,url,**kwargs):
            calls.append(('POST',url))
            if 'page=2' in url:
                return Response(page2,url)
            return Response(page1,url)
        def close(self): pass
    rows, diag = transport.fetch_spain_pages(
        base='https://euraxess.ec.europa.eu', pages=4, timeout=(1,1), use_spain_facet=False,
        parse_search_html=parse, is_spain=is_spain, parse_posted_date=posted,
        request_delay=0, make_session=lambda **_: Session(),
    )
    assert [r['id'] for r in rows] == ['100','101','102']
    assert calls[0][0] == 'GET'
    assert all(method == 'POST' for method,_ in calls[1:])
    assert diag['coverage_complete'] is True
    assert diag['pagination_repeat_detected'] is False


def test_filtered_http_200_with_inactive_facet_is_incomplete():
    class Session:
        def get(self,url,**kwargs):
            if kwargs.get('params'):
                return Response(FORM + card('100','Germany'), url)
            return Response(FORM, url)
        def post(self,*a,**k): raise AssertionError('no post expected')
        def close(self): pass
    rows, diag = transport.fetch_spain_pages(
        base='https://euraxess.ec.europa.eu', pages=2, timeout=(1,1), use_spain_facet=True,
        parse_search_html=parse, is_spain=is_spain, parse_posted_date=posted,
        request_delay=0, make_session=lambda **_: Session(),
    )
    assert rows == []
    assert diag['coverage_complete'] is False
    assert diag['stop_reason'] == 'filter_validation_failed'


def test_detail_429_is_bounded_and_backed_off():
    statuses=[('', 'HTTP 429'), ('detail text', 'OK_HTML')]
    def fetcher(*args,**kwargs): return statuses.pop(0)
    with patch.object(transport.time,'sleep') as sleep:
        detail,status,count = transport.fetch_detail_resilient(
            fetcher,'https://euraxess.ec.europa.eu/jobs/1',timeout=(1,1),title_hint='x',session=object(),pace_seconds=0
        )
    assert detail == 'detail text'
    assert status == 'OK_HTML'
    assert count == 2
    sleep.assert_called_once_with(30.0)

def test_parser_rejects_external_jobs_path_links():
    html = """
    <div><a href="https://www.science.hr/jobs/244480/">External Research Job</a> JOB Spain External Org Posted on: 20 September 2026 Work Locations: Spain</div>
    <div><a href="/jobs/470367">EURAXESS Research Job</a> JOB Spain Internal Org Posted on: 20 September 2026 Work Locations: Spain</div>
    """
    rows = euraxess.parse_search_html(html)
    assert [row['id'] for row in rows] == ['470367']
    assert rows[0]['url'] == 'https://euraxess.ec.europa.eu/jobs/470367'


def test_next_listing_prefers_listing_path_over_job_detail():
    html = """
    <a rel="next" href="/jobs/470367">Next job</a>
    <a rel="next" href="/jobs/search?page=1">Next</a>
    """
    assert transport._next_listing_url(
        html, 'https://euraxess.ec.europa.eu/jobs/search?page=0'
    ) == 'https://euraxess.ec.europa.eu/jobs/search?page=1'


def test_next_listing_keeps_cross_path_fallback_when_no_listing_path_exists():
    html = '<a rel="next" href="/alternative?page=2">Next</a>'
    assert transport._next_listing_url(
        html, 'https://euraxess.ec.europa.eu/jobs/search?page=1'
    ) == 'https://euraxess.ec.europa.eu/alternative?page=2'
