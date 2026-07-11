"""Management shim: session aliases, source-backed selection, admin routing."""

from __future__ import annotations

import pytest

import honua_gp


def test_make_feature_layer_registers_alias(stub_clients) -> None:
    honua_gp.management.MakeFeatureLayer("roads", "roads_lyr", where_clause="STATUS = 'OPEN'")
    alias = honua_gp.get_session().get_layer("roads_lyr")
    assert alias is not None
    assert alias.source == "roads"
    assert alias.where == "STATUS = 'OPEN'"


def test_make_feature_layer_overwrite_protection(stub_clients) -> None:
    honua_gp.management.MakeFeatureLayer("roads", "roads_lyr")
    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        honua_gp.management.MakeFeatureLayer("roads_alt", "roads_lyr")

    honua_gp.env.overwriteOutput = True
    honua_gp.management.MakeFeatureLayer("roads_alt", "roads_lyr")
    assert honua_gp.get_session().get_layer("roads_lyr").source == "roads_alt"


def test_get_count_uses_make_feature_layer_workspace() -> None:
    """GetCount over an alias must project the alias-bound workspace.

    The alias stores the workspace from ``MakeFeatureLayer(..., workspace=...)``.
    Counting ``alias.source`` directly loses that workspace and builds a
    descriptor for service ``roads`` instead of the intended workspace service.
    """

    captured: dict[str, object] = {}

    class _RecordingSource:
        def query(self, **_: object) -> object:
            class _Result:
                total_count = 0
                features: list[object] = []

            return _Result()

    class _RecordingClient:
        def source(self, descriptor: object) -> object:
            captured["descriptor"] = descriptor
            return _RecordingSource()

    honua_gp.configure(client=_RecordingClient())
    honua_gp.management.MakeFeatureLayer(
        "roads",
        "roads_lyr",
        workspace="honua://services/transport",
    )

    assert honua_gp.management.GetCount("roads_lyr") == 0
    assert captured["descriptor"]["locator"] == {"serviceId": "transport", "layerId": 0}


def test_select_layer_by_attribute_updates_where_and_returns_count(stub_clients) -> None:
    honua_gp.management.MakeFeatureLayer("roads", "roads_lyr")
    selection = honua_gp.management.SelectLayerByAttribute(
        "roads_lyr", "NEW_SELECTION", "STATUS = 'OPEN'"
    )
    assert selection.layer_name == "roads_lyr"
    assert isinstance(selection.count, int)
    assert honua_gp.get_session().get_layer("roads_lyr").where == "STATUS = 'OPEN'"

    further = honua_gp.management.SelectLayerByAttribute(
        "roads_lyr", "SUBSET_SELECTION", "name LIKE 'A%'"
    )
    assert "AND" in further.where


def test_select_layer_by_attribute_applies_invert_where_clause(stub_clients) -> None:
    honua_gp.management.MakeFeatureLayer("roads", "roads_lyr")
    selection = honua_gp.management.SelectLayerByAttribute(
        "roads_lyr",
        "NEW_SELECTION",
        "STATUS = 'OPEN'",
        invert_where_clause=True,
    )
    assert selection.where == "NOT (STATUS = 'OPEN')"
    assert honua_gp.get_session().get_layer("roads_lyr").where == "NOT (STATUS = 'OPEN')"


def test_select_layer_by_attribute_switch_is_unsupported(stub_clients) -> None:
    # arcpy SWITCH_SELECTION inverts the prior selection set (OIDs), which we
    # cannot model as a SQL where clause; the previous behaviour silently
    # cleared the selection. Surface it as unsupported instead.
    honua_gp.management.MakeFeatureLayer("roads", "roads_lyr")
    with pytest.raises(honua_gp.HonuaGpUnsupportedError) as info:
        honua_gp.management.SelectLayerByAttribute("roads_lyr", "SWITCH_SELECTION")
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

    honua_gp.management.MakeFeatureLayer("roads", "roads_lyr")
    with pytest.raises(honua_gp.HonuaGpUnsupportedError):
        honua_gp.management.SelectLayerByAttribute("roads_lyr", "SWITCH_SELECTION")

    audit_dir = Path(os.environ["HONUA_GP_AUDIT_DIR"])
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
    honua_gp.management.MakeFeatureLayer("roads", "roads_lyr")
    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        honua_gp.management.SelectLayerByAttribute("roads_lyr", "BOGUS_MODE", "STATUS = 'OPEN'")


