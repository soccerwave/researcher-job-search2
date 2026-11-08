"""Read-only weekly audit export of immutable production runs from Cloudflare R2."""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import boto3

REQUIRED = ("run_summary.json", "source_summary.csv", "all_canonical.csv.gz")
RUN_ID_RE = re.compile(r"^\d+-\d+$")


def days_ending(end: date, count: int) -> list[str]:
    if not 1 <= count <= 31:
        raise ValueError("days must be between 1 and 31")
    return [(end - timedelta(days=i)).isoformat() for i in range(count - 1, -1, -1)]


def client():
    account = os.environ["R2_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("R2_ENDPOINT") or f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def list_day_runs(s3, bucket: str, day: str) -> list[tuple[datetime, str]]:
    prefix = f"runs/{day}/"
    newest: dict[str, datetime] = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            parts = key[len(prefix):].split("/")
            if len(parts) != 2 or parts[1] != "run_summary.json":
                continue
            run_id = parts[0]
            if not RUN_ID_RE.fullmatch(run_id):
                continue
            modified = obj["LastModified"]
            if modified.tzinfo is None:
                modified = modified.replace(tzinfo=timezone.utc)
            newest[run_id] = modified
    return sorted(((when, run_id) for run_id, when in newest.items()), reverse=True)


def validate_payload(name: str, raw: bytes) -> dict:
    if name == "run_summary.json":
        payload = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("run_summary must be a JSON object")
        return {"bytes": len(raw)}
    if name == "source_summary.csv":
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        if not rows:
            raise ValueError("source_summary contains no source rows")
        return {"bytes": len(raw), "rows": len(rows)}
    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as file:
        text = io.TextIOWrapper(file, encoding="utf-8-sig")
        reader = csv.DictReader(text)
        if not reader.fieldnames:
            raise ValueError("canonical has no columns")
        n = sum(1 for _ in reader)
    if not n:
        raise ValueError("canonical has no rows")
    return {"bytes": len(raw), "rows": n}


def export(s3, bucket: str, end: date, count: int, dest: Path) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    days = days_ending(end, count)
    manifest = {"period_start": days[0], "period_end": days[-1], "days_requested": count,
                "runs": [], "errors": [], "complete": False}
    for day in days:
        matches = list_day_runs(s3, bucket, day)
        if not matches:
            manifest["errors"].append(f"{day}: no published production run found")
            continue
        # Choose newest complete run, not simply the newest partially published run.
        selected = None
        candidate_errors = []
        for _, run_id in matches:
            prefix = f"runs/{day}/{run_id}"
            downloaded = {}
            try:
                for name in REQUIRED:
                    raw = s3.get_object(Bucket=bucket, Key=f"{prefix}/{name}")["Body"].read()
                    downloaded[name] = (raw, validate_payload(name, raw))
                summary = json.loads(downloaded["run_summary.json"][0].decode("utf-8-sig"))
                if str(summary.get("availability_as_of") or "") != day:
                    raise ValueError("summary availability_as_of does not match folder date")
                selected = (run_id, prefix, downloaded)
                break
            except Exception as exc:
                candidate_errors.append(f"{run_id}: {type(exc).__name__}: {exc}")
        if selected is None:
            manifest["errors"].append(f"{day}: no complete usable run ({'; '.join(candidate_errors)})")
            continue
        run_id, prefix, downloaded = selected
        output = dest / day
        output.mkdir(exist_ok=True)
        info = {"date": day, "run_id": run_id, "r2_prefix": prefix, "files": {}}
        for name, (raw, metadata) in downloaded.items():
            (output / name).write_bytes(raw)
            info["files"][name] = metadata
        if candidate_errors:
            info["newer_incomplete_runs_ignored"] = candidate_errors
        manifest["runs"].append(info)
    manifest["complete"] = len(manifest["runs"]) == count and not manifest["errors"]
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_lines = [
        "# Weekly Collector & Evaluator Audit Export",
        f"Period: {days[0]} to {days[-1]}",
        f"Complete: {manifest['complete']}",
        f"Valid days: {len(manifest['runs'])}/{count}",
        "",
        "| Day | Selected run | Canonical rows | Sources |",
        "|---|---|---:|---:|",
    ]
    for r in manifest["runs"]:
        summary_lines.append(f"| {r['date']} | {r['run_id']} | {r['files']['all_canonical.csv.gz']['rows']} | {r['files']['source_summary.csv']['rows']} |")
    if manifest["errors"]:
        summary_lines += ["", "## Missing or corrupt days"] + [f"- {err}" for err in manifest["errors"]]
    (dest / "README.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--end-date", default="", help="YYYY-MM-DD inclusive; default current UTC date")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    end = date.fromisoformat(args.end_date) if args.end_date else datetime.now(timezone.utc).date()
    result = export(client(), os.environ["R2_BUCKET"], end, args.days, args.out)
    print(json.dumps({"complete": result["complete"], "runs": len(result["runs"]),
                      "errors": result["errors"], "period_end": result["period_end"]}, ensure_ascii=False))
    raise SystemExit(0 if result["complete"] else 2)


if __name__ == "__main__":
    main()
