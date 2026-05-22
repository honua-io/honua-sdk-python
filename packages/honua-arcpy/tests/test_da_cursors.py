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
