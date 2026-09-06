from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from jobbot.availability import assess_availability, resolve_as_of
from jobbot.dedupe import deduplicate
from jobbot.evaluate import evaluate_job
from jobbot.state import apply_seen_state, load_state
from jobbot.production import (
    FROZEN_ENGINE,
    PRODUCTION_VERSION,
    SOURCE_ORDER,
    assert_scoring_freeze,
    collect_sources,
)

ROOT = Path(__file__).resolve().parent
DURABLE_STATE_ENV = "JOBBOT_STATE_FILE"
DURABLE_STATE_DIRNAME = ".job-search-bot"


def _state_path_from_value(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path


def resolve_state_path(value: str | None, root: Path = ROOT) -> tuple[Path, dict]:
    """Resolve production state independently of the extracted code version.

    Explicit --state-file remains fully backward compatible. If it is omitted, an
    environment override is honored; otherwise state lives under the user's home
    directory so extracting V1.63/V1.64/... cannot silently reset NEW/SEEN history.
    """
    if value:
        return _state_path_from_value(value, root), {"mode": "explicit", "env": ""}

    env_value = str(os.environ.get(DURABLE_STATE_ENV) or "").strip()
    if env_value:
        path = Path(env_value).expanduser()
        if not path.is_absolute():
            path = Path.home() / path
        return path, {"mode": "env", "env": DURABLE_STATE_ENV}

    return Path.home() / DURABLE_STATE_DIRNAME / "seen_jobs.json", {
        "mode": "durable_default",
        "env": "",
    }


def _legacy_state_candidates(root: Path, target: Path) -> list[Path]:
    """Find legacy per-version state files created by V1.38-V1.61 packages."""
    candidates: list[Path] = []
    direct = root / "state" / "seen_jobs.json"
    if direct.exists():
        candidates.append(direct)

    parent = root.parent
    for candidate in sorted(parent.glob("job-search-bot-v*/state/seen_jobs.json")):
        if candidate.exists():
            candidates.append(candidate)

    out: list[Path] = []
    seen: set[str] = set()
    try:
        target_key = str(target.resolve())
    except OSError:
        target_key = str(target.absolute())
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
        except OSError:
            key = str(candidate.absolute())
        if key == target_key or key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def inspect_state_storage(value: str | None, root: Path = ROOT) -> dict:
    """Report durable/legacy state readiness without collection or mutation."""
    target, meta = resolve_state_path(value, root)
    report = {
        "production_version": PRODUCTION_VERSION,
        "state_file": str(target),
        "state_storage_mode": meta.get("mode", ""),
        "state_exists": target.exists(),
        "state_updated_at": "",
        "state_jobs": 0,
        "legacy_candidates": [],
        "would_migrate_from": "",
    }
    if target.exists():
        data = load_state(target)
        report["state_updated_at"] = str(data.get("updated_at") or "")
        report["state_jobs"] = len(data.get("jobs") or {})
        return report

    if meta.get("mode") != "durable_default":
        return report

    valid: list[tuple[tuple[str, int, float], Path]] = []
    for candidate in _legacy_state_candidates(root, target):
        item = {"path": str(candidate), "valid": False, "updated_at": "", "jobs": 0, "error": ""}
        try:
            data = load_state(candidate)
            item["valid"] = True
            item["updated_at"] = str(data.get("updated_at") or "")
            item["jobs"] = len(data.get("jobs") or {})
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                mtime = 0.0
            valid.append(((item["updated_at"], item["jobs"], mtime), candidate))
        except RuntimeError as exc:
            item["error"] = str(exc)
        report["legacy_candidates"].append(item)

    if valid:
        report["would_migrate_from"] = str(max(valid, key=lambda item: item[0])[1])
    return report


def bootstrap_durable_state(target: Path, root: Path = ROOT) -> dict:
    """Migrate the best valid legacy state once, without mutating the legacy copy.

    Preference is latest `updated_at`, then larger state, then filesystem mtime. This
    matches the monotonic production-state model while retaining the old file as a
    rollback/audit copy. If legacy files exist but none is valid, fail closed instead
    of silently reseeding every current vacancy as NEW.
    """
    result = {
        "attempted": False,
        "migrated": False,
        "migrated_from": "",
        "legacy_candidates": 0,
        "invalid_candidates": [],
    }
    if target.exists():
        return result

    candidates = _legacy_state_candidates(root, target)
    result["legacy_candidates"] = len(candidates)
    if not candidates:
        return result
    result["attempted"] = True

    valid: list[tuple[tuple[str, int, float], Path, dict]] = []
    for candidate in candidates:
        try:
            data = load_state(candidate)
            updated_at = str(data.get("updated_at") or "")
            jobs = data.get("jobs") or {}
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                mtime = 0.0
            valid.append(((updated_at, len(jobs), mtime), candidate, data))
        except RuntimeError as exc:
            result["invalid_candidates"].append({"path": str(candidate), "error": str(exc)})

    if not valid:
        raise RuntimeError(
            "Legacy seen-state files were found but none was valid; refusing to reset production history. "
            "Use --state-file with a known-good state file or repair/remove the corrupt legacy files."
        )

    _, source, data = max(valid, key=lambda item: item[0])
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".migrate.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp, target)
    result["migrated"] = True
    result["migrated_from"] = str(source)
    return result


def _csv_value(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def write_csv(path: Path, rows: list[dict], fallback_rows: list[dict] | None = None) -> None:
    keys = []
    for row in (rows or fallback_rows or []):
        for key in row:
            if key not in keys:
                keys.append(key)
    if not keys:
        keys = ["source", "title", "company", "location", "score", "recommendation", "reason"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: _csv_value(v) for k, v in row.items()})


def _has_full_detail(job: dict) -> bool:
    status = str(job.get("detail_status") or "")
    detail = str(job.get("full_detail") or "").strip()
    return bool(detail) and status in {"OK_HTML", "OK_PDF", "OK_PDF_ATTACHMENT", "OK_ATTACHMENT", "CACHE", "OK"}




def _availability_input(job: dict) -> dict:
    """Use source-authoritative availability text without altering scoring input.

    ISCIII call PDFs contain many procedural date ranges. The official portal/detail
    page already supplies the actual application-window end date, so scanning the
    entire PDF for availability creates false deadline conflicts (often capturing
    the start of the application window). Scoring still receives the untouched JD.
    """
    if str(job.get("source") or "").lower().startswith("isciii employment"):
        return {**job, "full_detail": ""}
    return job


def _assess_job_availability(job: dict, availability_day) -> dict:
    """Apply the frozen generic parser, then a source-authoritative status if needed.

    Some official boards publish a reliable status marker but no explicit application
    deadline. Collectors may expose that evidence as `source_application_status`. The
    generic frozen availability parser keeps precedence whenever it found an explicit
    deadline/status; the source marker is used only when the generic result is UNKNOWN.
    """
    result = assess_availability(_availability_input(job), availability_day)
    if result.get("application_status") != "UNKNOWN":
        return result

    source_status = str(job.get("source_application_status") or "").strip().upper()
    if source_status not in {"OPEN", "CLOSED", "OPEN_UNTIL_FILLED"}:
        return result

    evidence = str(job.get("source_status_evidence") or "").strip()
    return {
        **result,
        "application_status": source_status,
        "deadline_evidence": evidence or "Source-authoritative application status",
    }

def _recommendation_rank(row: dict) -> tuple[int, int, str]:
    ranks = {"STRONG_APPLY": 0, "APPLY": 1, "REVIEW": 2, "LOW_PRIORITY": 3, "NEEDS_DETAIL_REVIEW": 4, "SKIP": 5}
    score = row.get("score")
    try:
        score_num = int(score)
    except (TypeError, ValueError):
        score_num = -1
    return (ranks.get(str(row.get("recommendation") or ""), 99), -score_num, str(row.get("title") or ""))


def _row_sources(row: dict) -> set[str]:
    """Return normalized provenance source labels for one canonical row."""
    provenance = row.get("source_provenance") or []
    names = {str(p.get("source") or "").strip() for p in provenance if isinstance(p, dict)}
    names.discard("")
    if not names:
        names = {part.strip() for part in str(row.get("source") or "").split("+") if part.strip()}
    return names


def _is_actionable_for_coverage(row: dict) -> bool:
    return row.get("recommendation") != "SKIP" and row.get("application_status") != "CLOSED"


def build_coverage_audit(all_canonical: list[dict], source_runs: dict[str, dict]) -> dict:
    """Measure each configured source's post-dedupe marginal contribution.

    `exclusive_*` counts are the true one-run marginal contribution under the current
    conservative cross-source dedupe: removing that source would remove those rows from
    this observed scan. Overlap counts are jobs also seen by at least one other source.
    This is reporting only and does not alter identity, scoring, or availability.
    """
    labels = [(key, str(info.get("source") or key).strip()) for key, info in source_runs.items()]
    recognized = {label for _, label in labels if label}
    source_sets = [_row_sources(row) for row in all_canonical]

    per_source: dict[str, dict] = {}
    for key, label in labels:
        covered_idx = [i for i, names in enumerate(source_sets) if label in names]
        exclusive_idx = [i for i in covered_idx if source_sets[i] == {label}]
        overlap_idx = [i for i in covered_idx if len(source_sets[i]) > 1]
        actionable_idx = [i for i in covered_idx if _is_actionable_for_coverage(all_canonical[i])]
        exclusive_actionable_idx = [i for i in exclusive_idx if _is_actionable_for_coverage(all_canonical[i])]
        overlap_actionable_idx = [i for i in overlap_idx if _is_actionable_for_coverage(all_canonical[i])]

        partner_counts: dict[str, int] = {}
        partner_actionable_counts: dict[str, int] = {}
        for i in overlap_idx:
            for other in sorted(source_sets[i] - {label}):
                partner_counts[other] = partner_counts.get(other, 0) + 1
                if _is_actionable_for_coverage(all_canonical[i]):
                    partner_actionable_counts[other] = partner_actionable_counts.get(other, 0) + 1

        per_source[key] = {
            "source": label,
            "canonical_covered": len(covered_idx),
            "exclusive_canonical": len(exclusive_idx),
            "overlapping_canonical": len(overlap_idx),
            "marginal_unique_canonical": len(exclusive_idx),
            "exclusive_canonical_share": round(len(exclusive_idx) / len(covered_idx), 4) if covered_idx else 0.0,
            "actionable_covered": len(actionable_idx),
            "exclusive_actionable": len(exclusive_actionable_idx),
            "overlapping_actionable": len(overlap_actionable_idx),
            "marginal_unique_actionable": len(exclusive_actionable_idx),
            "exclusive_actionable_share": round(len(exclusive_actionable_idx) / len(actionable_idx), 4) if actionable_idx else 0.0,
            "exclusive_apply_or_strong": sum(
                all_canonical[i].get("recommendation") in {"STRONG_APPLY", "APPLY"}
                for i in exclusive_actionable_idx
            ),
            "exclusive_review": sum(all_canonical[i].get("recommendation") == "REVIEW" for i in exclusive_actionable_idx),
            "exclusive_low": sum(all_canonical[i].get("recommendation") == "LOW_PRIORITY" for i in exclusive_actionable_idx),
            "exclusive_detail_review": sum(all_canonical[i].get("recommendation") == "NEEDS_DETAIL_REVIEW" for i in exclusive_actionable_idx),
            "overlap_partners": partner_counts,
            "actionable_overlap_partners": partner_actionable_counts,
        }

    pairwise = []
    for pos, (key_a, label_a) in enumerate(labels):
        for key_b, label_b in labels[pos + 1:]:
            overlap_idx = [i for i, names in enumerate(source_sets) if label_a in names and label_b in names]
            if not overlap_idx:
                continue
            pairwise.append({
                "source_a_key": key_a,
                "source_a": label_a,
                "source_b_key": key_b,
                "source_b": label_b,
                "canonical_overlap": len(overlap_idx),
                "actionable_overlap": sum(_is_actionable_for_coverage(all_canonical[i]) for i in overlap_idx),
            })
    pairwise.sort(key=lambda r: (-int(r["canonical_overlap"]), -int(r["actionable_overlap"]), r["source_a"], r["source_b"]))

    multi_idx = [i for i, names in enumerate(source_sets) if len(names) > 1]
    actionable_all_idx = [i for i, row in enumerate(all_canonical) if _is_actionable_for_coverage(row)]
    multi_actionable_idx = [i for i in multi_idx if _is_actionable_for_coverage(all_canonical[i])]
    unattributed_idx = [i for i, names in enumerate(source_sets) if not (names & recognized)]

    return {
        "aggregate": {
            "canonical_total": len(all_canonical),
            "single_source_canonical": len(all_canonical) - len(multi_idx),
            "multi_source_canonical": len(multi_idx),
            "actionable_total": len(actionable_all_idx),
            "single_source_actionable": len(actionable_all_idx) - len(multi_actionable_idx),
            "multi_source_actionable": len(multi_actionable_idx),
            "unattributed_canonical": len(unattributed_idx),
            "sources_measured": len(labels),
        },
        "per_source": per_source,
        "pairwise_overlaps": pairwise,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Production job-search orchestration with frozen V1.36 research scoring")
    p.add_argument("--source", choices=[*SOURCE_ORDER, "both", "all"], default="both")
    p.add_argument("--linkedin-repo", default="", help="Optional path to the Mads ai-job-search repo; auto-detected from ~/Documents when omitted")
    p.add_argument("--linkedin-limit-per-search", type=int, default=10)
    p.add_argument("--linkedin-jobage-minutes", type=int, default=36 * 60)
    p.add_argument("--linkedin-max-jobs", type=int, default=120)
    p.add_argument("--linkedin-spain-only", action="store_true", help="Deprecated compatibility flag; production is Spain-only from V1.87")
    p.add_argument("--infojobs-repo", default="", help="Optional path to the Spain ai-job-search repo; auto-detected from ~/Documents when omitted")
    p.add_argument("--infojobs-limit-per-search", type=int, default=10)
    p.add_argument("--infojobs-jobage-days", type=int, default=1)
    p.add_argument("--infojobs-max-jobs", type=int, default=100)
    p.add_argument("--academicpositions-max-jobs", type=int, default=80)
    p.add_argument("--ikerbasque-max-calls", type=int, default=20)
    p.add_argument("--atswatch-max-jobs-per-employer", type=int, default=100)
    p.add_argument("--santpau-pages", type=int, default=3)
    p.add_argument("--santpau-max-jobs", type=int, default=60)
    p.add_argument("--fbg-max-jobs", type=int, default=50)
    p.add_argument("--gencat-max-jobs", type=int, default=100)
    p.add_argument("--csic-pages", type=int, default=3)
    p.add_argument("--csic-max-jobs", type=int, default=100)
    p.add_argument("--isciii-pages", type=int, default=1, help="ISCIII reliable default: newest page only; increase explicitly for diagnostic/deep scans")
    p.add_argument("--isciii-max-jobs", type=int, default=60)
    p.add_argument("--idibaps-max-jobs", type=int, default=100)
    p.add_argument("--upc-max-jobs", type=int, default=80)
    p.add_argument("--idibell-max-jobs", type=int, default=80)
    p.add_argument("--hospitaldelmar-max-jobs", type=int, default=100)
    p.add_argument("--bist-max-jobs", type=int, default=100)
    p.add_argument("--bist-max-pages", type=int, default=5)
    p.add_argument("--institution-max-pages", type=int, default=4)
    p.add_argument("--institution-max-jobs-per-board", type=int, default=100)
    p.add_argument("--fisabio-max-jobs", type=int, default=50)
    p.add_argument("--fps-max-jobs", type=int, default=50)
    p.add_argument("--iislafe-pages", type=int, default=3)
    p.add_argument("--iislafe-max-jobs", type=int, default=30)
    p.add_argument("--madrid-pages", type=int, default=10)
    p.add_argument("--madrid-max-jobs", type=int, default=100)
    p.add_argument("--madrid-detail-workers", type=int, default=6)
    p.add_argument("--euraxess-pages", type=int, default=8)
    p.add_argument("--euraxess-max-candidates", type=int, default=80)
    p.add_argument("--history-days", type=int, default=None)
    p.add_argument("--history-max-pages", type=int, default=40)
    p.add_argument("--history-max-candidates", type=int, default=250)
    p.add_argument("--detail-delay", type=float, default=None)
    p.add_argument("--as-of", default=None, help="Optional reproducible date YYYY-MM-DD; defaults to today")
    p.add_argument("--out", default="live_output")
    p.add_argument("--state-file", default=None, help="Persistent seen/history state file. Omit for durable user-level state (~/.job-search-bot/seen_jobs.json); used only with --source all")
    p.add_argument("--no-state", action="store_true", help="Disable persistent seen/history state for this run")
    p.add_argument("--state-preflight", action="store_true", help="Inspect durable/legacy state readiness without collecting jobs or mutating state")
    return p


def run(args) -> dict:
    freeze_check = assert_scoring_freeze(ROOT)
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    collected = collect_sources(args, out)
    jobs = collected["jobs"]
    unique, dupes = deduplicate(jobs)
    availability_day = resolve_as_of(args.as_of)
    unique = [{**job, **_assess_job_availability(job, availability_day)} for job in unique]

    evaluated: list[dict] = []
    needs_detail: list[dict] = []
    for job in unique:
        if _has_full_detail(job):
            if not job.get("trusted_full_detail_source"):
                job["trusted_full_detail_source"] = job.get("source")
                job["trusted_full_detail_url"] = job.get("url")
            ev = evaluate_job(job)
            evaluated.append({**job, **ev})
        else:
            needs_detail.append({
                **job,
                "score": "",
                "recommendation": "NEEDS_DETAIL_REVIEW",
                "domain_category": "",
                "job_family": "",
                "fit_signals": [],
                "partial_matches": ["Full Job Description unavailable; deterministic scoring not run"],
                "missing_requirements": [],
                "blockers": [],
                "reason": f"Detail status: {job.get('detail_status') or 'missing'}",
            })

    evaluated.sort(key=lambda r: (-int(r.get("score", 0)), str(r.get("title") or "")))
    needs_detail.sort(key=lambda r: (str(r.get("title") or ""), str(r.get("company") or "")))
    all_canonical = sorted([*evaluated, *needs_detail], key=_recommendation_rank)

    # Persistent state is a production concern, not a collector/calibration concern.
    # Enable it by default only for the unified daily --source all run so source-specific
    # debugging cannot accidentally consume NEW jobs or mutate global history.
    state_enabled = (args.source == "all") and not bool(args.history_days) and not bool(getattr(args, "no_state", False))
    state_stats = {
        "NEW": 0, "SEEN": 0, "MATERIALLY_CHANGED": 0, "REOPENED": 0,
        "DETAIL_RESOLVED": 0, "DETAIL_UNRESOLVED": 0, "state_jobs": 0,
    }
    state_path, state_path_meta = resolve_state_path(getattr(args, "state_file", None), ROOT)
    state_migration = {
        "attempted": False, "migrated": False, "migrated_from": "",
        "legacy_candidates": 0, "invalid_candidates": [],
    }
    if state_enabled:
        if state_path_meta.get("mode") == "durable_default":
            state_migration = bootstrap_durable_state(state_path, ROOT)
        state_stats = apply_seen_state(all_canonical, state_path, availability_day.isoformat())
    else:
        for row in all_canonical:
            row["seen_status"] = "STATE_DISABLED"
            row["change_reasons"] = []
            row["state_events"] = []
            row["first_seen"] = ""
            row["last_seen"] = ""
            row["times_seen"] = ""
            row["state_id"] = ""

    # Re-derive views after history annotation so every output carries the same state metadata.
    evaluated = [r for r in all_canonical if r.get("recommendation") != "NEEDS_DETAIL_REVIEW"]
    needs_detail = [r for r in all_canonical if r.get("recommendation") == "NEEDS_DETAIL_REVIEW"]
    primary = [r for r in evaluated if r["recommendation"] in {"STRONG_APPLY", "APPLY", "REVIEW"}]
    low = [r for r in evaluated if r["recommendation"] == "LOW_PRIORITY"]
    skipped = [r for r in evaluated if r["recommendation"] == "SKIP"]
    closed = [r for r in all_canonical if r.get("application_status") == "CLOSED"]
    actionable_primary = [r for r in primary if r.get("application_status") != "CLOSED"]
    actionable_low = [r for r in low if r.get("application_status") != "CLOSED"]
    actionable_detail_review = [r for r in needs_detail if r.get("application_status") != "CLOSED"]
    actionable = sorted([*actionable_primary, *actionable_low, *actionable_detail_review], key=_recommendation_rank)
    daily_statuses = {"NEW", "MATERIALLY_CHANGED", "REOPENED"}
    detail_resolved_rows = [r for r in all_canonical if "DETAIL_RESOLVED" in (r.get("state_events") or [])]
    detail_unresolved_rows = [r for r in all_canonical if "DETAIL_UNRESOLVED" in (r.get("state_events") or [])]
    # A resolution-quality recovery is not a vacancy change. Still surface it once if
    # the newly resolved job is actionable, so a formerly unscored opportunity is not lost.
    daily_actionable = [
        r for r in actionable
        if r.get("seen_status") in daily_statuses
        or "DETAIL_RESOLVED" in (r.get("state_events") or [])
    ]
    new_actionable = [r for r in actionable if r.get("seen_status") == "NEW"]
    changed_or_reopened = [r for r in all_canonical if r.get("seen_status") in {"MATERIALLY_CHANGED", "REOPENED"}]
    seen_unchanged = [
        r for r in all_canonical
        if r.get("seen_status") == "SEEN" and not (r.get("state_events") or [])
    ]
    state_quality_events = [r for r in all_canonical if r.get("state_events")]

    # Backward-compatible outputs plus production-oriented aggregate views.
    write_csv(out / "all_evaluated.csv", evaluated)
    write_csv(out / "primary.csv", primary, fallback_rows=evaluated)
    write_csv(out / "low.csv", low, fallback_rows=evaluated)
    write_csv(out / "skipped.csv", skipped, fallback_rows=evaluated)
    write_csv(out / "needs_detail_review.csv", needs_detail, fallback_rows=evaluated)
    write_csv(out / "closed.csv", closed, fallback_rows=evaluated)
    write_csv(out / "actionable_primary.csv", actionable_primary, fallback_rows=evaluated)
    write_csv(out / "actionable_low.csv", actionable_low, fallback_rows=evaluated)
    write_csv(out / "euraxess_card_audit.csv", collected["euraxess_audit"])
    write_csv(out / "all_canonical.csv", all_canonical, fallback_rows=evaluated)
    write_csv(out / "actionable.csv", actionable, fallback_rows=all_canonical)
    write_csv(out / "daily_actionable.csv", daily_actionable, fallback_rows=actionable)
    write_csv(out / "new_actionable.csv", new_actionable, fallback_rows=actionable)
    write_csv(out / "changed_or_reopened.csv", changed_or_reopened, fallback_rows=all_canonical)
    write_csv(out / "seen_unchanged.csv", seen_unchanged, fallback_rows=all_canonical)
    write_csv(out / "state_quality_events.csv", state_quality_events, fallback_rows=all_canonical)

    # Enrich collection diagnostics with canonical/scoring/availability counts. A
    # cross-source duplicate is counted once in aggregate and may appear in each
    # contributing source's diagnostic row via provenance.
    for key, run_info in collected["source_runs"].items():
        label = str(run_info.get("source") or "")
        src_rows = [r for r in all_canonical if label in _row_sources(r)]
        src_eval = [r for r in src_rows if r.get("recommendation") != "NEEDS_DETAIL_REVIEW"]
        run_info.update({
            "canonical_jobs": len(src_rows),
            "evaluated": len(src_eval),
            "needs_detail_review": sum(r.get("recommendation") == "NEEDS_DETAIL_REVIEW" for r in src_rows),
            "strong_apply": sum(r.get("recommendation") == "STRONG_APPLY" for r in src_rows),
            "apply": sum(r.get("recommendation") == "APPLY" for r in src_rows),
            "review": sum(r.get("recommendation") == "REVIEW" for r in src_rows),
            "primary": sum(r.get("recommendation") in {"STRONG_APPLY", "APPLY", "REVIEW"} for r in src_rows),
            "low": sum(r.get("recommendation") == "LOW_PRIORITY" for r in src_rows),
            "skip": sum(r.get("recommendation") == "SKIP" for r in src_rows),
            "open": sum(r.get("application_status") == "OPEN" for r in src_rows),
            "open_until_filled": sum(r.get("application_status") == "OPEN_UNTIL_FILLED" for r in src_rows),
            "closed": sum(r.get("application_status") == "CLOSED" for r in src_rows),
            "availability_unknown": sum(r.get("application_status") == "UNKNOWN" for r in src_rows),
            "actionable": sum(r.get("recommendation") != "SKIP" and r.get("application_status") != "CLOSED" for r in src_rows),
        })

    coverage_audit = build_coverage_audit(all_canonical, collected["source_runs"])
    for key, metrics in coverage_audit["per_source"].items():
        if key in collected["source_runs"]:
            collected["source_runs"][key].update({
                "exclusive_canonical": metrics["exclusive_canonical"],
                "overlapping_canonical": metrics["overlapping_canonical"],
                "marginal_unique_canonical": metrics["marginal_unique_canonical"],
                "exclusive_actionable": metrics["exclusive_actionable"],
                "overlapping_actionable": metrics["overlapping_actionable"],
                "marginal_unique_actionable": metrics["marginal_unique_actionable"],
            })

    source_summary_rows = [{"source_key": key, **run_info} for key, run_info in collected["source_runs"].items()]
    write_csv(out / "source_summary.csv", source_summary_rows)
    coverage_rows = [{"source_key": key, **metrics} for key, metrics in coverage_audit["per_source"].items()]
    write_csv(out / "coverage_contribution.csv", coverage_rows)
    write_csv(
        out / "source_overlap.csv",
        coverage_audit["pairwise_overlaps"],
        fallback_rows=[{
            "source_a_key": "", "source_a": "", "source_b_key": "", "source_b": "",
            "canonical_overlap": 0, "actionable_overlap": 0,
        }],
    )
    (out / "coverage_audit.json").write_text(json.dumps(coverage_audit, indent=2, ensure_ascii=False), encoding="utf-8")

    configured_scan_complete = bool(collected["source_runs"]) and all(
        r["status"] == "OK" for r in collected["source_runs"].values()
    )
    rec_counts = {
        name: sum(r.get("recommendation") == name for r in evaluated)
        for name in ("STRONG_APPLY", "APPLY", "REVIEW", "LOW_PRIORITY", "SKIP")
    }
    summary = {
        "production_version": PRODUCTION_VERSION,
        "scoring_engine": FROZEN_ENGINE,
        "scoring_freeze_check": freeze_check,
        "configured_sources": collected["selected_sources"],
        "coverage_scope": "CONFIGURED_SOURCE_SCAN_ONLY",
        "whole_market_coverage_claimed": False,
        "configured_scan_complete": configured_scan_complete,
        "calibration_mode": bool(args.history_days),
        "history_days": args.history_days,
        "as_of": args.as_of,
        "availability_as_of": availability_day.isoformat(),
        "raw": len(jobs),
        "unique": len(unique),
        "duplicates_removed": dupes,
        "errors": collected["errors"],
        "warnings": collected["warnings"],
        "evaluated": len(evaluated),
        "needs_detail_review": len(needs_detail),
        "recommendations": rec_counts,
        "primary": len(primary),
        "low": len(low),
        "skip": len(skipped),
        "open": sum(r.get("application_status") == "OPEN" for r in all_canonical),
        "open_until_filled": sum(r.get("application_status") == "OPEN_UNTIL_FILLED" for r in all_canonical),
        "closed": len(closed),
        "availability_unknown": sum(r.get("application_status") == "UNKNOWN" for r in all_canonical),
        "deadline_conflicts": sum(bool(r.get("deadline_conflict")) for r in all_canonical),
        "actionable_primary": len(actionable_primary),
        "actionable_low": len(actionable_low),
        "actionable_total_including_detail_review": len(actionable),
        "seen_state_enabled": state_enabled,
        "state_file": str(state_path.relative_to(ROOT) if state_path.is_relative_to(ROOT) else state_path),
        "state_storage_mode": state_path_meta.get("mode", ""),
        "state_migrated_from": state_migration.get("migrated_from", ""),
        "state_migration_attempted": bool(state_migration.get("attempted")),
        "state_migration_legacy_candidates": int(state_migration.get("legacy_candidates", 0) or 0),
        "state_migration_invalid_candidates": state_migration.get("invalid_candidates", []),
        "state_disabled_reason": "" if state_enabled else ("calibration_mode" if args.history_days else "explicit_no_state" if getattr(args, "no_state", False) else "source_subset_run"),
        "new_canonical": state_stats.get("NEW", 0),
        "seen_unchanged": len(seen_unchanged),
        "seen_with_quality_event": sum(r.get("seen_status") == "SEEN" and bool(r.get("state_events")) for r in all_canonical),
        "materially_changed": state_stats.get("MATERIALLY_CHANGED", 0),
        "reopened": state_stats.get("REOPENED", 0),
        "detail_resolved": state_stats.get("DETAIL_RESOLVED", 0),
        "detail_unresolved": state_stats.get("DETAIL_UNRESOLVED", 0),
        "seen_state_jobs": state_stats.get("state_jobs", 0),
        "current_actionable": len(actionable),
        "daily_actionable": len(daily_actionable),
        "new_actionable": len(new_actionable),
        "detail_resolved_actionable": sum(
            r.get("application_status") != "CLOSED" and r.get("recommendation") != "SKIP"
            for r in detail_resolved_rows
        ),
        "changed_or_reopened_actionable": sum(r.get("application_status") != "CLOSED" and r.get("recommendation") != "SKIP" for r in changed_or_reopened),
        "coverage_audit": {
            "aggregate": coverage_audit["aggregate"],
            "per_source": coverage_audit["per_source"],
            "top_pairwise_overlaps": coverage_audit["pairwise_overlaps"][:10],
        },
        "source_runs": collected["source_runs"],
        "source_diagnostics": collected["diagnostics"],
    }
    (out / "run_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "collector_diagnostics.json").write_text(json.dumps(collected["diagnostics"], indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def main() -> None:
    args = build_parser().parse_args()
    if getattr(args, "state_preflight", False):
        print(json.dumps(inspect_state_storage(getattr(args, "state_file", None), ROOT), indent=2, ensure_ascii=False))
        return
    summary = run(args)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