def test_select_layer_by_attribute_validation_failures_are_audited(stub_clients) -> None:
    """Pre-dispatch validation failures (missing alias, unknown selection_type)
    must still write one JSONL audit line under the base function name so the
    every-shim-call audit contract documented in
    ``docs/honua-gp/README.md`` holds. Previously these paths raised
    before entering ``record_call`` and produced no audit record at all."""

    import json
    import os
    from pathlib import Path

    honua_gp.management.MakeFeatureLayer("roads", "roads_lyr")

    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        honua_gp.management.SelectLayerByAttribute("does_not_exist", "NEW_SELECTION", "STATUS = 'OPEN'")
    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        honua_gp.management.SelectLayerByAttribute("roads_lyr", "BOGUS_MODE", "STATUS = 'OPEN'")

    audit_dir = Path(os.environ["HONUA_GP_AUDIT_DIR"])
    files = list(audit_dir.glob("audit-*.jsonl"))
    assert files, "expected an audit JSONL file"
    records = [
        json.loads(line)
        for line in files[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    sla_errors = [
        rec
        for rec in records
        if rec["function"] == "management.SelectLayerByAttribute" and rec.get("status") == "error"
    ]
    # Two failures => two error-status audit records (one per call), each
    # keyed under the base function name and tagged with the shared
    # ``configuration`` ``error_kind`` from ``HonuaGpConfigurationError``
    # so operators can pivot on the failure category.
    assert len(sla_errors) == 2
    assert {rec["error_kind"] for rec in sla_errors} == {"configuration"}


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

    honua_gp.configure(client=_ExplodingClient())
    honua_gp.management.MakeFeatureLayer("roads", "roads_lyr")

    with pytest.raises(honua_gp.ExecuteError) as info:
        honua_gp.management.SelectLayerByAttribute(
            "roads_lyr", "NEW_SELECTION", "STATUS = 'OPEN'"
        )
    assert info.value.error_kind == "RuntimeError"

    audit_dir = Path(os.environ["HONUA_GP_AUDIT_DIR"])
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

    honua_gp.configure(client=_ExplodingClient())
    honua_gp.management.MakeFeatureLayer("roads", "roads_lyr", where_clause="STATUS = 'OPEN'")

    alias = honua_gp.get_session().get_layer("roads_lyr")
    assert alias is not None
    assert alias.where == "STATUS = 'OPEN'"
    original_selection = dict(alias.selection)

    with pytest.raises(honua_gp.ExecuteError):
        honua_gp.management.SelectLayerByAttribute(
            "roads_lyr", "SUBSET_SELECTION", "name LIKE 'A%'"
        )

    # The alias.where / alias.selection must still reflect the prior state,
    # not the candidate where that the backend rejected.
    assert alias.where == "STATUS = 'OPEN'"
    assert alias.selection == original_selection


def test_get_count_with_and_without_selection(stub_clients) -> None:
    honua_gp.management.MakeFeatureLayer("roads", "roads_lyr")
    full = honua_gp.management.GetCount("roads_lyr")
    honua_gp.management.SelectLayerByAttribute("roads_lyr", "NEW_SELECTION", "STATUS = 'OPEN'")
    filtered = honua_gp.management.GetCount("roads_lyr")
    assert isinstance(full, int)
    assert isinstance(filtered, int)


def test_get_count_resolve_failure_is_audited(stub_clients) -> None:
    """A pre-dispatch resolve failure must still write one JSONL audit line.

    ``GetCount(None)`` used to raise ``HonuaGpResolveError`` outside the
    surrounding ``record_call``, so the documented "every shim call writes
    one JSONL line" contract was violated -- operators had no record of the
    refused call. The alias lookup and resolve now run inside the audit
    context so resolve / configuration failures land in the JSONL stream.
    """

    import json
    import os
    from pathlib import Path

    with pytest.raises(honua_gp.HonuaGpResolveError):
        honua_gp.management.GetCount(None)

    audit_dir = Path(os.environ["HONUA_GP_AUDIT_DIR"])
    files = list(audit_dir.glob("audit-*.jsonl"))
    assert files, "expected an audit JSONL file"
    records = [
        json.loads(line)
        for line in files[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    refused = [r for r in records if r["function"] == "management.GetCount"]
    assert refused, "GetCount(None) refusal was not audited"
    assert refused[-1]["status"] == "error"
    # ``HonuaGpResolveError`` carries ``error_kind="resolve"`` so operators
    # can pivot on the failure category in the JSONL stream.
    assert refused[-1]["error_kind"] == "resolve"


def test_describe_returns_schema_shaped_result(stub_clients) -> None:
    """Describe fetches the FeatureServer layer schema and projects it onto
    an arcpy-shaped DescribeResult: shapeType, fields, spatialReference,
    OIDFieldName all come from the stub's canned ``segments`` layer."""

    honua_gp.env.workspace = "honua://services/legacy"
    result = honua_gp.Describe("segments")

    assert result.name == "segments"
    assert result.dataType == "FeatureClass"
    assert result.shapeType == "Polyline"
    assert result.OIDFieldName == "OBJECTID"
    assert result.spatialReference is not None
    assert result.spatialReference.factoryCode == 4326
    assert result.spatialReference.wkid == 4326
    field_names = {f.name for f in result.fields}
    assert field_names == {"OBJECTID", "STATUS", "LENGTH_KM", "SHAPE"}
    by_name = {f.name: f for f in result.fields}
    assert by_name["OBJECTID"].type == "OID"
    assert by_name["STATUS"].type == "String"
    assert by_name["STATUS"].aliasName == "Status"
    assert by_name["STATUS"].length == 20
    assert by_name["LENGTH_KM"].type == "Double"
    assert by_name["SHAPE"].type == "Geometry"

    # Top-level ``honua_gp.Describe`` and ``honua_gp.management.Describe``
    # must be the same callable, mirroring real arcpy's module-level
    # ``arcpy.Describe``.
    assert honua_gp.Describe is honua_gp.management.Describe


def test_describe_is_audited_as_supported(stub_clients) -> None:
    import json
    import os
    from pathlib import Path

    honua_gp.env.workspace = "honua://services/legacy"
    honua_gp.Describe("segments")

    audit_dir = Path(os.environ["HONUA_GP_AUDIT_DIR"])
    files = list(audit_dir.glob("audit-*.jsonl"))
    assert files, "expected an audit JSONL file"
    records = [
        json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    describe_records = [r for r in records if r["function"] == "management.Describe"]
    assert describe_records and describe_records[-1]["status"] == "ok"


def test_describe_accepts_and_audits_data_type_argument(stub_clients) -> None:
    """arcpy's documented ``Describe(value, {datatype})`` form must not crash
    at the wrapper boundary. honua-gp does not honor the ``data_type`` filter
    (the manifest marks it unsupported), so the call is accepted, produces the
    same result as the one-arg form, and the supplied ``data_type`` is recorded
    in the audit trail rather than being silently swallowed."""

    import json
    import os
    from pathlib import Path

    honua_gp.env.workspace = "honua://services/legacy"

    # Passing data_type as a second positional (arcpy's documented form) must
    # NOT raise, and must yield the same Describe result as the one-arg call.
    plain = honua_gp.Describe("segments")
    with_type = honua_gp.Describe("segments", "FeatureClass")

    assert with_type.name == plain.name
    assert with_type.dataType == plain.dataType
    assert with_type.shapeType == plain.shapeType
    assert with_type.OIDFieldName == plain.OIDFieldName
    assert {f.name for f in with_type.fields} == {f.name for f in plain.fields}

    # The ignored-but-accepted data_type value is audited so operators can see
    # it was supplied.
    audit_dir = Path(os.environ["HONUA_GP_AUDIT_DIR"])
    files = list(audit_dir.glob("audit-*.jsonl"))
    assert files, "expected an audit JSONL file"
    records = [
        json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    describe_records = [r for r in records if r["function"] == "management.Describe"]
    assert describe_records, "Describe call was not audited"
    typed = [r for r in describe_records if r["kwargs"].get("data_type") == "FeatureClass"]
    assert typed, "Describe(path, data_type) did not record data_type in the audit trail"
    assert typed[-1]["status"] == "ok"


def test_list_fields_returns_all_fields_by_default(stub_clients) -> None:
    honua_gp.env.workspace = "honua://services/legacy"
    fields = honua_gp.management.ListFields("segments")
    assert isinstance(fields, list)
    assert {f.name for f in fields} == {"OBJECTID", "STATUS", "LENGTH_KM", "SHAPE"}

    # Also reachable as the top-level ``honua_gp.ListFields`` re-export.
    assert honua_gp.ListFields is honua_gp.management.ListFields


def test_list_fields_wild_card_filters_by_name(stub_clients) -> None:
    honua_gp.env.workspace = "honua://services/legacy"
    fields = honua_gp.management.ListFields("segments", wild_card="STAT*")
    assert [f.name for f in fields] == ["STATUS"]

    # Case-insensitive, per real arcpy.
    fields_lower = honua_gp.management.ListFields("segments", wild_card="stat*")
    assert [f.name for f in fields_lower] == ["STATUS"]


def test_list_fields_field_type_filters_by_type(stub_clients) -> None:
    honua_gp.env.workspace = "honua://services/legacy"
    fields = honua_gp.management.ListFields("segments", field_type="String")
    assert [f.name for f in fields] == ["STATUS"]

    # Semicolon-delimited multi-type filter, arcpy ValueTable style.
    fields = honua_gp.management.ListFields("segments", field_type="String;Double")
    assert {f.name for f in fields} == {"STATUS", "LENGTH_KM"}

    # A Python sequence is also accepted.
    fields = honua_gp.management.ListFields("segments", field_type=["OID"])
    assert [f.name for f in fields] == ["OBJECTID"]

    # "All" (arcpy's own sentinel) disables filtering entirely.
    fields = honua_gp.management.ListFields("segments", field_type="All")
    assert len(fields) == 4


def test_list_fields_no_match_returns_empty_list(stub_clients) -> None:
    honua_gp.env.workspace = "honua://services/legacy"
    fields = honua_gp.management.ListFields("segments", field_type="Raster")
    assert fields == []

    fields = honua_gp.management.ListFields("segments", wild_card="NO_SUCH_FIELD*")
    assert fields == []


def test_describe_dataset_not_found_raises_execute_error(stub_clients) -> None:
    """A dataset the stub's catalog does not know about must surface as an
    ``ExecuteError`` (mirroring how a real 404 from honua-server would be
    wrapped), not a bare exception or a silent empty result."""

    honua_gp.env.workspace = "honua://services/does-not-exist"
    with pytest.raises(honua_gp.ExecuteError) as info:
        honua_gp.Describe("segments")
    assert info.value.function == "management.Describe"


def test_list_fields_dataset_not_found_raises_execute_error(stub_clients) -> None:
    honua_gp.env.workspace = "honua://services/does-not-exist"
    with pytest.raises(honua_gp.ExecuteError) as info:
        honua_gp.management.ListFields("segments")
    assert info.value.function == "management.ListFields"


def test_describe_unconfigured_client_raises_configuration_error() -> None:
    """A client without ``feature_server()`` must fail with a clear
    configuration error rather than an ``AttributeError``."""

    class _NoFeatureServerClient:
        def source(self, descriptor: object) -> object:  # pragma: no cover - unused here
            raise AssertionError("source() should not be called by Describe")

    honua_gp.configure(client=_NoFeatureServerClient())
    honua_gp.env.workspace = "honua://services/legacy"
    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        honua_gp.Describe("segments")


def test_field_describe_dataclass_supports_alias_name(stub_clients) -> None:
    # FieldDescribe uses arcpy's own property name (``aliasName``, not
    # ``alias``) so a script written against real ``arcpy.Field`` objects
    # keeps working unmodified.
    field = honua_gp.FieldDescribe(name="STATUS", type="String", aliasName="Status")
    assert field.aliasName == "Status"


def test_add_field_is_stub_until_admin_contract_lands(stub_clients) -> None:
    # apply_manifest exists but has no add-field translation; surface the gap
    # explicitly so customer scripts do not silently no-op.
    with pytest.raises(honua_gp.HonuaGpUnsupportedError):
        honua_gp.management.AddField("segments", "route_id", field_type="LONG")


def test_field_describe_dataclass_is_importable(stub_clients) -> None:
    # FieldDescribe and DescribeResult are kept so eventual non-stub
    # implementations have a stable return shape; they remain importable.
    assert honua_gp.FieldDescribe(name="OBJECTID", type="OID").name == "OBJECTID"
    assert honua_gp.DescribeResult(name="segments").name == "segments"


def test_calculate_field_is_an_unsupported_stub(stub_clients) -> None:
    """``management.CalculateField`` is a stub: honua-server classifies
    ``data-management.calculate-field`` as CanServe=false, so it is never a
    standalone OGC process and a one-shot call 404s. The shim raises a
    client-side ``HonuaGpUnsupportedError`` without touching the transport."""

    client, _ = stub_clients
    with pytest.raises(honua_gp.HonuaGpUnsupportedError):
        honua_gp.management.CalculateField(
            "honua://services/segments/2", "scaled_speed", "speed * 1.1", where_clause="speed > 0"
        )
    assert client.ogc_processes().calls == []


def test_stubs_raise_with_replacement_hints(stub_clients) -> None:
    with pytest.raises(honua_gp.HonuaGpUnsupportedError):
        honua_gp.management.Sort("roads", "out", [["name", "ASCENDING"]])
    with pytest.raises(honua_gp.HonuaGpUnsupportedError):
        honua_gp.management.Append(["a"], "b")
    with pytest.raises(honua_gp.HonuaGpUnsupportedError):
        honua_gp.management.CreateFeatureclass("ws", "fc", "POLYGON")


def test_stub_calls_are_audited_with_status_error(stub_clients) -> None:
    """Every shim call must write one JSONL line, including stubs that raise
    immediately. The previous behaviour skipped the audit so operators had no
    record of the rejected call."""

    import json
    import os
    from pathlib import Path

    with pytest.raises(honua_gp.HonuaGpUnsupportedError):
        honua_gp.analysis.Near("roads", "stations", search_radius="100 Meters")

    audit_dir = Path(os.environ["HONUA_GP_AUDIT_DIR"])
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
