from sources.fisabio import parse_board_html, collect


def test_parse_fisabio_fundanet_rows_and_deadlines():
    html = '''
    <table><tbody>
      <tr>
        <td><a href="/convocatoriaspropias/es/Convocatorias/VerConvocatoria/871">2026/58 UN/A TÉCNICO/A DE GESTIÓN DE LA INVESTIGACIÓN (M3)</a></td>
        <td>17/08/2026 14:52</td><td>01/09/2026 23:59</td>
      </tr>
      <tr>
        <td><a href="/convocatoriaspropias/es/Convocatorias/VerConvocatoria/869">2026/56 UN/A TÉCNICO/A DE INVESTIGACIÓN (T3)</a></td>
        <td>17/08/2026 14:15</td><td>01/09/2026 23:59</td>
      </tr>
    </tbody></table>
    '''
    rows = parse_board_html(html)
    assert len(rows) == 2
    assert rows[0]["id"] == "2026/58"
    assert rows[0]["source"] == "FISABIO"
    assert rows[0]["company"] == "Fundación Fisabio"
    assert rows[0]["location"] == "Valencia, Spain"
    assert "Application deadline: 01/09/2026" in rows[0]["description"]
    assert rows[0]["url"].endswith("/VerConvocatoria/871")


def test_parse_fisabio_ignores_non_vacancy_links_and_deduplicates():
    html = '''
    <a href="/convocatoriaspropias/es/Convocatorias/DesgloseEstadoTipoConvocatoria/EMPLEO">Estado</a>
    <table><tr><td>
      <a href="/convocatoriaspropias/es/Convocatorias/VerConvocatoria/871">2026_58 UN/A TÉCNICO/A</a>
      <a href="/convocatoriaspropias/es/Convocatorias/VerConvocatoria/871#x">duplicate</a>
    </td><td>17/08/2026 14:52</td><td>01/09/2026 23:59</td></tr></table>
    '''
    rows = parse_board_html(html)
    assert len(rows) == 1
    assert rows[0]["id"] == "2026/58"


def test_collect_fisabio_marks_detail_failure_without_scoring_snippet(monkeypatch):
    class Resp:
        status_code = 200
        url = "https://fisabio.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/DetalleTipoConvocatoria/EMPLEO?Estado=A"
        text = '<table><tr><td><a href="/convocatoriaspropias/es/Convocatorias/VerConvocatoria/871">2026/58 UN/A TÉCNICO/A</a></td><td>17/08/2026</td><td>01/09/2026</td></tr></table>'
        def raise_for_status(self): return None
    class DetailResp:
        status_code = 200
        url = "https://fisabio.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/VerConvocatoria/871"
        text = '<html><body>Application wrapper only</body></html>'
        def raise_for_status(self): return None
    class Session:
        def get(self, url, *args, **kwargs):
            if "DetalleTipoConvocatoria" in url: return Resp()
            return DetailResp()
        def close(self): pass
    monkeypatch.setattr("sources.fisabio.make_retry_session", lambda **kwargs: Session())
    diag = {}
    rows = collect(diagnostics=diag)
    assert len(rows) == 1
    assert rows[0]["full_detail"] == ""
    assert rows[0]["detail_status"] == "FISABIO_BASES_LINK_NOT_FOUND"
    assert diag["detail_failed"] == 1
    assert diag["coverage_complete"] is True
