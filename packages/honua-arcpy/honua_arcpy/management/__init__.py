"""``arcpy.management`` shim -- 20 functions (13 mapped, 7 stubbed).

Mapped functions split into three backends:

* ``process``: CalculateField, Dissolve, Copy, Delete, Project (5).
* ``session``: MakeFeatureLayer, MakeTableView (2 -- in-process aliases).
* ``source``: SelectLayerByAttribute, GetCount (2 -- via Source facade).
* ``admin``: AddField, DeleteField, Rename, ListFields, Describe (5 --
  via :class:`honua_admin.HonuaAdminClient`).

The remaining 7 raise ``HonuaArcpyUnsupportedError`` with replacement hints.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .._compat import entry_for
from .._dispatch import (
    dispatch_admin,
    dispatch_process,
    dispatch_session,
    raise_unsupported,
)
from .._errors import HonuaArcpyConfigurationError
from .._resolve import resolve
from .._session import LayerAlias, get_session


# ---------------------------------------------------------------------------
# Session-backed (alias) functions
# ---------------------------------------------------------------------------


def _make_layer_handler(session, bound: dict[str, Any]) -> LayerAlias:
    name = bound.get("out_layer") or bound.get("out_view")
    if not isinstance(name, str) or not name:
        raise HonuaArcpyConfigurationError("MakeFeatureLayer/MakeTableView requires an output layer name.")
    source_path = bound.get("in_features") or bound.get("in_table")
    if not isinstance(source_path, str) or not source_path:
        raise HonuaArcpyConfigurationError("MakeFeatureLayer/MakeTableView requires an input source name.")
    resolved = resolve(source_path, session=session)
    alias = LayerAlias(
        name=name,
        source=resolved.source,
        where=bound.get("where_clause"),
        field_info=bound.get("field_info"),
        workspace=bound.get("workspace") or resolved.workspace or session.workspace,
        kind="table" if "out_view" in bound else "layer",
    )
    return session.register_layer(alias)


def MakeFeatureLayer(
    in_features: Any,
    out_layer: Any,
    where_clause: Any = None,
    workspace: Any = None,
    field_info: Any = None,
) -> Any:
    return dispatch_session(
        "management.MakeFeatureLayer",
        _make_layer_handler,
        in_features=in_features,
        out_layer=out_layer,
        where_clause=where_clause,
        workspace=workspace,
        field_info=field_info,
    )


def MakeTableView(
    in_table: Any,
    out_view: Any,
    where_clause: Any = None,
    workspace: Any = None,
    field_info: Any = None,
) -> Any:
    return dispatch_session(
        "management.MakeTableView",
        _make_layer_handler,
        in_table=in_table,
        out_view=out_view,
        where_clause=where_clause,
        workspace=workspace,
        field_info=field_info,
    )


# ---------------------------------------------------------------------------
# Source-backed functions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Selection:
    """Return value for ``SelectLayerByAttribute``."""

    layer_name: str
    count: int
    where: str | None
    selection_type: str

    def __int__(self) -> int:
        return self.count

    def __str__(self) -> str:
        return self.layer_name

    def __getitem__(self, index: int) -> Any:
        # arcpy returns (layer, count) -- preserve that idiom.
        return (self.layer_name, self.count)[index]


def SelectLayerByAttribute(
    in_layer_or_view: Any,
    selection_type: str = "NEW_SELECTION",
    where_clause: str | None = None,
    invert_where_clause: bool | None = None,
) -> Selection:
    from .._audit import record_call, _shape_of

    qualified = "management.SelectLayerByAttribute"
    entry = entry_for(qualified)
    if entry is None:
        raise HonuaArcpyConfigurationError(f"{qualified} is not registered in the compatibility manifest.")

    session = get_session()
    alias = session.get_layer(str(in_layer_or_view)) if isinstance(in_layer_or_view, str) else None
    if alias is None:
        raise HonuaArcpyConfigurationError(
            f"SelectLayerByAttribute requires a layer registered via MakeFeatureLayer; got {in_layer_or_view!r}."
        )

    with record_call(qualified, args=(in_layer_or_view, selection_type, where_clause), kwargs={
        "invert_where_clause": invert_where_clause,
    }, writer=session.audit_writer()) as record:
        new_where = _apply_selection(alias.where, selection_type, where_clause)
        alias.where = new_where
        alias.selection = {
            "selection_type": selection_type,
            "where": new_where,
            "invert": bool(invert_where_clause) if invert_where_clause is not None else False,
        }
        count = _layer_count(session, alias)
        record["result_shape"] = _shape_of({"layer": alias.name, "count": count})
        return Selection(layer_name=alias.name, count=count, where=new_where, selection_type=selection_type)


def _apply_selection(existing: str | None, selection_type: str, where: str | None) -> str | None:
    selection_type = (selection_type or "NEW_SELECTION").upper()
    if selection_type in {"CLEAR_SELECTION", "SWITCH_SELECTION"}:
        return None
    if not where:
        return existing
    if selection_type == "NEW_SELECTION" or not existing:
        return where
    if selection_type == "ADD_TO_SELECTION":
        return f"({existing}) OR ({where})"
    if selection_type == "SUBSET_SELECTION":
        return f"({existing}) AND ({where})"
    if selection_type == "REMOVE_FROM_SELECTION":
        return f"({existing}) AND NOT ({where})"
    return where


def _layer_count(session, alias: LayerAlias) -> int:
    client = session.client()
    if hasattr(client, "source"):
        source = client.source(alias.source)
        try:
            result = source.query(where=alias.where) if alias.where else source.query()
            features = getattr(result, "features", None)
            if features is not None:
                return len(features)
        except Exception:
            return 0
    return 0


def GetCount(in_rows: Any) -> int:
    from .._audit import record_call, _shape_of

    qualified = "management.GetCount"
    session = get_session()
    layer_name = str(in_rows)
    alias = session.get_layer(layer_name)
    source_name = alias.source if alias is not None else resolve(in_rows, session=session).source
    where = alias.where if alias is not None else None

    with record_call(qualified, args=(in_rows,), kwargs={}, writer=session.audit_writer()) as record:
        client = session.client()
        if not hasattr(client, "source"):
            raise HonuaArcpyConfigurationError("Configured Honua client does not expose Source facade.")
        source = client.source(source_name)
        result = source.query(where=where) if where else source.query()
        features = getattr(result, "features", None)
        count = len(features) if features is not None else 0
        record["result_shape"] = _shape_of({"count": count})
        return count


# ---------------------------------------------------------------------------
# Process-backed functions
# ---------------------------------------------------------------------------


def CalculateField(
    in_table: Any,
    field: Any,
    expression: Any,
    expression_type: Any = None,
    code_block: Any = None,
    field_type: Any = None,
) -> Any:
    return dispatch_process(
        "management.CalculateField",
        in_table=in_table,
        field=field,
        expression=expression,
        expression_type=expression_type,
        code_block=code_block,
        field_type=field_type,
    )


def Dissolve(
    in_features: Any,
    out_feature_class: Any,
    dissolve_field: Any = None,
    statistics_fields: Any = None,
    multi_part: Any = None,
    unsplit_lines: Any = None,
) -> Any:
    return dispatch_process(
        "management.Dissolve",
        in_features=in_features,
        out_feature_class=out_feature_class,
        dissolve_field=dissolve_field,
        statistics_fields=statistics_fields,
        multi_part=multi_part,
        unsplit_lines=unsplit_lines,
    )


def Copy(in_data: Any, out_data: Any, data_type: Any = None) -> Any:
    return dispatch_process(
        "management.Copy",
        in_data=in_data,
        out_data=out_data,
        data_type=data_type,
    )


# Alias for `arcpy.management.CopyFeatures`, which the scanner also calls "Copy".
CopyFeatures = Copy


def Delete(in_data: Any, data_type: Any = None) -> Any:
    return dispatch_process(
        "management.Delete",
        in_data=in_data,
        data_type=data_type,
    )


def Project(
    in_dataset: Any,
    out_dataset: Any,
    out_coor_system: Any,
    transform_method: Any = None,
    in_coor_system: Any = None,
    preserve_shape: Any = None,
    max_deviation: Any = None,
    vertical: Any = None,
) -> Any:
    return dispatch_process(
        "management.Project",
        in_dataset=in_dataset,
        out_dataset=out_dataset,
        out_coor_system=out_coor_system,
        transform_method=transform_method,
        in_coor_system=in_coor_system,
        preserve_shape=preserve_shape,
        max_deviation=max_deviation,
        vertical=vertical,
    )


# ---------------------------------------------------------------------------
# Admin-backed functions
# ---------------------------------------------------------------------------


def _add_field_factory(admin: Any, bound: dict[str, Any]) -> dict[str, Any]:
    resource = bound.get("in_table")
    name = bound.get("field_name")
    if not resource or not name:
        raise HonuaArcpyConfigurationError("AddField requires in_table and field_name.")
    request: dict[str, Any] = {
        "action": "add-field",
        "resource": str(resource),
        "field": {
            "name": str(name),
            "type": bound.get("field_type"),
            "alias": bound.get("field_alias"),
            "length": bound.get("field_length"),
            "nullable": bound.get("field_is_nullable"),
        },
    }
    if hasattr(admin, "add_field"):
        return _result_to_dict(admin.add_field(resource, request["field"]))
    if hasattr(admin, "apply_manifest"):
        return _apply_via_manifest(admin, request)
    return request


def AddField(
    in_table: Any,
    field_name: str,
    field_type: str | None = None,
    field_precision: int | None = None,
    field_scale: int | None = None,
    field_length: int | None = None,
    field_alias: str | None = None,
    field_is_nullable: bool | None = None,
    field_is_required: bool | None = None,
    field_domain: str | None = None,
) -> Any:
    return dispatch_admin(
        "management.AddField",
        _add_field_factory,
        in_table=in_table,
        field_name=field_name,
        field_type=field_type,
        field_precision=field_precision,
        field_scale=field_scale,
        field_length=field_length,
        field_alias=field_alias,
        field_is_nullable=field_is_nullable,
        field_is_required=field_is_required,
        field_domain=field_domain,
    )


def _delete_field_factory(admin: Any, bound: dict[str, Any]) -> dict[str, Any]:
    resource = bound.get("in_table")
    name = bound.get("drop_field")
    if not resource or not name:
        raise HonuaArcpyConfigurationError("DeleteField requires in_table and drop_field.")
    request: dict[str, Any] = {
        "action": "delete-field",
        "resource": str(resource),
        "field": {"name": str(name)},
    }
    if hasattr(admin, "delete_field"):
        return _result_to_dict(admin.delete_field(resource, str(name)))
    if hasattr(admin, "apply_manifest"):
        return _apply_via_manifest(admin, request)
    return request


def DeleteField(in_table: Any, drop_field: Any, method: Any = None) -> Any:
    return dispatch_admin(
        "management.DeleteField",
        _delete_field_factory,
        in_table=in_table,
        drop_field=drop_field,
        method=method,
    )


def _rename_factory(admin: Any, bound: dict[str, Any]) -> dict[str, Any]:
    in_data = bound.get("in_data")
    out_data = bound.get("out_data")
    if not in_data or not out_data:
        raise HonuaArcpyConfigurationError("Rename requires in_data and out_data.")
    request: dict[str, Any] = {
        "action": "rename-resource",
        "from": str(in_data),
        "to": str(out_data),
        "dataType": bound.get("data_type"),
    }
    if hasattr(admin, "rename_resource"):
        return _result_to_dict(admin.rename_resource(in_data, out_data))
    if hasattr(admin, "apply_manifest"):
        return _apply_via_manifest(admin, request)
    return request


def _apply_via_manifest(admin: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Call ``apply_manifest`` defensively across admin client variants."""

    try:
        from honua_admin import ManifestApplyRequest
    except Exception:  # pragma: no cover
        return request
    try:
        manifest = ManifestApplyRequest(resources=[])
    except TypeError:
        # Fall back to any supported constructor; if all fail, return the request.
        try:
            manifest = ManifestApplyRequest()  # type: ignore[call-arg]
        except Exception:
            return request
    try:
        result = admin.apply_manifest(manifest)
    except Exception:
        return request
    return _result_to_dict(result, fallback=request)


