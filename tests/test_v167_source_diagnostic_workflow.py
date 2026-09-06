from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / '.github' / 'workflows' / 'source-diagnostic.yml'


def test_v167_diagnostic_workflow_is_state_safe_and_source_selectable():
    text = WF.read_text(encoding='utf-8')
    assert 'name: Source Diagnostic' in text
    assert 'source:' in text
    assert '--source "$SOURCE"' in text
    assert '--no-state' in text
    assert 'timeout-minutes: 90' in text
    assert 'download-state' not in text
    assert 'publish-run' not in text
    assert 'R2_ACCESS_KEY_ID' not in text
    assert 'TELEGRAM_BOT_TOKEN' not in text
    assert '[diagnostic:start]' in text
    assert '[diagnostic:done]' in text
