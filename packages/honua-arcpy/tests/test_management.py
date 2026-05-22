"""Management shim: session aliases, source-backed selection, admin routing."""

from __future__ import annotations

import pytest

import honua_arcpy


def test_make_feature_layer_registers_alias(stub_clients) -> None:
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr", where_clause="STATUS = 'OPEN'")
    alias = honua_arcpy.get_session().get_layer("roads_lyr")
    assert alias is not None
    assert alias.source == "roads"
    assert alias.where == "STATUS = 'OPEN'"


def test_make_feature_layer_overwrite_protection(stub_clients) -> None:
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr")
    with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError):
        honua_arcpy.management.MakeFeatureLayer("roads_alt", "roads_lyr")

    honua_arcpy.env.overwriteOutput = True
    honua_arcpy.management.MakeFeatureLayer("roads_alt", "roads_lyr")
    assert honua_arcpy.get_session().get_layer("roads_lyr").source == "roads_alt"


def test_select_layer_by_attribute_updates_where_and_returns_count(stub_clients) -> None:
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr")
    selection = honua_arcpy.management.SelectLayerByAttribute(
        "roads_lyr", "NEW_SELECTION", "STATUS = 'OPEN'"
    )
    assert selection.layer_name == "roads_lyr"
    assert isinstance(selection.count, int)
    assert honua_arcpy.get_session().get_layer("roads_lyr").where == "STATUS = 'OPEN'"

    further = honua_arcpy.management.SelectLayerByAttribute(
        "roads_lyr", "SUBSET_SELECTION", "name LIKE 'A%'"
    )
    assert "AND" in further.where


def test_select_layer_by_attribute_applies_invert_where_clause(stub_clients) -> None:
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr")
    selection = honua_arcpy.management.SelectLayerByAttribute(
        "roads_lyr",
        "NEW_SELECTION",
        "STATUS = 'OPEN'",
        invert_where_clause=True,
    )
    assert selection.where == "NOT (STATUS = 'OPEN')"
    assert honua_arcpy.get_session().get_layer("roads_lyr").where == "NOT (STATUS = 'OPEN')"


def test_select_layer_by_attribute_switch_is_unsupported(stub_clients) -> None:
    # arcpy SWITCH_SELECTION inverts the prior selection set (OIDs), which we
    # cannot model as a SQL where clause; the previous behaviour silently
    # cleared the selection. Surface it as unsupported instead.
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr")
    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError) as info:
        honua_arcpy.management.SelectLayerByAttribute("roads_lyr", "SWITCH_SELECTION")
    # The error must be scoped to the SWITCH_SELECTION mode, not claim the
    # whole SelectLayerByAttribute function is unimplemented (the compatibility
    # matrix lists it as Supported, just not in this mode).
    assert "SWITCH_SELECTION" in info.value.function
    assert info.value.replacement_hint and "invert_where_clause" in info.value.replacement_hint
    # The compat anchor still points at the SelectLayerByAttribute matrix row,
    # which means it must not include the SWITCH_SELECTION variant suffix.
    anchor = (info.value.compat_anchor or "").lower()
    assert "selectlayerbyattribute" in anchor
    assert "switch_selection" not in anchor


