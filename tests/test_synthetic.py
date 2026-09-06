import json
from pathlib import Path
from jobbot.evaluate import evaluate_job

DATA = Path(__file__).with_name("synthetic_jobs.json")


def test_synthetic_cases():
    cases = json.loads(DATA.read_text(encoding="utf-8"))
    failures = []
    for job in cases:
        result = evaluate_job(job)
        if result["recommendation"] not in job["expected"]:
            failures.append((job["case"], result["recommendation"], result["score"], job["expected"], result))
    assert not failures, failures
