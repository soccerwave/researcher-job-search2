import json
from sources import madrid_idi as madrid


class Resp:
    def __init__(self, status=200, payload=None, text='', url='https://x.test'):
        self.status_code=status
        self._payload=payload
        self.text=text
        self.url=url
        self.headers={'content-type':'application/json'}
        self.content=text.encode()
    def json(self):
        if self._payload is None:
            raise ValueError('not json')
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class APISession:
    def __init__(self, payload):
        self.payload=payload
        self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs))
        return Resp(200,self.payload,url=url)


def test_poem_public_api_exact_path_and_anonymous_headers():
    payload={'result':{'status':True,'http_code':201},'data':{'idOferta':63661,'dsPuesto':'Project Manager','dsEmpresa':'IMDEA'}}
    s=APISession(payload)
    data,status=madrid._fetch_poem_api({'id':'63661'},s,(1,1))
    assert status == 'POEM_API_OK'
    assert data['dsEmpresa']=='IMDEA'
    url,kwargs=s.calls[0]
    assert url.endswith('/portal-empleo/v1.1/ofertas/63661')
    h=kwargs['headers']
    assert h['application-credentials']=='true'
    assert h['x-trace-id']
    assert 'Authorization' not in h


def test_poem_render_labels_publication_end_as_listing_window():
    data={
      'idOferta':1,
      'dsPuesto':'Clinical Research Coordinator',
      'fcPublicacionHasta':'2026-09-07T22:00:00.000+00:00',
      'requisitosDto':{'dsRequisitos':'Experience in human research and data analysis.'},
    }
    text=madrid._render_poem_offer_data(data)
    assert 'Position: Clinical Research Coordinator' in text
    assert 'Portal listing end: 07/09/2026' in text
    assert 'Requirements: Experience in human research and data analysis.' in text
    assert 'idOferta' not in text


def test_external_url_is_extracted_but_madrid_internal_urls_are_not_job_targets():
    data={'dsOtros':'La descripción de este puesto está disponible aquí https://example.org/jobs/abc y https://gestiona.comunidad.madrid/foo'}
    urls=madrid._extract_public_urls(data)
    external=[u for u in urls if madrid._is_external_job_url(u)]
    assert external == ['https://example.org/jobs/abc']
    rendered=madrid._render_poem_offer_data(data)
    assert madrid._api_looks_partial(rendered, external) is True


def test_api_metadata_updates_location_company_and_reference():
    job={'company':'old','location':'Madrid, Spain'}
    data={
      'dsEmpresa':'Hospital Foundation',
      'provinciaDto':{'dsNombre':'Madrid'},
      'municipioDto':{'dsNombre':'Leganés'},
      'dsReferencia':'REF-123',
      'fcPublicacionHasta':'2026-09-01T22:00:00.000+00:00',
    }
    madrid._apply_poem_metadata(job,data)
    assert job['company']=='Hospital Foundation'
    assert job['location']=='Leganés, Madrid, Spain'
    assert job['poem_reference']=='REF-123'
    assert job['poem_publication_end'].startswith('2026-09-01')


def test_substantive_poem_json_can_be_full_detail_without_external_url(monkeypatch):
    data={
      'dsPuesto':'Research Project Manager',
      'dsEmpresa':'Research Institute',
      'dsFunciones':'Coordinate Horizon Europe consortium work packages, deliverables, milestones, partner meetings, reporting, study implementation and dissemination. '*6,
      'dsRequisitos':'University degree in health sciences. Experience coordinating international research projects and strong written English. '*5,
      'fcPublicacionHasta':'2026-09-30T22:00:00.000+00:00',
    }
    monkeypatch.setattr(madrid,'_fetch_poem_api',lambda *a,**k:(data,'POEM_API_OK'))
    job={'id':'1','title':'Research Project Manager','company':'','location':'Madrid, Spain','detail_candidates':[]}
    detail,status,url,method=madrid._fetch_detail_candidates(job,object(),(1,1))
    assert status=='OK'
    assert method=='poem_api'
    assert 'Horizon Europe' in detail
    assert url.endswith('/ofertas/1')


def test_redirect_style_poem_record_is_not_scored_if_external_fetch_fails(monkeypatch):
    data={
      'dsPuesto':'IT Project Manager',
      'dsEmpresa':'IMDEA',
      'dsOtros':'La descripción de este puesto está disponible aquí https://example.org/jobs/it-project-manager/ Igualdad de oportunidades.',
      'fcPublicacionHasta':'2026-08-30T22:00:00.000+00:00',
    }
    monkeypatch.setattr(madrid,'_fetch_poem_api',lambda *a,**k:(data,'POEM_API_OK'))
    monkeypatch.setattr(madrid,'fetch_url_text',lambda *a,**k:('', 'FETCH_FAILED: test'))
    job={'id':'63661','title':'IT project manager - research support 2026','company':'IMDEA','location':'Madrid, Spain','detail_candidates':[]}
    detail,status,url,method=madrid._fetch_detail_candidates(job,object(),(1,1))
    assert detail==''
    assert status=='POEM_API_PARTIAL_DETAIL'
    assert method=='poem_api_partial'
