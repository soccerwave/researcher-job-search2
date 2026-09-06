from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable

from sources import academicpositions, ats_watchlist, biocat, bist, csic_institutes, euraxess, fbg_ub, fisabio, fps_andalucia, gencat_research, hospital_del_mar, idibell, iislafe, ikerbasque_calls, infojobs_spain, institutions, isciii_employment, linkedin_mads, madrid_idi, sant_pau_research, idibaps, upc_talenthub

FROZEN_ENGINE = "V1.36_FINAL_SCORING_CLEANUP"
PRODUCTION_VERSION = "V1.87_SPAIN_ONLY_SCOPE"
FREEZE_MANIFEST = "SCORING_FREEZE_V136.json"
SOURCE_ORDER = ("linkedin", "infojobs", "academicpositions", "ikerbasque", "atswatch", "santpau", "fbg", "biocat", "gencat", "csic", "isciii", "idibaps", "upc", "idibell", "hospitaldelmar", "euraxess", "bist", "institutions", "madrid", "fisabio", "fps", "iislafe")
SOURCE_LABELS = {
    "linkedin": "LinkedIn",
    "infojobs": "InfoJobs",
    "academicpositions": "AcademicPositions",
    "ikerbasque": "Ikerbasque Calls",
    "atswatch": "Research Employer ATS Watchlist",
    "santpau": "IR Sant Pau",
    "fbg": "Fundació Bosch i Gimpera (UB)",
    "biocat": "Biocat",
    "gencat": "Gencat Research Staff",
    "csic": "CSIC Barcelona Institutes",
    "isciii": "ISCIII Employment",
    "idibaps": "FRCB-IDIBAPS Job Offers",
    "upc": "UPC Talent Hub",
    "idibell": "IDIBELL Job Offers",
    "hospitaldelmar": "Hospital del Mar Research Institute",
    "euraxess": "EURAXESS",
    "bist": "BIST",
    "institutions": "Institutions",
    "madrid": "Madrid I+D+i",
    "fisabio": "FISABIO",
    "fps": "Fundación Progreso y Salud",
    "iislafe": "IIS La Fe",
}


def verify_scoring_freeze(root: Path) -> dict:
    manifest_path = root / FREEZE_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_engine = str(manifest.get("scoring_engine") or "")
    mismatches = []
    checked = []
    for relative, meta in (manifest.get("sha256") or {}).items():
        path = root / relative
        expected = str((meta or "") if isinstance(meta, str) else meta.get("sha256", ""))
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"
        checked.append(relative)
        if actual != expected:
            mismatches.append({"file": relative, "expected": expected, "actual": actual})
    if expected_engine != FROZEN_ENGINE:
        mismatches.append({"file": FREEZE_MANIFEST, "expected_engine": FROZEN_ENGINE, "actual_engine": expected_engine})
    return {
        "ok": not mismatches,
        "manifest": FREEZE_MANIFEST,
        "scoring_engine": expected_engine,
        "files_checked": checked,
        "mismatches": mismatches,
    }


def assert_scoring_freeze(root: Path) -> dict:
    result = verify_scoring_freeze(root)
    if not result["ok"]:
        details = "; ".join(f"{m.get('file')}: {m.get('actual', m.get('actual_engine'))}" for m in result["mismatches"])
        raise RuntimeError(f"Frozen V1.36 scoring integrity check failed: {details}")
    return result


def selected_sources(source: str) -> list[str]:
    if source == "all":
        return list(SOURCE_ORDER)
    if source == "both":
        return ["biocat", "euraxess"]
    if source not in SOURCE_ORDER:
        raise ValueError(f"Unknown source: {source}")
    return [source]


def _collector_map(overrides: dict[str, Callable] | None = None) -> dict[str, Callable]:
    collectors = {
        "linkedin": linkedin_mads.collect,
        "infojobs": infojobs_spain.collect,
        "academicpositions": academicpositions.collect,
        "ikerbasque": ikerbasque_calls.collect,
        "atswatch": ats_watchlist.collect,
        "santpau": sant_pau_research.collect,
        "fbg": fbg_ub.collect,
        "biocat": biocat.collect,
        "gencat": gencat_research.collect,
        "csic": csic_institutes.collect,
        "isciii": isciii_employment.collect,
        "idibaps": idibaps.collect,
        "upc": upc_talenthub.collect,
        "idibell": idibell.collect,
        "hospitaldelmar": hospital_del_mar.collect,
        "euraxess": euraxess.collect,
        "bist": bist.collect,
        "institutions": institutions.collect,
        "madrid": madrid_idi.collect,
        "fisabio": fisabio.collect,
        "fps": fps_andalucia.collect,
        "iislafe": iislafe.collect,
    }
    if overrides:
        collectors.update(overrides)
    return collectors


