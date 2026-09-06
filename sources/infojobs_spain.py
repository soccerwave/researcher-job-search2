from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .common import JobRecord

SOURCE_NAME = "InfoJobs"
CLI_RELATIVE = Path(".agents/skills/infojobs-search/cli/src/cli.ts")
CLOSED_RE = re.compile(
    r"(?:"
    r"esta\s+oferta\s+(?:ya\s+)?no\s+est[aá]\s+(?:activa|disponible)"
    r"|esta\s+oferta\s+ha\s+caducado"
    r"|oferta\s+(?:cerrada|caducada|finalizada)"
    r"|proceso\s+de\s+selecci[oó]n\s+(?:cerrado|finalizado)"
    r"|ya\s+no\s+se\s+aceptan\s+(?:candidaturas|solicitudes|inscripciones)"
    r"|inscripci[oó]n\s+cerrada"
    r"|no\s+longer\s+accepting\s+applications"
    r"|this\s+job\s+is\s+no\s+longer\s+available"
    r")",
    re.I,
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_queries() -> list[str]:
    path = _project_root() / "config" / "queries.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [_clean(q) for q in payload.get("infojobs_spain", []) if _clean(q)]


def _candidate_repos(explicit: str | Path | None = None) -> list[Path]:
    values: list[Path] = []
    if explicit:
        values.append(Path(explicit).expanduser())
    env = _clean(os.environ.get("AI_JOB_SEARCH_SPAIN_REPO"))
    if env:
        values.append(Path(env).expanduser())
    home = Path.home()
    values.extend([
        home / "Documents" / "ai-job-search-spain-test",
        home / "Documents" / "ai-job-search-spain",
        home / "ai-job-search-spain-test",
        home / "ai-job-search-spain",
    ])
    deduped: list[Path] = []
    seen: set[str] = set()
    for p in values:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def resolve_repo(explicit: str | Path | None = None) -> tuple[Path | None, list[str]]:
    checked: list[str] = []
    for repo in _candidate_repos(explicit):
        checked.append(str(repo))
        if (repo / CLI_RELATIVE).exists():
            return repo, checked
    return None, checked


def _default_runner(repo: Path, args: list[str], timeout_seconds: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bun", "run", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )


def _run_json(repo: Path, args: list[str], runner: Callable | None = None) -> dict[str, Any]:
    proc = (runner or _default_runner)(repo, args)
    if proc.returncode != 0:
        raise RuntimeError(_clean(proc.stderr) or _clean(proc.stdout) or "InfoJobs CLI failed")
    raw = (proc.stdout or "").strip()
    if not raw:
        return {"results": []}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from InfoJobs CLI: {raw[:400]}") from exc
    if isinstance(payload, list):
        return {"results": payload}
    if isinstance(payload, dict):
        return payload
    raise RuntimeError("Unexpected JSON structure from InfoJobs CLI")


def _run_plain(repo: Path, args: list[str], runner: Callable | None = None) -> str:
    proc = (runner or _default_runner)(repo, args)
    if proc.returncode != 0:
        raise RuntimeError(_clean(proc.stderr) or _clean(proc.stdout) or "InfoJobs detail CLI failed")
    return (proc.stdout or "").strip()


def _identity(item: dict[str, Any]) -> str:
    return _clean(item.get("id")) or _clean(item.get("url"))


def _merge_query(existing: str, query: str) -> str:
    parts = [p.strip() for p in (existing or "").split(";") if p.strip()]
    if query and query not in parts:
        parts.append(query)
    return "; ".join(parts)


def _make_job(item: dict[str, Any], query: str) -> dict:
    row = JobRecord(
        source=SOURCE_NAME,
        title=_clean(item.get("title")),
        company=_clean(item.get("company")),
        location=_clean(item.get("location")),
        date=_clean(item.get("date")),
        url=_clean(item.get("url")),
        id=_clean(item.get("id")),
        modality=_clean(item.get("modality")),
        description="InfoJobs current Spain-search result.",
        search_query=query,
    ).to_dict()
    row["search_scope"] = "Spain"
    return row


def classify_source_status(detail: str) -> tuple[str, str]:
    text = _clean(detail)
    if not text:
        return "", ""
    m = CLOSED_RE.search(text)
    if m:
        return "CLOSED", _clean(m.group(0))
    return "OPEN", "Returned by current InfoJobs search and Full JD resolved successfully"


def collect(
    diagnostics: dict | None = None,
    repo_path: str | Path | None = None,
    limit_per_search: int = 10,
    jobage_days: int = 1,
    max_jobs: int = 100,
    enrich_detail: bool = True,
    runner: Callable | None = None,
) -> list[dict]:
    """Collect InfoJobs through the existing Spain-fork infojobs-search CLI.

    Discovery/detail transport is delegated to the already-installed external CLI.
    This project retains canonical dedupe, availability/state handling and frozen
    V1.36 research-job fit scoring. Queries come from config/queries.json.
    """
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "source": SOURCE_NAME,
        "feed_mode": "spain_fork_infojobs_search_cli_adapter",
        "repo_path": "",
        "cli_path": str(CLI_RELATIVE),
        "repo_candidates_checked": [],
        "bun_available": bool(shutil.which("bun")) if runner is None else True,
        "limit_per_search": int(limit_per_search),
        "jobage_days": int(jobage_days),
        "queries_spain": 0,
        "search_attempts": 0,
        "search_success": 0,
        "search_failed": 0,
        "search_errors": [],
        "raw_results": 0,
        "unique_jobs": 0,
        "truncated": 0,
        "detail_attempts": 0,
        "detail_success": 0,
        "detail_failed": 0,
        "detail_status_counts": {},
        "source_status_open": 0,
        "source_status_closed": 0,
        "source_status_unknown": 0,
        "coverage_complete": False,
        "coverage_warning": "",
    })

    if runner is None and not shutil.which("bun"):
        diag["coverage_warning"] = "Bun is not available in PATH; InfoJobs CLI cannot run"
        return []

    repo, checked = resolve_repo(repo_path)
    diag["repo_candidates_checked"] = checked
    if repo is None:
        diag["coverage_warning"] = "Spain ai-job-search repo with infojobs-search CLI was not found"
        return []
    diag["repo_path"] = str(repo)

    queries = _load_queries()
    diag["queries_spain"] = len(queries)

    rows: list[dict] = []
    for query in queries:
        diag["search_attempts"] += 1
        args = [
            str(CLI_RELATIVE), "search",
            "-q", query,
            "--jobage", str(jobage_days),
            "--limit", str(limit_per_search),
            "--format", "json",
        ]
        try:
            payload = _run_json(repo, args, runner=runner)
            diag["search_success"] += 1
            for item in payload.get("results", []):
                if not isinstance(item, dict) or not _clean(item.get("title")):
                    continue
                rows.append(_make_job(item, query))
        except Exception as exc:
            diag["search_failed"] += 1
            diag["search_errors"].append({
                "query": query,
                "error": f"{type(exc).__name__}: {exc}",
            })

    diag["raw_results"] = len(rows)

    unique: list[dict] = []
    by_key: dict[str, dict] = {}
    for job in rows:
        key = _identity(job)
        if not key:
            key = "::".join([
                _clean(job.get("company")).lower(),
                _clean(job.get("title")).lower(),
                _clean(job.get("location")).lower(),
            ])
        if key not in by_key:
            by_key[key] = job
            unique.append(job)
        else:
            current = by_key[key]
            current["search_query"] = _merge_query(current.get("search_query", ""), job.get("search_query", ""))

    diag["unique_jobs"] = len(unique)
    if len(unique) > max_jobs:
        diag["truncated"] = len(unique) - max_jobs
        unique = unique[:max_jobs]

    if enrich_detail:
        for job in unique:
            identifier = _identity(job)
            if not identifier:
                job["full_detail"] = ""
                job["detail_status"] = "INFOJOBS_ID_MISSING"
                job["source_application_status"] = ""
                job["source_status_evidence"] = ""
                diag["detail_failed"] += 1
                diag["source_status_unknown"] += 1
                continue
            diag["detail_attempts"] += 1
            try:
                detail = _run_plain(
                    repo,
                    [str(CLI_RELATIVE), "detail", identifier, "--format", "plain"],
                    runner=runner,
                )
                if detail:
                    job["full_detail"] = detail
                    job["detail_status"] = "OK"
                    job["trusted_full_detail_source"] = SOURCE_NAME
                    job["trusted_full_detail_url"] = job.get("url", "")
                    app_status, evidence = classify_source_status(detail)
                    job["source_application_status"] = app_status
                    job["source_status_evidence"] = evidence
                    diag["detail_success"] += 1
                    if app_status == "OPEN":
                        diag["source_status_open"] += 1
                    elif app_status == "CLOSED":
                        diag["source_status_closed"] += 1
                    else:
                        diag["source_status_unknown"] += 1
                else:
                    job["full_detail"] = ""
                    job["detail_status"] = "INFOJOBS_DETAIL_EMPTY"
                    job["source_application_status"] = ""
                    job["source_status_evidence"] = ""
                    diag["detail_failed"] += 1
                    diag["source_status_unknown"] += 1
            except Exception as exc:
                job["full_detail"] = ""
                job["detail_status"] = "INFOJOBS_DETAIL_FAILED"
                job["detail_error"] = f"{type(exc).__name__}: {exc}"
                job["source_application_status"] = ""
                job["source_status_evidence"] = ""
                diag["detail_failed"] += 1
                diag["source_status_unknown"] += 1
            status = str(job.get("detail_status") or "")
            counts = diag["detail_status_counts"]
            counts[status] = int(counts.get(status, 0)) + 1

    if diag["search_failed"]:
        diag["coverage_warning"] = (
            f"InfoJobs search incomplete: {diag['search_failed']} of {diag['search_attempts']} queries failed"
        )
    elif diag["truncated"]:
        diag["coverage_warning"] = (
            f"InfoJobs candidate set truncated by max_jobs={max_jobs}; {diag['truncated']} job(s) not processed"
        )

    diag["coverage_complete"] = bool(
        diag["search_attempts"] > 0
        and diag["search_success"] == diag["search_attempts"]
        and diag["truncated"] == 0
    )
    return unique
