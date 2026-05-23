"""arcpy.da cursor classes."""

from __future__ import annotations

from typing import Any

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


def test_search_cursor_inherits_alias_where_from_make_feature_layer() -> None:
    """A SearchCursor over a MakeFeatureLayer-defined layer must apply alias.where."""

    captured: dict[str, Any] = {}

    class _RecordingSource:
        def iter_features(self, where: str | None = None, **_: Any) -> Any:
            captured["where"] = where
            return iter(())

    class _RecordingClient:
        def source(self, descriptor: Any) -> Any:
            return _RecordingSource()

    honua_arcpy.configure(client=_RecordingClient())
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr", where_clause="STATUS = 'OPEN'")

    with honua_arcpy.da.SearchCursor("roads_lyr", ["OID@", "STATUS"]) as cursor:
        list(cursor)

    assert captured["where"] == "STATUS = 'OPEN'"


def test_search_cursor_uses_alias_workspace_after_env_workspace_changes() -> None:
    """An alias must keep the workspace captured when it was created.

    ``SearchCursor`` used to resolve ``alias.source`` instead of the alias
    name, so descriptor projection fell back to the *current* session
    workspace. A later ``arcpy.env.workspace`` change could therefore retarget
    an existing layer alias at a different service.
    """

    captured: dict[str, Any] = {}

    class _RecordingSource:
        def iter_features(self, **_: Any) -> Any:
            return iter(())

    class _RecordingClient:
        def source(self, descriptor: Any) -> Any:
            captured["descriptor"] = descriptor
            return _RecordingSource()

    honua_arcpy.configure(client=_RecordingClient())
    honua_arcpy.env.workspace = "honua://services/original"
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr")
    honua_arcpy.env.workspace = "honua://services/changed"

    with honua_arcpy.da.SearchCursor("roads_lyr", ["OID@"]) as cursor:
        list(cursor)

    assert captured["descriptor"]["locator"] == {"serviceId": "original", "layerId": 0}


def test_search_cursor_combines_alias_where_with_cursor_where() -> None:
    """A cursor-supplied where_clause must AND with the alias-resident filter."""

    captured: dict[str, Any] = {}

    class _RecordingSource:
        def iter_features(self, where: str | None = None, **_: Any) -> Any:
            captured["where"] = where
            return iter(())

        def query(self, **_: Any) -> Any:
            class _R:
                features: list[Any] = []
                total_count = 0
            return _R()

    class _RecordingClient:
        def source(self, descriptor: Any) -> Any:
            return _RecordingSource()

    honua_arcpy.configure(client=_RecordingClient())
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr", where_clause="STATUS = 'OPEN'")
    honua_arcpy.management.SelectLayerByAttribute(
        "roads_lyr", "SUBSET_SELECTION", "name LIKE 'A%'"
    )

    with honua_arcpy.da.SearchCursor("roads_lyr", ["OID@"], where_clause="OBJECTID > 0") as cursor:
        list(cursor)

    where = captured["where"]
    assert where is not None
    assert "STATUS = 'OPEN'" in where
    assert "name LIKE 'A%'" in where
    assert "OBJECTID > 0" in where


def test_search_cursor_forwards_supported_query_options() -> None:
    captured: dict[str, Any] = {}

    class _RecordingSource:
        def iter_features(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return iter(())

    class _RecordingClient:
        def source(self, descriptor: Any) -> Any:
            return _RecordingSource()

    honua_arcpy.configure(client=_RecordingClient())

    with honua_arcpy.da.SearchCursor(
        "roads",
        ["OID@", "STATUS"],
        where_clause="STATUS = 'OPEN'",
        spatial_reference=4326,
        sql_clause=(None, "ORDER BY STATUS DESC"),
    ) as cursor:
        list(cursor)

    assert captured == {
        "where": "STATUS = 'OPEN'",
        "out_fields": ("OBJECTID", "STATUS"),
        "return_geometry": False,
        "out_sr": 4326,
        "order_by": "STATUS DESC",
    }


def test_search_cursor_rejects_unsupported_options() -> None:
    class _RecordingSource:
        def iter_features(self, **kwargs: Any) -> Any:
            return iter(())

    class _RecordingClient:
        def source(self, descriptor: Any) -> Any:
            return _RecordingSource()

    honua_arcpy.configure(client=_RecordingClient())

    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError):
        with honua_arcpy.da.SearchCursor("roads", ["OID@"], explode_to_points=True) as cursor:
            list(cursor)

    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError):
        with honua_arcpy.da.SearchCursor("roads", ["OID@"], sql_clause=("DISTINCT", None)) as cursor:
            list(cursor)


