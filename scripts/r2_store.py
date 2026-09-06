from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

STATE_KEY = "state/current/seen_jobs.json"


def _required(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _client():
    account_id = _required("R2_ACCOUNT_ID")
    endpoint = str(os.environ.get("R2_ENDPOINT") or f"https://{account_id}.r2.cloudflarestorage.com").strip()
    return boto3.client(
        service_name="s3",
        endpoint_url=endpoint,
        aws_access_key_id=_required("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_required("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )


def _bucket() -> str:
    return _required("R2_BUCKET")


def validate_state(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), dict):
        raise RuntimeError(f"Invalid seen-state schema: {path}")
    if not str(data.get("state_version") or "").strip():
        raise RuntimeError(f"Missing state_version: {path}")
    return data


def download_state(dest: Path, require: bool = True) -> bool:
    s3 = _client()
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        s3.download_file(_bucket(), STATE_KEY, str(dest))
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            if require:
                raise RuntimeError(
                    "Cloud production state is missing in R2. Bootstrap the validated local state before the first cloud run."
                ) from exc
            return False
        raise
    validate_state(dest)
    return True


def _put_file(s3, local: Path, key: str, content_type: str | None = None) -> None:
    extra = {"ContentType": content_type} if content_type else None
    if extra:
        s3.upload_file(str(local), _bucket(), key, ExtraArgs=extra)
    else:
        s3.upload_file(str(local), _bucket(), key)


def bootstrap_state(path: Path) -> dict:
    data = validate_state(path)
    s3 = _client()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_key = f"state/bootstrap/{stamp}.json"
    _put_file(s3, path, backup_key, "application/json")
    _put_file(s3, path, STATE_KEY, "application/json")
    return {"state_key": STATE_KEY, "backup_key": backup_key, "jobs": len(data["jobs"])}


def publish_run(state_file: Path, out_dir: Path, report: Path, run_id: str) -> dict:
    state = validate_state(state_file)
    summary_path = out_dir / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not bool(summary.get("seen_state_enabled")):
        raise RuntimeError("Refusing to publish a production run whose seen/history state was disabled")
    expected_jobs = int(summary.get("seen_state_jobs", -1) or -1)
    if expected_jobs != len(state["jobs"]):
        raise RuntimeError(
            f"State/report mismatch: summary has {expected_jobs} jobs but persisted state has {len(state['jobs'])}"
        )
    day = str(summary.get("availability_as_of") or datetime.now(timezone.utc).date().isoformat())
    safe_run = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_") or datetime.now(timezone.utc).strftime("%H%M%S")
    prefix = f"runs/{day}/{safe_run}"
    s3 = _client()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    state_backup = f"state/backups/{stamp}-{safe_run}.json"
    _put_file(s3, state_file, state_backup, "application/json")
    _put_file(s3, state_file, STATE_KEY, "application/json")

    # Persist the complete canonical snapshot for historical analysis without bloating
    # Telegram delivery. The source CSV already exists for every production run; R2
    # stores a gzip-compressed copy under the immutable run prefix.
    canonical_csv = out_dir / "all_canonical.csv"
    if not canonical_csv.exists():
        raise RuntimeError(f"Missing complete canonical archive source: {canonical_csv}")
    canonical_gzip = out_dir / "all_canonical.csv.gz"
    with canonical_csv.open("rb") as src, gzip.open(canonical_gzip, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)

    publish = [
        (summary_path, f"{prefix}/run_summary.json", "application/json"),
        (report, f"{prefix}/job_search_report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        (canonical_gzip, f"{prefix}/all_canonical.csv.gz", "application/gzip"),
    ]
    selected = ["daily_actionable.csv", "new_actionable.csv", "changed_or_reopened.csv", "actionable.csv", "needs_detail_review.csv", "source_summary.csv"]
    for name in selected:
        path = out_dir / name
        if path.exists():
            publish.append((path, f"{prefix}/{name}", "text/csv"))

    for local, key, ctype in publish:
        _put_file(s3, local, key, ctype)

    latest_map = {
        summary_path: ("latest/run_summary.json", "application/json"),
        report: ("latest/job_search_report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        canonical_gzip: ("latest/all_canonical.csv.gz", "application/gzip"),
    }
    for name in selected:
        path = out_dir / name
        if path.exists():
            latest_map[path] = (f"latest/{name}", "text/csv")
    for local, (key, ctype) in latest_map.items():
        _put_file(s3, local, key, ctype)

    manifest = {
        "published_at": datetime.now(timezone.utc).isoformat(),
        "run_id": safe_run,
        "run_prefix": prefix,
        "state_key": STATE_KEY,
        "state_backup": state_backup,
        "state_jobs": len(state["jobs"]),
        "report_key": "latest/job_search_report.xlsx",
        "summary_key": "latest/run_summary.json",
        "canonical_archive_key": f"{prefix}/all_canonical.csv.gz",
        "latest_canonical_archive_key": "latest/all_canonical.csv.gz",
        "canonical_archive_raw_bytes": canonical_csv.stat().st_size,
        "canonical_archive_gzip_bytes": canonical_gzip.stat().st_size,
    }
    manifest_path = out_dir / "cloud_publish_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _put_file(s3, manifest_path, f"{prefix}/cloud_publish_manifest.json", "application/json")
    _put_file(s3, manifest_path, "latest/cloud_publish_manifest.json", "application/json")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Cloudflare R2 transport for production state and run outputs")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("download-state")
    d.add_argument("--dest", required=True)
    d.add_argument("--allow-missing", action="store_true")
    b = sub.add_parser("bootstrap-state")
    b.add_argument("--file", required=True)
    p = sub.add_parser("publish-run")
    p.add_argument("--state-file", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--run-id", required=True)
    args = parser.parse_args()

    if args.command == "download-state":
        ok = download_state(Path(args.dest), require=not args.allow_missing)
        print(json.dumps({"downloaded": ok, "state_key": STATE_KEY}, indent=2))
    elif args.command == "bootstrap-state":
        print(json.dumps(bootstrap_state(Path(args.file)), indent=2))
    else:
        print(json.dumps(publish_run(Path(args.state_file), Path(args.out_dir), Path(args.report), args.run_id), indent=2))


if __name__ == "__main__":
    main()
