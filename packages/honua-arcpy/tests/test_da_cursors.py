"""arcpy.da cursor classes."""

from __future__ import annotations

import pytest

import honua_arcpy


def test_search_cursor_iterates_rows(stub_clients) -> None:
    rows = []
    with honua_arcpy.da.SearchCursor("roads", ["OID@", "STATUS", "name"]) as cursor:
        for row in cursor:
            rows.append(row)
    assert len(rows) == 3
    assert rows[0][0] == 1  # OID
    assert rows[1][1] == "CLOSED"


def test_search_cursor_with_where_clause(stub_clients) -> None:
    with honua_arcpy.da.SearchCursor("roads", ["OID@", "STATUS"], where_clause="STATUS = 'OPEN'") as cursor:
        rows = list(cursor)
    assert rows


def test_update_cursor_buffers_updates_and_flushes_on_exit(stub_clients) -> None:
    client, _ = stub_clients
    with honua_arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"]) as cursor:
        for row in cursor:
            if row[1] == "CLOSED":
                row[1] = "ARCHIVED"
                cursor.updateRow(row)
    # We don't observe apply_edits on the stub, but the cursor should not raise.


def test_update_cursor_explicit_flush(stub_clients) -> None:
    with honua_arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"]) as cursor:
        row = next(cursor)
        row[1] = "FLUSHED"
        cursor.updateRow(row)
        result = cursor.flush()
        assert result is not None
        # Subsequent flush is a no-op
        assert cursor.flush() is None


def test_update_cursor_delete_row_buffers_deletes(stub_clients) -> None:
    with honua_arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"]) as cursor:
        for row in cursor:
            if row[1] == "CLOSED":
                cursor.deleteRow()


def test_insert_cursor_records_inserts(stub_clients) -> None:
    with honua_arcpy.da.InsertCursor("roads", ["STATUS", "name"]) as cursor:
        cursor.insertRow(["OPEN", "Main"])
        cursor.insertRow(["OPEN", "Elm"])
    # Cursor exits cleanly; insertion buffer flushed on __exit__.


def test_cursor_must_be_used_as_context_manager(stub_clients) -> None:
    cursor = honua_arcpy.da.SearchCursor("roads", ["OID@"])
    with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError):
        next(iter(cursor))


def test_da_stubs_raise(stub_clients) -> None:
    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError):
        honua_arcpy.da.Walk("honua://services/transport")
    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError):
        honua_arcpy.da.TableToNumPyArray("segments", ["OBJECTID"])


def test_cursor_open_failure_reports_real_error_kind(tmp_path) -> None:
    # Unconfigured session: _open() raises HonuaArcpyConfigurationError before
    # the caller's `with` block starts. The audit should record that real
    # error_kind, not GeneratorExit from the record_call generator being GC'd.
    import json

    honua_arcpy.reset()
    with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError):
        with honua_arcpy.da.SearchCursor("roads", ["OID@"]):
            pass

    import os
    from pathlib import Path

    audit_dir = Path(os.environ["HONUA_ARCPY_AUDIT_DIR"])
    files = list(audit_dir.glob("audit-*.jsonl"))
    assert files, f"audit file missing under {audit_dir}"
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert lines, "audit file should have one record"
    record = json.loads(lines[-1])
    assert record["status"] == "error"
    # The error_kind attribute on HonuaArcpyConfigurationError is "configuration".
    # Before the __enter__ fix, the audit recorded "GeneratorExit" because the
    # record_call context was GC'd instead of receiving the real exception.
    assert record["error_kind"] == "configuration"