def test_update_cursor_inherits_alias_where() -> None:
    captured: dict[str, Any] = {}

    class _RecordingSource:
        def iter_features(self, where: str | None = None, **_: Any) -> Any:
            captured["where"] = where
            return iter(())

        def apply_edits(self, **_: Any) -> Any:
            return None

    class _RecordingClient:
        def source(self, descriptor: Any) -> Any:
            return _RecordingSource()

    honua_arcpy.configure(client=_RecordingClient())
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr", where_clause="STATUS = 'OPEN'")

    with honua_arcpy.da.UpdateCursor("roads_lyr", ["OID@", "STATUS"]) as cursor:
        list(cursor)

    assert captured["where"] == "STATUS = 'OPEN'"


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


def test_search_cursor_wraps_iter_features_failures_in_execute_error() -> None:
    """Backend failures from Source.iter_features must surface as ExecuteError."""

    class _ExplodingSource:
        def iter_features(self, **_: Any) -> Any:
            raise RuntimeError("backend exploded")

    class _ExplodingClient:
        def source(self, descriptor: Any) -> Any:
            return _ExplodingSource()

    honua_arcpy.configure(client=_ExplodingClient())

    with pytest.raises(honua_arcpy.ExecuteError) as info:
        with honua_arcpy.da.SearchCursor("roads", ["OID@"]) as cursor:
            next(iter(cursor))
    assert info.value.function == "da.SearchCursor"
    assert info.value.error_kind == "RuntimeError"
    assert "compatibility-matrix" in (info.value.compat_anchor or "")