def test_select_layer_by_attribute_switch_writes_audit_record(stub_clients) -> None:
    """Even though SWITCH_SELECTION is rejected before the backend call, the
    refusal must be visible in the JSONL audit stream so operators see every
    shim call -- including the ones the shim immediately refuses."""

    import json
    import os
    from pathlib import Path

    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr")
    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError):
        honua_arcpy.management.SelectLayerByAttribute("roads_lyr", "SWITCH_SELECTION")

    audit_dir = Path(os.environ["HONUA_ARCPY_AUDIT_DIR"])
    files = list(audit_dir.glob("audit-*.jsonl"))
    assert files, "expected an audit JSONL file"
    records = [
        json.loads(line)
        for line in files[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    refusal = [r for r in records if "SWITCH_SELECTION" in r["function"]]
    assert refusal, "SWITCH_SELECTION rejection was not audited"
    assert refusal[-1]["status"] == "error"
    assert refusal[-1]["error_kind"] == "unsupported"


def test_select_layer_by_attribute_unknown_selection_type_raises(stub_clients) -> None:
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr")
    with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError):
        honua_arcpy.management.SelectLayerByAttribute("roads_lyr", "BOGUS_MODE", "STATUS = 'OPEN'")


def test_select_layer_by_attribute_propagates_backend_failures() -> None:
    # _layer_count must not swallow backend exceptions; a failure should
    # surface as ExecuteError with an audit error record.
    import json
    import os
    from pathlib import Path

    class _ExplodingSource:
        def query(self, **_: object) -> object:
            raise RuntimeError("backend exploded")

    class _ExplodingClient:
        def source(self, descriptor: object) -> object:
            return _ExplodingSource()

    honua_arcpy.configure(client=_ExplodingClient())
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr")

    with pytest.raises(honua_arcpy.ExecuteError) as info:
        honua_arcpy.management.SelectLayerByAttribute(
            "roads_lyr", "NEW_SELECTION", "STATUS = 'OPEN'"
        )
    assert info.value.error_kind == "RuntimeError"

    audit_dir = Path(os.environ["HONUA_ARCPY_AUDIT_DIR"])
    files = list(audit_dir.glob("audit-*.jsonl"))
    assert files
    records = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    select_records = [r for r in records if r["function"] == "management.SelectLayerByAttribute"]
    assert select_records and select_records[-1]["status"] == "error"
    assert select_records[-1]["error_kind"] == "RuntimeError"


def test_select_layer_by_attribute_rolls_back_alias_on_backend_failure() -> None:
    """A failed selection must not leave the candidate where on the alias.

    Subsequent cursors over the layer would otherwise apply a selection that
    never successfully reached the backend, silently filtering rows the user
    never asked to filter.
    """

    class _ExplodingSource:
        def query(self, **_: object) -> object:
            raise RuntimeError("backend exploded")

    class _ExplodingClient:
        def source(self, descriptor: object) -> object:
            return _ExplodingSource()

    honua_arcpy.configure(client=_ExplodingClient())
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr", where_clause="STATUS = 'OPEN'")

    alias = honua_arcpy.get_session().get_layer("roads_lyr")
    assert alias is not None
    assert alias.where == "STATUS = 'OPEN'"
    original_selection = dict(alias.selection)

    with pytest.raises(honua_arcpy.ExecuteError):
        honua_arcpy.management.SelectLayerByAttribute(
            "roads_lyr", "SUBSET_SELECTION", "name LIKE 'A%'"
        )

    # The alias.where / alias.selection must still reflect the prior state,
    # not the candidate where that the backend rejected.
    assert alias.where == "STATUS = 'OPEN'"
    assert alias.selection == original_selection


def test_get_count_with_and_without_selection(stub_clients) -> None:
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr")
    full = honua_arcpy.management.GetCount("roads_lyr")
    honua_arcpy.management.SelectLayerByAttribute("roads_lyr", "NEW_SELECTION", "STATUS = 'OPEN'")
    filtered = honua_arcpy.management.GetCount("roads_lyr")
    assert isinstance(full, int)
    assert isinstance(filtered, int)


def test_describe_is_stub_until_admin_contract_lands(stub_clients) -> None:
    # HonuaAdminClient does not expose a per-layer schema reader today.
    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError):
        honua_arcpy.Describe("segments")


def test_list_fields_is_stub_until_admin_contract_lands(stub_clients) -> None:
    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError):
        honua_arcpy.management.ListFields("segments")


def test_add_field_is_stub_until_admin_contract_lands(stub_clients) -> None:
    # apply_manifest exists but has no add-field translation; surface the gap
    # explicitly so customer scripts do not silently no-op.
    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError):
        honua_arcpy.management.AddField("segments", "route_id", field_type="LONG")


def test_field_describe_dataclass_is_importable(stub_clients) -> None:
    # FieldDescribe and DescribeResult are kept so eventual non-stub
    # implementations have a stable return shape; they remain importable.
    assert honua_arcpy.FieldDescribe(name="OBJECTID", type="OID").name == "OBJECTID"
    assert honua_arcpy.DescribeResult(name="segments").name == "segments"


def test_calculate_field_dispatches_process(stub_clients) -> None:
    client, _ = stub_clients
    honua_arcpy.management.CalculateField("segments", "scaled_speed", "!speed! * 1.1", expression_type="PYTHON3")
    process_calls = client.ogc_processes().calls
    assert process_calls[-1]["process_id"] == "data-management.calculate-field"
    assert process_calls[-1]["payload"]["inputs"]["expression"] == "!speed! * 1.1"


def test_stubs_raise_with_replacement_hints(stub_clients) -> None:
    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError):
        honua_arcpy.management.Sort("roads", "out", [["name", "ASCENDING"]])
    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError):
        honua_arcpy.management.Append(["a"], "b")
    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError):
        honua_arcpy.management.CreateFeatureclass("ws", "fc", "POLYGON")


def test_stub_calls_are_audited_with_status_error(stub_clients) -> None:
    """Every shim call must write one JSONL line, including stubs that raise
    immediately. The previous behaviour skipped the audit so operators had no
    record of the rejected call."""

    import json
    import os
    from pathlib import Path

    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError):
        honua_arcpy.analysis.Near("roads", "stations", search_radius="100 Meters")

    audit_dir = Path(os.environ["HONUA_ARCPY_AUDIT_DIR"])
    files = list(audit_dir.glob("audit-*.jsonl"))
    assert files, "expected an audit JSONL file"
    records = [
        json.loads(line)
        for line in files[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    stub_records = [r for r in records if r["function"] == "analysis.Near"]
    assert stub_records, "stub call analysis.Near was not audited"
    rec = stub_records[-1]
    assert rec["status"] == "error"
    assert rec["error_kind"] == "unsupported"
    # The redacted args/kwargs must round-trip the caller's payload so the
    # migration tool can pivot on what was attempted, not just the function
    # name.
    assert rec["args"] == ["roads", "stations"]
    assert rec["kwargs"] == {"search_radius": "100 Meters"}