def _kwargs_for_source(key: str, args, out_dir: Path, euraxess_audit: list[dict]) -> dict:
    if key == "linkedin":
        return {
            "repo_path": getattr(args, "linkedin_repo", "") or None,
            "limit_per_search": getattr(args, "linkedin_limit_per_search", 10),
            "jobage_minutes": getattr(args, "linkedin_jobage_minutes", 36 * 60),
            "max_jobs": getattr(args, "linkedin_max_jobs", 120),
            # V1.87 policy: Spain only. Remote-Europe discovery is disabled in production.
            "include_remote_europe": False,
        }
    if key == "infojobs":
        return {
            "repo_path": getattr(args, "infojobs_repo", "") or None,
            "limit_per_search": getattr(args, "infojobs_limit_per_search", 10),
            "jobage_days": getattr(args, "infojobs_jobage_days", 1),
            "max_jobs": getattr(args, "infojobs_max_jobs", 100),
        }
    if key == "academicpositions":
        return {"max_jobs": getattr(args, "academicpositions_max_jobs", 80)}
    if key == "ikerbasque":
        return {"max_calls": getattr(args, "ikerbasque_max_calls", 20)}
    if key == "atswatch":
        return {"max_jobs_per_employer": getattr(args, "atswatch_max_jobs_per_employer", 100)}
    if key == "santpau":
        return {"max_pages": getattr(args, "santpau_pages", 3), "max_jobs": getattr(args, "santpau_max_jobs", 60)}
    if key == "fbg":
        return {"max_jobs": getattr(args, "fbg_max_jobs", 50)}
    if key == "euraxess":
        historical = bool(args.history_days)
        return {
            "query": "taxonomy_scan",
            "pages": args.history_max_pages if historical else args.euraxess_pages,
            "max_candidates": args.history_max_candidates if historical else args.euraxess_max_candidates,
            "audit_rows": euraxess_audit,
            "history_days": args.history_days,
            "as_of": args.as_of,
            "detail_request_delay": args.detail_delay,
        }
    if key == "gencat":
        return {"max_jobs": args.gencat_max_jobs}
    if key == "csic":
        return {"max_jobs": args.csic_max_jobs}
    if key == "isciii":
        return {"max_pages": args.isciii_pages, "max_jobs": args.isciii_max_jobs}
    if key == "idibaps":
        return {"max_jobs": args.idibaps_max_jobs}
    if key == "upc":
        return {"max_jobs": args.upc_max_jobs}
    if key == "idibell":
        return {"max_jobs": args.idibell_max_jobs}
    if key == "hospitaldelmar":
        return {"max_jobs": args.hospitaldelmar_max_jobs}
    if key == "bist":
        return {"max_pages": args.bist_max_pages, "max_jobs": args.bist_max_jobs}
    if key == "institutions":
        return {"max_pages": args.institution_max_pages, "max_jobs_per_board": args.institution_max_jobs_per_board}
    if key == "madrid":
        return {"max_pages": args.madrid_pages, "max_jobs": args.madrid_max_jobs,
                "detail_workers": args.madrid_detail_workers,
                "debug_html_path": str(out_dir / "madrid_first_page_debug.html")}
    if key == "fisabio":
        return {"max_jobs": args.fisabio_max_jobs}
    if key == "fps":
        return {"max_jobs": args.fps_max_jobs}
    if key == "iislafe":
        return {"max_pages": args.iislafe_pages, "max_jobs": args.iislafe_max_jobs}
    return {}


