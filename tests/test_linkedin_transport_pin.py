from pathlib import Path

from sources.linkedin_mads import CLI_RELATIVE

MADS_PIN = "fd89eac178dc546d41f6c1a3213de88d96112c6d"


def test_production_pins_linkedin_transport_without_blocking_other_sources():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/production-job-search.yml"
    ).read_text(encoding="utf-8")
    assert f'MADS_PIN="{MADS_PIN}"' in workflow
    assert 'git -C "$AI_JOB_SEARCH_MADS_REPO" fetch --depth 1 origin "$MADS_PIN"' in workflow
    assert 'git -C "$AI_JOB_SEARCH_MADS_REPO" checkout --detach "$MADS_PIN"' in workflow
    assert '"$(git -C "$AI_JOB_SEARCH_MADS_REPO" rev-parse HEAD)" = "$MADS_PIN"' in workflow
    assert f'$AI_JOB_SEARCH_MADS_REPO/{CLI_RELATIVE.as_posix()}' in workflow
    assert 'if clone_repo "$MADS_REPO" "$AI_JOB_SEARCH_MADS_REPO"' in workflow
    assert 'rm -rf "$AI_JOB_SEARCH_MADS_REPO"' in workflow
    assert 'LinkedIn transport unavailable or pinned CLI invalid' in workflow
    assert 'LinkedIn transport dependency setup failed' in workflow
    assert 'clone_repo "$INFOJOBS_REPO" "$AI_JOB_SEARCH_SPAIN_REPO"' in workflow
    assert workflow.index('clone_repo "$INFOJOBS_REPO"') < workflow.index("- name: Run all production sources")


def test_linkedin_collector_reports_error_without_crashing_run():
    collector = (
        Path(__file__).resolve().parents[1] / "sources/linkedin_mads.py"
    ).read_text(encoding="utf-8")
    assert 'Mads ai-job-search repo with linkedin-search CLI was not found' in collector
    assert 'return []' in collector
