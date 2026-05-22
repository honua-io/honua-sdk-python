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


def test_get_count_with_and_without_selection(stub_clients) -> None:
    honua_arcpy.management.MakeFeatureLayer("roads", "roads_lyr")
    full = honua_arcpy.management.GetCount("roads_lyr")
    honua_arcpy.management.SelectLayerByAttribute("roads_lyr", "NEW_SELECTION", "STATUS = 'OPEN'")
    filtered = honua_arcpy.management.GetCount("roads_lyr")
    assert isinstance(full, int)
    assert isinstance(filtered, int)


def test_describe_returns_dataclass_with_fields(stub_clients) -> None:
    described = honua_arcpy.Describe("segments")
    assert described.dataType == "FeatureClass"
    assert any(field.name == "OBJECTID" for field in described.fields)


def test_list_fields_filter_by_wildcard_and_type(stub_clients) -> None:
    all_fields = honua_arcpy.management.ListFields("segments")
    assert any(field.name == "STATUS" for field in all_fields)

    str_only = honua_arcpy.management.ListFields("segments", field_type="String")
    assert all(field.type == "String" for field in str_only)
    assert all_fields != str_only  # OBJECTID is OID, not String

    wild = honua_arcpy.management.ListFields("segments", wild_card="STAT*")
    assert [field.name for field in wild] == ["STATUS"]


def test_add_field_calls_admin_apply(stub_clients) -> None:
    _, admin = stub_clients
    honua_arcpy.management.AddField("segments", "route_id", field_type="LONG")
    assert any(event["kind"] == "apply_manifest" for event in admin.events)


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
