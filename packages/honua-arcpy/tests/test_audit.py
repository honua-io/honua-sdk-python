"""Audit JSONL writer + redaction."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from honua_arcpy._audit import (
    AuditWriter,
    _redact_value,
    _shape_of,
    record_call,
)


def test_record_call_writes_one_line_with_required_fields(tmp_path: Path) -> None:
    writer = AuditWriter(base_dir=tmp_path)
    with record_call("analysis.Buffer", args=("roads", "out"), kwargs={"distance": 25}, writer=writer):
        pass
    files = list(tmp_path.glob("audit-*.jsonl"))
    assert len(files) == 1
    line = files[0].read_text(encoding="utf-8").splitlines()[0]
    record = json.loads(line)
    assert record["function"] == "analysis.Buffer"
    assert record["status"] == "ok"
    assert "latency_ms" in record
    assert "timestamp" in record
    assert record["args"] == ["roads", "out"]
    assert record["kwargs"] == {"distance": 25}


def test_record_call_captures_error_kind_when_exception_raised(tmp_path: Path) -> None:
    writer = AuditWriter(base_dir=tmp_path)

    class Boom(Exception):
        error_kind = "custom"

    with pytest.raises(Boom):
        with record_call("analysis.Boom", writer=writer):
            raise Boom("nope")

    record = json.loads(next(tmp_path.glob("audit-*.jsonl")).read_text(encoding="utf-8").splitlines()[0])
    assert record["status"] == "error"
    assert record["error_kind"] == "custom"


def test_redact_value_redacts_paths_and_urls() -> None:
    assert _redact_value("/srv/data/parcels.gdb/Parcels").startswith("<local-path>")
    assert _redact_value("C:\\GIS\\parcels.gdb\\Parcels").startswith("<local-path>")
    assert _redact_value("https://user:pass@db.example.com/?token=abcd").startswith("https://")
    assert _redact_value("super-secret-token", context="api_key") == "<redacted>"


def test_shape_of_summarizes_without_leaking_values() -> None:
    shape = _shape_of({"a": 1, "b": 2})
    assert shape == {"type": "object", "keys": ["a", "b"]}

    array_shape = _shape_of([1, 2, 3])
    assert array_shape == {"type": "array", "length": 3}

    string_shape = _shape_of("abc")
    assert string_shape == {"type": "string", "length": 3}


def test_writer_rotates_on_new_utc_day(tmp_path: Path) -> None:
    writer = AuditWriter(base_dir=tmp_path)
    day_one = datetime(2026, 5, 21, tzinfo=timezone.utc)
    day_two = datetime(2026, 5, 22, tzinfo=timezone.utc)
    writer.write({"function": "x"}, now=day_one)
    writer.write({"function": "y"}, now=day_two)
    files = sorted(p.name for p in tmp_path.glob("audit-*.jsonl"))
    assert files == ["audit-20260521.jsonl", "audit-20260522.jsonl"]