def _coverage_complete(key: str, diag: dict, args) -> bool:
    if key in {"linkedin", "infojobs"}:
        return bool(diag.get("coverage_complete", False)) and int(diag.get("truncated", 0) or 0) == 0
    if key == "academicpositions":
        return bool(diag.get("coverage_complete", False)) and int(diag.get("truncated", 0) or 0) == 0
    if key == "ikerbasque":
        return bool(diag.get("coverage_complete", False)) and bool(diag.get("board_fetched")) and int(diag.get("truncated", 0) or 0) == 0
    if key == "atswatch":
        return bool(diag.get("coverage_complete", False)) and not diag.get("employer_errors") and int(diag.get("truncated", 0) or 0) == 0
    if key == "santpau":
        return bool(diag.get("coverage_complete", False)) and not diag.get("page_errors") and int(diag.get("truncated", 0) or 0) == 0
    if key == "biocat":
        return diag.get("board_fetch") == "OK"
    if key == "gencat":
        return diag.get("board_fetch") == "OK" and int(diag.get("truncated", 0) or 0) == 0
    if key == "csic":
        return bool(diag.get("coverage_complete", False)) and not diag.get("board_errors") and int(diag.get("truncated", 0) or 0) == 0
    if key == "isciii":
        return bool(diag.get("coverage_complete", False)) and not diag.get("page_errors") and int(diag.get("truncated", 0) or 0) == 0
    if key == "idibaps":
        return bool(diag.get("coverage_complete", False)) and diag.get("board_fetch") == "OK" and int(diag.get("truncated", 0) or 0) == 0
    if key == "upc":
        return bool(diag.get("coverage_complete", False)) and not diag.get("board_errors") and int(diag.get("truncated", 0) or 0) == 0
    if key == "idibell":
        return bool(diag.get("coverage_complete", False)) and bool(diag.get("board_fetched")) and int(diag.get("truncated", 0) or 0) == 0
    if key == "hospitaldelmar":
        return bool(diag.get("coverage_complete", False)) and diag.get("board_fetch") == "OK" and int(diag.get("truncated", 0) or 0) == 0
    if key == "euraxess":
        feed = diag.get("feed") or {}
        if str(feed.get("mode") or "").lower() == "failed":
            return False
        if feed.get("page_errors"):
            return False
        if int(diag.get("candidate_truncated", 0) or 0) > 0:
            return False
        return feed.get("coverage_complete") is True
    if key == "bist":
        return diag.get("feed_fetch") == "OK" and int(diag.get("truncated", 0) or 0) == 0
    if key == "institutions":
        return not diag.get("board_errors") and int(diag.get("truncated", 0) or 0) == 0
    if key == "madrid":
        return bool(diag.get("coverage_complete", True)) and not diag.get("page_errors") and int(diag.get("truncated", 0) or 0) == 0
    if key in {"fbg", "fisabio", "fps", "iislafe"}:
        return bool(diag.get("coverage_complete", False)) and int(diag.get("truncated", 0) or 0) == 0
    return False


def _detail_complete(diag: dict) -> bool:
    return int(diag.get("detail_failed", 0) or 0) == 0


