from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / '.github' / 'workflows' / 'all-source-diagnostic.yml'


def test_v168_matrix_benchmarks_all_sources_without_touching_production_state():
    text = WF.read_text(encoding='utf-8')
    expected = [
        'linkedin','infojobs','academicpositions','ikerbasque','atswatch','santpau','fbg','biocat',
        'gencat','csic','isciii','idibaps','upc','idibell','hospitaldelmar','euraxess','bist',
        'institutions','madrid','fisabio','fps','iislafe'
    ]
    assert 'name: All Source Diagnostic' in text
    assert 'fail-fast: false' in text
    assert 'max-parallel: 6' in text
    assert '--no-state' in text
    assert 'download-state' not in text
    assert 'publish-run' not in text
    assert 'R2_ACCESS_KEY_ID' not in text
    assert 'TELEGRAM_BOT_TOKEN' not in text
    assert '[diagnostic:start]' in text
    assert '[diagnostic:done]' in text
    assert 'GITHUB_STEP_SUMMARY' in text
    for source in expected:
        assert f'- {source}' in text
