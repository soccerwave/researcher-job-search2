from datetime import date, datetime, timezone
import csv
import gzip
import io
import json

from scripts.weekly_r2_audit_export import days_ending, export, list_day_runs


class FakePaginator:
    def __init__(self, store):
        self.store = store

    def paginate(self, Bucket, Prefix):
        objects = [
            {"Key": key, "LastModified": datetime(2026, 11, 8, tzinfo=timezone.utc)}
            for key in self.store if key.startswith(Prefix)
        ]
        yield {"Contents": objects}


class FakeS3:
    def __init__(self, store):
        self.store = store

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return FakePaginator(self.store)

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.store[Key])}


def fixture_store():
    prefix = "runs/2026-11-01/123-1"
    gz = gzip.compress(b"title,recommendation\nExample,SKIP\n")
    return {
        prefix + "/run_summary.json": json.dumps({"availability_as_of": "2026-11-01"}).encode(),
        prefix + "/source_summary.csv": b"source,status\nLinkedIn,OK\n",
        prefix + "/all_canonical.csv.gz": gz,
    }


def test_date_window():
    assert days_ending(date(2026, 11, 1), 7) == [
        "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29",
        "2026-10-30", "2026-10-31", "2026-11-01",
    ]


def test_complete_export(tmp_path):
    store = fixture_store()
    result = export(FakeS3(store), "bucket", date(2026, 11, 1), 1, tmp_path)
    assert result["complete"] is True
    assert result["runs"][0]["run_id"] == "123-1"
    assert (tmp_path / "2026-11-01" / "all_canonical.csv.gz").read_bytes() == store["runs/2026-11-01/123-1/all_canonical.csv.gz"]
    assert (tmp_path / "manifest.json").exists()


def test_missing_day_is_explicit(tmp_path):
    result = export(FakeS3({}), "bucket", date(2026, 11, 1), 1, tmp_path)
    assert result["complete"] is False
    assert "no published production run" in result["errors"][0]
    assert (tmp_path / "manifest.json").exists()


def test_incomplete_latest_run_falls_back(tmp_path):
    store = fixture_store()
    store["runs/2026-11-01/124-1/run_summary.json"] = json.dumps({"availability_as_of": "2026-11-01"}).encode()
    result = export(FakeS3(store), "bucket", date(2026, 11, 1), 1, tmp_path)
    assert result["complete"]
    assert result["runs"][0]["run_id"] == "123-1"