def _warnings_for_source(key: str, diag: dict, args) -> list[str]:
    warnings: list[str] = []
    failed = int(diag.get("detail_failed", 0) or 0)
    truncated = int(diag.get("truncated", 0) or 0)
    if failed:
        warnings.append(f"{SOURCE_LABELS[key]} detail resolution incomplete: {failed} unresolved job details")
    if key in {"linkedin", "infojobs"}:
        if diag.get("coverage_warning"):
            warnings.append(str(diag["coverage_warning"]))
        elif truncated:
            warnings.append(f"{SOURCE_LABELS[key]} candidate set truncated: {truncated} job(s) not processed")
    elif key == "academicpositions":
        if diag.get("coverage_warning"):
            warnings.append(str(diag["coverage_warning"]))
        elif truncated:
            warnings.append(f"AcademicPositions candidate set truncated: {truncated} job(s) not processed")
    elif key == "ikerbasque":
        if diag.get("coverage_warning"):
            warnings.append(str(diag["coverage_warning"]))
        elif truncated:
            warnings.append(f"Ikerbasque call set truncated: {truncated} call(s) not processed")
    elif key == "atswatch":
        if diag.get("coverage_warning"):
            warnings.append(str(diag["coverage_warning"]))
        elif truncated:
            warnings.append(f"Research Employer ATS Watchlist truncated: {truncated} job(s) not processed")
    elif key == "euraxess":
        feed = diag.get("feed") or {}
        if feed.get("page_errors"):
            warnings.append(f"EURAXESS feed page errors: {len(feed.get('page_errors') or [])}")
        if int(diag.get("candidate_truncated", 0) or 0) > 0:
            warnings.append(f"EURAXESS candidate set truncated: {int(diag.get('candidate_truncated', 0) or 0)} candidate(s) omitted")
        if args.history_days and not feed.get("coverage_complete", False):
            warnings.append(str(feed.get("coverage_warning") or "EURAXESS historical feed coverage incomplete"))
        if diag.get("detail_rate_limited"):
            warnings.append("EURAXESS detail resolution was rate limited; persistent cache permits a resumable rerun")
    elif key == "gencat" and truncated:
        warnings.append(f"Gencat Research Staff listing set truncated: {truncated} listing(s) not processed")
    elif key == "csic":
        if diag.get("coverage_warning"):
            warnings.append(str(diag["coverage_warning"]))
        elif truncated:
            warnings.append(f"CSIC institute listing set truncated: {truncated} listing(s) not processed")
    elif key == "isciii":
        if diag.get("coverage_warning"):
            warnings.append(str(diag["coverage_warning"]))
        elif truncated:
            warnings.append(f"ISCIII employment listing set truncated: {truncated} listing(s) not processed")
    elif key == "idibaps":
        if diag.get("coverage_warning"):
            warnings.append(str(diag["coverage_warning"]))
        elif truncated:
            warnings.append(f"IDIBAPS listing set truncated: {truncated} listing(s) not processed")
    elif key == "upc":
        if diag.get("coverage_warning"):
            warnings.append(str(diag["coverage_warning"]))
        elif truncated:
            warnings.append(f"UPC Talent Hub listing set truncated: {truncated} listing(s) not processed")
    elif key == "idibell":
        if diag.get("coverage_warning"):
            warnings.append(str(diag["coverage_warning"]))
        elif truncated:
            warnings.append(f"IDIBELL listing set truncated: {truncated} listing(s) not processed")
    elif key == "santpau":
        if diag.get("coverage_warning"):
            warnings.append(str(diag["coverage_warning"]))
        elif truncated:
            warnings.append(f"IR Sant Pau listing set truncated: {truncated} listing(s) not processed")
    elif key == "fbg":
        if diag.get("coverage_warning"):
            warnings.append(str(diag["coverage_warning"]))
        elif truncated:
            warnings.append(f"FBG/UB listing set truncated: {truncated} listing(s) not processed")
    elif key == "hospitaldelmar":
        if diag.get("coverage_warning"):
            warnings.append(str(diag["coverage_warning"]))
        elif truncated:
            warnings.append(f"Hospital del Mar listing set truncated: {truncated} listing(s) not processed")
    elif key == "bist" and truncated:
        warnings.append(f"BIST listing set truncated: {truncated} listing(s) not processed")
    elif key == "institutions":
        if diag.get("board_errors"):
            warnings.append(f"Institutional direct board coverage incomplete: {len(diag.get('board_errors') or [])} board(s) failed")
        if truncated:
            warnings.append(f"Institutional direct listing set truncated: {truncated} listing(s) not processed")
    elif key in {"madrid", "fisabio", "fps", "iislafe"}:
        if diag.get("coverage_warning"):
            warnings.append(str(diag["coverage_warning"]))
        elif truncated:
            warnings.append(f"{SOURCE_LABELS[key]} listing set truncated: {truncated} listing(s) not processed")
    return list(dict.fromkeys(warnings))




def _diagnostic_hard_error(key: str, diag: dict) -> str:
    """Promote collector-internal total failures to source errors.

    Some collectors intentionally return [] plus diagnostics instead of raising.
    Production orchestration must not mislabel those runs as merely incomplete.
    """
    if key in {"linkedin", "infojobs"}:
        if not diag.get("repo_path"):
            return str(diag.get("coverage_warning") or f"{SOURCE_LABELS[key]} external repo/CLI unavailable")
        if int(diag.get("search_attempts", 0) or 0) > 0 and int(diag.get("search_success", 0) or 0) == 0:
            return str(diag.get("coverage_warning") or f"All {SOURCE_LABELS[key]} searches failed")
    if key == "academicpositions" and int(diag.get("boards_fetched", 0) or 0) == 0 and diag.get("board_errors"):
        return str(diag.get("coverage_warning") or "All AcademicPositions Spain public boards failed")
    if key == "ikerbasque" and diag.get("board_fetched") is False:
        return str(diag.get("coverage_warning") or "Ikerbasque calls board collection failed")
    if key == "atswatch" and int(diag.get("employers_fetched", 0) or 0) == 0 and diag.get("employer_errors"):
        return str(diag.get("coverage_warning") or "All ATS watchlist employers failed")
    if key == "santpau" and int(diag.get("pages_fetched", 0) or 0) == 0 and diag.get("page_errors"):
        return str(diag.get("coverage_warning") or "IR Sant Pau board collection failed")
    if key == "fbg" and diag.get("board_fetched") is False:
        return str(diag.get("coverage_warning") or "FBG/UB current-offers board collection failed")
    if key == "gencat" and diag.get("board_fetch") == "FAILED":
        return str(diag.get("board_error") or "Gencat Research Staff board fetch failed")
    if key == "csic" and int(diag.get("boards_fetched", 0) or 0) == 0 and diag.get("board_errors"):
        return str(diag.get("coverage_warning") or "All configured CSIC institute boards failed")
    if key == "isciii" and int(diag.get("pages_fetched", 0) or 0) == 0 and diag.get("page_errors"):
        return str(diag.get("coverage_warning") or "ISCIII employment first-page collection failed")
    if key == "idibaps" and diag.get("board_fetch") == "FAILED":
        return str(diag.get("coverage_warning") or "IDIBAPS job board fetch failed")
    if key == "upc" and int(diag.get("boards_fetched", 0) or 0) == 0 and diag.get("board_errors"):
        return str(diag.get("coverage_warning") or "UPC Talent Hub board collection failed")
    if key == "idibell" and diag.get("board_fetched") is False:
        return str(diag.get("coverage_warning") or "IDIBELL active board fetch failed")
    if key == "hospitaldelmar" and diag.get("board_fetch") == "FAILED":
        return str(diag.get("coverage_warning") or "Hospital del Mar temporary-calls board fetch failed")
    if key == "euraxess":
        feed = diag.get("feed") or {}
        if str(feed.get("mode") or "").lower() == "failed":
            return str(feed.get("coverage_warning") or "EURAXESS feed collection failed")
    if key in {"fisabio", "fps"} and diag.get("board_fetched") is False:
        return str(diag.get("coverage_warning") or f"{SOURCE_LABELS[key]} board fetch failed")
    if key == "institutions" and int(diag.get("boards_fetched", 0) or 0) == 0 and diag.get("board_errors"):
        return f"All institutional boards failed ({len(diag.get('board_errors') or [])} error(s))"
    if key in {"madrid", "iislafe"} and int(diag.get("pages_fetched", 0) or 0) == 0 and diag.get("page_errors"):
        return str(diag.get("coverage_warning") or f"{SOURCE_LABELS[key]} first-page collection failed")
    return ""

