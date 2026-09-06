from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_failure_notification_lines_remain_inside_run_block():
    lines = (ROOT / ".github" / "workflows" / "production-job-search.yml").read_text(encoding="utf-8").splitlines()
    trigger_lines = [line for line in lines if "Trigger: %s" in line]
    assert trigger_lines, "failure notification message missing"
    assert all(line.startswith("            ") for line in trigger_lines)
    assert not any(line.startswith("Trigger:") or line.startswith("Run:") for line in lines)
