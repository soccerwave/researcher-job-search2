from pathlib import Path

from sources.linkedin_mads import CLI_RELATIVE

MADS_PIN = "fd89eac178dc546d41f6c1a3213de88d96112c6d"


def test_production_pins_linkedin_transport_and_checks_cli_before_running():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/production-job-search.yml"
    ).read_text(encoding="utf-8")
    assert f'MADS_PIN="{MADS_PIN}"' in workflow
    assert 'git -C "$AI_JOB_SEARCH_MADS_REPO" fetch --depth 1 origin "$MADS_PIN"' in workflow
    assert 'git -C "$AI_JOB_SEARCH_MADS_REPO" checkout --detach "$MADS_PIN"' in workflow
    assert 'test "$(git -C "$AI_JOB_SEARCH_MADS_REPO" rev-parse HEAD)" = "$MADS_PIN"' in workflow
    assert f'$AI_JOB_SEARCH_MADS_REPO/{CLI_RELATIVE.as_posix()}' in workflow
    assert workflow.index('if [ ! -f "$AI_JOB_SEARCH_MADS_REPO/') < workflow.index("- name: Run all production sources")
    assert 'clone_repo "$INFOJOBS_REPO" "$AI_JOB_SEARCH_SPAIN_REPO"' in workflow