def _annotate_provenance(row: dict, source_key: str) -> dict:
    out = dict(row)
    src = str(out.get("source") or SOURCE_LABELS[source_key]).strip()
    out["source"] = src
    out.setdefault("source_provenance", [{
        "source": src,
        "id": str(out.get("id") or ""),
        "url": str(out.get("url") or ""),
        "detail_status": str(out.get("detail_status") or ""),
    }])
    return out


def collect_sources(args, out_dir: Path, collector_overrides: dict[str, Callable] | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    collectors = _collector_map(collector_overrides)
    selected = selected_sources(args.source)
    diagnostics = {key: None for key in SOURCE_ORDER}
    source_runs: dict[str, dict] = {}
    jobs: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []
    euraxess_audit: list[dict] = []

    for key in selected:
        diag: dict = {}
        error = ""
        rows: list[dict] = []
        started = time.monotonic()
        print(f"[collector:start] {key} ({SOURCE_LABELS[key]})", flush=True)
        try:
            rows = collectors[key](diagnostics=diag, **_kwargs_for_source(key, args, out_dir, euraxess_audit)) or []
            rows = [_annotate_provenance(r, key) for r in rows]
            jobs.extend(rows)
            diagnostic_error = _diagnostic_hard_error(key, diag)
            if diagnostic_error:
                error = diagnostic_error
                errors.append(f"{SOURCE_LABELS[key]}: {diagnostic_error}")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            errors.append(f"{SOURCE_LABELS[key]}: {exc}")
        diagnostics[key] = diag
        local_warnings = _warnings_for_source(key, diag, args)
        warnings.extend(local_warnings)
        coverage_ok = (not error) and _coverage_complete(key, diag, args)
        detail_ok = (not error) and _detail_complete(diag)
        status = "ERROR" if error else "OK" if coverage_ok and detail_ok else "PARTIAL"
        elapsed_seconds = round(time.monotonic() - started, 1)
        print(
            f"[collector:done] {key} status={status} jobs={len(rows)} elapsed={elapsed_seconds}s",
            flush=True,
        )
        source_runs[key] = {
            "source": SOURCE_LABELS[key],
            "status": status,
            "jobs_collected": len(rows),
            "elapsed_seconds": elapsed_seconds,
            "coverage_complete": coverage_ok,
            "detail_resolution_complete": detail_ok,
            "detail_success": int(diag.get("detail_success", 0) or 0),
            "detail_failed": int(diag.get("detail_failed", 0) or 0),
            "truncated": int(diag.get("truncated", diag.get("candidate_truncated", 0)) or 0),
            "error": error,
            "warnings": local_warnings,
        }

    return {
        "jobs": jobs,
        "errors": errors,
        "warnings": list(dict.fromkeys(warnings)),
        "diagnostics": diagnostics,
        "source_runs": source_runs,
        "selected_sources": selected,
        "euraxess_audit": euraxess_audit,
    }