def test_update_cursor_flush_failure_wraps_in_execute_error_and_audits_error() -> None:
    """apply_edits failures during flush surface as ExecuteError and audit as error."""

    import json
    import os
    from pathlib import Path

    class _ExplodingSource:
        def iter_features(self, **_: Any) -> Any:
            return iter([
                {"attributes": {"OBJECTID": 1, "STATUS": "OPEN"}},
            ])

        def apply_edits(self, **_: Any) -> Any:
            raise RuntimeError("apply_edits exploded")

    class _ExplodingClient:
        def source(self, descriptor: Any) -> Any:
            return _ExplodingSource()

    honua_arcpy.configure(client=_ExplodingClient())

    with pytest.raises(honua_arcpy.ExecuteError) as info:
        with honua_arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"]) as cursor:
            row = next(cursor)
            row[1] = "ARCHIVED"
            cursor.updateRow(row)
    assert info.value.function == "da.UpdateCursor"
    assert info.value.error_kind == "RuntimeError"

    audit_dir = Path(os.environ["HONUA_ARCPY_AUDIT_DIR"])
    files = list(audit_dir.glob("audit-*.jsonl"))
    assert files
    records = [
        json.loads(line)
        for line in files[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cursor_records = [r for r in records if r["function"] == "da.UpdateCursor"]
    assert cursor_records, "UpdateCursor audit record missing"
    # Before the fix, the audit recorded status="ok" because __exit__ passed
    # exc_type=None into record_call even though _close raised.
    assert cursor_records[-1]["status"] == "error"
    assert cursor_records[-1]["error_kind"] == "RuntimeError"


def test_insert_cursor_flush_failure_wraps_in_execute_error_and_audits_error() -> None:
    import json
    import os
    from pathlib import Path

    class _ExplodingSource:
        def apply_edits(self, **_: Any) -> Any:
            raise RuntimeError("insert exploded")

    class _ExplodingClient:
        def source(self, descriptor: Any) -> Any:
            return _ExplodingSource()

    honua_arcpy.configure(client=_ExplodingClient())

    with pytest.raises(honua_arcpy.ExecuteError) as info:
        with honua_arcpy.da.InsertCursor("roads", ["STATUS"]) as cursor:
            cursor.insertRow(["OPEN"])
    assert info.value.function == "da.InsertCursor"
    assert info.value.error_kind == "RuntimeError"

    audit_dir = Path(os.environ["HONUA_ARCPY_AUDIT_DIR"])
    records = [
        json.loads(line)
        for path in sorted(audit_dir.glob("audit-*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    insert_records = [r for r in records if r["function"] == "da.InsertCursor"]
    assert insert_records and insert_records[-1]["status"] == "error"
    assert insert_records[-1]["error_kind"] == "RuntimeError"


def test_search_cursor_preserves_zero_valued_objectid() -> None:
    """A valid OBJECTID of 0 must surface as 0, not None.

    Before the fix, ``attrs.get('OBJECTID') or attrs.get('oid') or attrs.get('FID')``
    collapsed ``0`` into the fallback chain and returned ``None``.
    """

    class _ZeroOidSource:
        def iter_features(self, **_: Any) -> Any:
            return iter([
                {"attributes": {"OBJECTID": 0, "STATUS": "OPEN"}},
                {"attributes": {"OBJECTID": 1, "STATUS": "CLOSED"}},
            ])

    class _ZeroOidClient:
        def source(self, descriptor: Any) -> Any:
            return _ZeroOidSource()

    honua_arcpy.configure(client=_ZeroOidClient())

    with honua_arcpy.da.SearchCursor("roads", ["OID@", "STATUS"]) as cursor:
        rows = list(cursor)

    assert rows[0] == (0, "OPEN")
    assert rows[1] == (1, "CLOSED")


def test_search_cursor_preserves_zero_valued_fid_fallback() -> None:
    """Layers that expose ``FID`` (not ``OBJECTID``) must also preserve a zero
    value when ``OID@`` is requested."""

    class _FidSource:
        def iter_features(self, **_: Any) -> Any:
            return iter([
                {"attributes": {"FID": 0, "NAME": "first"}},
            ])

    class _FidClient:
        def source(self, descriptor: Any) -> Any:
            return _FidSource()

    honua_arcpy.configure(client=_FidClient())

    with honua_arcpy.da.SearchCursor("parcels", ["OID@", "NAME"]) as cursor:
        rows = list(cursor)

    assert rows == [(0, "first")]


def test_update_cursor_preserves_zero_valued_oid_for_updates_and_deletes() -> None:
    """UpdateCursor.updateRow / deleteRow must accept a feature with OBJECTID=0.

    Before the fix, _extract_oid returned None for OBJECTID=0 and both
    methods raised HonuaArcpyConfigurationError, masking a valid edit.
    """

    edits: dict[str, Any] = {}

    class _ZeroOidSource:
        def iter_features(self, **_: Any) -> Any:
            return iter([
                {"attributes": {"OBJECTID": 0, "STATUS": "OPEN"}},
                {"attributes": {"OBJECTID": 1, "STATUS": "OPEN"}},
            ])

        def apply_edits(self, **kwargs: Any) -> Any:
            edits.update(kwargs)
            return {"ok": True}

    class _ZeroOidClient:
        def source(self, descriptor: Any) -> Any:
            return _ZeroOidSource()

    honua_arcpy.configure(client=_ZeroOidClient())

    with honua_arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"]) as cursor:
        first = next(cursor)
        assert first[0] == 0  # The zero OID must reach the caller.
        first[1] = "ARCHIVED"
        cursor.updateRow(first)

        second = next(cursor)
        cursor.deleteRow()  # OBJECTID=1

    # The buffered update must carry OBJECTID=0 verbatim, and the delete
    # must enqueue OID 1 (proving the deleteRow path also reads the OID
    # without relying on the truthy chain).
    assert edits["updates"][0]["attributes"]["OBJECTID"] == 0
    assert edits["deletes"] == [1]
    _ = second  # silence unused-var warnings


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


def test_search_cursor_next_before_enter_raises_configuration_error() -> None:
    """Direct ``next(cursor)`` on a cursor that never entered its context
    must raise the documented configuration error, not the bare
    ``AttributeError`` that ``_wrap_source_error`` previously mislabelled
    as a backend ``ExecuteError``."""

    cursor = honua_arcpy.da.SearchCursor("roads", ["OID@"])
    with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError):
        next(cursor)


def test_search_cursor_next_after_exit_raises_configuration_error(stub_clients) -> None:
    """After the context closes, a cached iterator must not keep yielding
    rows; the cursor is logically closed."""

    cursor_obj = None
    with honua_arcpy.da.SearchCursor("roads", ["OID@", "STATUS"]) as cursor:
        next(cursor)  # prime the iterator
        cursor_obj = cursor

    assert cursor_obj is not None
    with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError):
        next(cursor_obj)


def test_update_cursor_next_before_enter_raises_configuration_error() -> None:
    cursor = honua_arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"])
    with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError):
        next(cursor)


def test_update_cursor_next_after_exit_raises_configuration_error(stub_clients) -> None:
    cursor_obj = None
    with honua_arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"]) as cursor:
        next(cursor)
        cursor_obj = cursor

    assert cursor_obj is not None
    with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError):
        next(cursor_obj)


def test_insert_cursor_reset_refuses_to_drop_buffered_inserts() -> None:
    """``InsertCursor.reset`` must refuse rather than silently discard
    buffered rows. Real ``arcpy.da.InsertCursor`` has no reset method; the
    inherited ``BaseCursor.reset`` would otherwise clear ``_inserts`` /
    ``_inserted`` and the subsequent ``_close`` would skip ``flush`` because
    the buffer is empty -- a silent data loss the audit JSONL never sees.
    """

    captured: dict[str, Any] = {}

    class _RecordingSource:
        def apply_edits(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return {"ok": True}

    class _RecordingClient:
        def source(self, descriptor: Any) -> Any:
            return _RecordingSource()

    honua_arcpy.configure(client=_RecordingClient())

    with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError) as info:
        with honua_arcpy.da.InsertCursor("roads", ["STATUS"]) as cursor:
            cursor.insertRow(["OPEN"])
            cursor.reset()
    assert "InsertCursor does not support reset" in str(info.value)
    # The buffer must reach apply_edits despite the exception unwinding the
    # context manager -- the refusal happens *before* the buffer is cleared,
    # so the user can still recover by catching the error and calling flush.
    # However in this test we exit with the exception so __exit__'s _close
    # early-returns: the failure mode is "raise before silent loss", not
    # "raise *and* commit". Confirm the buffer survived the reset attempt
    # by checking that the cursor never apply_edits'd.
    assert captured == {}, "buffer must not be silently dropped or flushed by reset()"


def test_insert_cursor_reset_does_not_clear_buffer_before_raising() -> None:
    """Confirm the refusal short-circuits before the buffer would have been
    cleared. The caller can still flush manually after catching the error.
    """

    flushed: list[dict[str, Any]] = []

    class _RecordingSource:
        def apply_edits(self, **kwargs: Any) -> Any:
            flushed.append(dict(kwargs))
            return {"ok": True}

    class _RecordingClient:
        def source(self, descriptor: Any) -> Any:
            return _RecordingSource()

    honua_arcpy.configure(client=_RecordingClient())

    with honua_arcpy.da.InsertCursor("roads", ["STATUS"]) as cursor:
        cursor.insertRow(["OPEN"])
        try:
            cursor.reset()
        except honua_arcpy.HonuaArcpyConfigurationError:
            pass
        # The buffered row must still be present for an explicit flush.
        cursor.flush()

    assert flushed == [{"adds": [{"attributes": {"STATUS": "OPEN"}}]}]


def test_insert_cursor_reset_outside_context_raises_configuration_error() -> None:
    """``reset()`` must still go through ``_ensure_open()`` so a cursor that
    never entered its context fails with the same configuration error as
    ``next(cursor)``, not a misleading ``InsertCursor does not support reset``
    message that implies the cursor was actually open.
    """

    cursor = honua_arcpy.da.InsertCursor("roads", ["STATUS"])
    with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError) as info:
        cursor.reset()
    # Must be the must-be-used-as-context-manager message, not the
    # InsertCursor-specific refusal.
    assert "context manager" in str(info.value)