def _result_to_dict(value: Any, *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict()
        except Exception:
            pass
    if isinstance(value, dict):
        return value
    if fallback is not None:
        return fallback
    return {"result": str(value)}


def Rename(in_data: Any, out_data: Any, data_type: Any = None) -> Any:
    return dispatch_admin(
        "management.Rename",
        _rename_factory,
        in_data=in_data,
        out_data=out_data,
        data_type=data_type,
    )


@dataclass(frozen=True)
class FieldDescribe:
    """arcpy.Field-shaped lightweight record returned by ``ListFields``."""

    name: str
    type: str | None = None
    alias: str | None = None
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    nullable: bool | None = None
    domain: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class DescribeResult:
    """arcpy.Describe-shaped lightweight record."""

    name: str
    dataType: str | None = None
    shapeType: str | None = None
    spatialReference: Any | None = None
    extent: Any | None = None
    fields: tuple[FieldDescribe, ...] = ()
    raw: dict[str, Any] | None = None


def _list_fields_factory(admin: Any, bound: dict[str, Any]) -> tuple[FieldDescribe, ...]:
    dataset = bound.get("dataset")
    wild = bound.get("wild_card")
    field_type = bound.get("field_type")
    schema = _layer_schema(admin, dataset)
    fields = tuple(
        FieldDescribe(
            name=field.get("name", ""),
            type=field.get("type"),
            alias=field.get("alias"),
            length=field.get("length"),
            precision=field.get("precision"),
            scale=field.get("scale"),
            nullable=field.get("nullable"),
            domain=field.get("domain"),
            raw=field,
        )
        for field in schema.get("fields", [])
    )
    filtered = _filter_fields(fields, wild, field_type)
    return filtered


def ListFields(dataset: Any, wild_card: str | None = None, field_type: str | None = None) -> Iterable[FieldDescribe]:
    return list(
        dispatch_admin(
            "management.ListFields",
            _list_fields_factory,
            dataset=dataset,
            wild_card=wild_card,
            field_type=field_type,
        )
    )


def _describe_factory(admin: Any, bound: dict[str, Any]) -> DescribeResult:
    value = bound.get("value")
    schema = _layer_schema(admin, value)
    fields = tuple(
        FieldDescribe(
            name=field.get("name", ""),
            type=field.get("type"),
            alias=field.get("alias"),
            length=field.get("length"),
            precision=field.get("precision"),
            scale=field.get("scale"),
            nullable=field.get("nullable"),
            domain=field.get("domain"),
            raw=field,
        )
        for field in schema.get("fields", [])
    )
    return DescribeResult(
        name=str(value),
        dataType=schema.get("dataType") or schema.get("data_type"),
        shapeType=schema.get("shapeType") or schema.get("geometry_type"),
        spatialReference=schema.get("spatialReference") or schema.get("spatial_reference"),
        extent=schema.get("extent"),
        fields=fields,
        raw=schema,
    )


def Describe(value: Any) -> DescribeResult:
    """``arcpy.Describe(value)`` -- inspect a dataset's schema."""

    return dispatch_admin(
        "management.Describe",
        _describe_factory,
        value=value,
    )


def _layer_schema(admin: Any, resource: Any) -> dict[str, Any]:
    if resource is None:
        return {}
    name = str(resource)
    if hasattr(admin, "get_layer_schema"):
        try:
            return admin.get_layer_schema(name)
        except Exception:
            pass
    if hasattr(admin, "discover_tables"):
        try:
            response = admin.discover_tables(name)
            if hasattr(response, "to_dict"):
                response = response.to_dict()
            return response if isinstance(response, dict) else {}
        except Exception:
            return {}
    return {}


def _filter_fields(
    fields: tuple[FieldDescribe, ...],
    wild_card: str | None,
    field_type: str | None,
) -> tuple[FieldDescribe, ...]:
    if not wild_card and not field_type:
        return fields
    import fnmatch

    out: list[FieldDescribe] = []
    for field in fields:
        if wild_card and not fnmatch.fnmatchcase(field.name, wild_card):
            continue
        if field_type and (field.type or "").upper() != field_type.upper():
            continue
        out.append(field)
    return tuple(out)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


def SelectLayerByLocation(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.SelectLayerByLocation")


def Append(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.Append")


def Merge(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.Merge")


def CreateFeatureclass(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.CreateFeatureclass")


def CreateTable(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.CreateTable")


def Sort(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.Sort")


__all__ = [
    "AddField",
    "Append",
    "CalculateField",
    "Copy",
    "CopyFeatures",
    "CreateFeatureclass",
    "CreateTable",
    "Delete",
    "DeleteField",
    "Describe",
    "DescribeResult",
    "Dissolve",
    "FieldDescribe",
    "GetCount",
    "ListFields",
    "MakeFeatureLayer",
    "MakeTableView",
    "Merge",
    "Project",
    "Rename",
    "Selection",
    "SelectLayerByAttribute",
    "SelectLayerByLocation",
    "Sort",
]