def test_update_cursor_update_row_length_mismatch_raises_configuration_error(
    stub_clients,
) -> None:
    """A ``updateRow`` call whose row length disagrees with ``field_names`` must
    surface as ``HonuaArcpyConfigurationError`` (an ``ExecuteError``
    subclass) so ``except arcpy.ExecuteError`` keeps catching it. Before the
    fix, ``zip(..., strict=True)`` raised a bare ``ValueError`` that escaped
    the documented shim error surface.
    """

    with honua_arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"]) as cursor:
        row = next(cursor)
        with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError) as info:
            cursor.updateRow(row + ["extra"])
        message = str(info.value)
        assert "3 value(s)" in message
        assert "field_names declares 2" in message


def test_update_cursor_update_row_short_row_raises_configuration_error(
    stub_clients,
) -> None:
    with honua_arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"]) as cursor:
        row = next(cursor)
        with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError):
            cursor.updateRow(row[:1])


def test_insert_cursor_insert_row_length_mismatch_raises_configuration_error(
    stub_clients,
) -> None:
    """``insertRow`` shares ``_payload_for_row`` with ``updateRow``; the same
    row-length contract applies.
    """

    with honua_arcpy.da.InsertCursor("roads", ["STATUS", "name"]) as cursor:
        with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError) as info:
            cursor.insertRow(["OPEN"])
        assert "1 value(s)" in str(info.value)
        assert "field_names declares 2" in str(info.value)


def test_row_length_mismatch_caught_by_execute_error(stub_clients) -> None:
    """The legacy ``except arcpy.ExecuteError:`` idiom must still catch the
    row-length error. ``HonuaArcpyConfigurationError`` subclasses
    ``ExecuteError`` (== top-level ``honua_arcpy.ExecuteError``), so this is
    the regression that ``ValueError`` would have broken.
    """

    with honua_arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"]) as cursor:
        row = next(cursor)
        try:
            cursor.updateRow(row + ["extra"])
        except honua_arcpy.ExecuteError:
            return
    raise AssertionError("expected ExecuteError to catch the row-length mismatch")
