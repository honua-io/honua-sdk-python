"""``arcpy.management`` shim -- 20 functions (9 mapped, 11 stubbed).

Mapped functions split into three backends:

* ``process``: CalculateField, Dissolve, Copy, Delete, Project (5).
* ``session``: MakeFeatureLayer, MakeTableView (2 -- in-process aliases).
* ``source``: SelectLayerByAttribute, GetCount (2 -- via Source facade;
  GetCount is ``partial`` until the Source facade exposes a count-only
  helper).

The remaining 11 raise ``HonuaArcpyUnsupportedError`` with replacement hints,
including the five admin-targeted entries (AddField, DeleteField, Rename,
ListFields, Describe) that previously routed through a partial admin shim --
the real ``HonuaAdminClient`` does not yet expose per-layer schema mutation
or reading, so we surface the gap explicitly until the contract lands.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .._compat import anchor_for, entry_for
from .._dispatch import (
    dispatch_process,
    dispatch_session,
    raise_unsupported,
)
from .._errors import (
    ExecuteError,
    HonuaArcpyConfigurationError,
    HonuaArcpyResolveError,
)
from .._resolve import descriptor_mapping, resolve
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


_SELECTION_TYPES = {
    "NEW_SELECTION",
    "ADD_TO_SELECTION",
    "REMOVE_FROM_SELECTION",
    "SUBSET_SELECTION",
    "CLEAR_SELECTION",
    "SWITCH_SELECTION",
}


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

    # SWITCH_SELECTION is detected *before* the surrounding ``record_call``
    # so ``raise_unsupported`` owns its own variant-scoped audit line and we
    # do not double-audit (one base-name line from the outer ``record_call``
    # plus one variant-scoped line from ``raise_unsupported``). The
    # surrounding ``record_call`` below covers the rest of the validation
    # paths (missing alias, unknown selection_type, backend failures) so
    # every other rejection still produces exactly one JSONL line.
    normalized_type = (selection_type or "NEW_SELECTION").upper()
    if normalized_type == "SWITCH_SELECTION":
        raise_unsupported(
            f"{qualified}(selection_type=SWITCH_SELECTION)",
            args=(in_layer_or_view, selection_type, where_clause),
            kwargs={"invert_where_clause": invert_where_clause},
            compat_anchor=anchor_for(qualified),
            replacement_hint=(
                "SWITCH_SELECTION depends on the prior OID set, which the shim "
                "cannot model client-side. Re-issue SelectLayerByAttribute with "
                "the negated predicate (invert_where_clause=True) instead."
            ),
        )

    with record_call(qualified, args=(in_layer_or_view, selection_type, where_clause), kwargs={
        "invert_where_clause": invert_where_clause,
    }, writer=session.audit_writer()) as record:
        alias = session.get_layer(str(in_layer_or_view)) if isinstance(in_layer_or_view, str) else None
        if alias is None:
            raise HonuaArcpyConfigurationError(
                f"SelectLayerByAttribute requires a layer registered via MakeFeatureLayer; got {in_layer_or_view!r}."
            )

        if normalized_type not in _SELECTION_TYPES:
            raise HonuaArcpyConfigurationError(
                f"SelectLayerByAttribute selection_type={selection_type!r} is not recognized; "
                f"expected one of {sorted(_SELECTION_TYPES)}."
            )

        invert = bool(invert_where_clause) if invert_where_clause is not None else False
        effective_where = where_clause
        if effective_where and invert:
            effective_where = f"NOT ({effective_where})"

        # Compute the candidate selection but do NOT commit it to the alias
        # until _layer_count succeeds. Mutating alias.where / alias.selection
        # up-front would leave a failed selection on the alias if the backend
        # call raises, so subsequent cursors would query against a selection
        # that did not actually take effect.
        candidate_where = _apply_selection(alias.where, normalized_type, effective_where)
        try:
            count = _layer_count(session, alias, candidate_where)
        except (ExecuteError, HonuaArcpyConfigurationError, HonuaArcpyResolveError):
            raise
        except Exception as exc:
            raise ExecuteError(
                f"{qualified} failed: {exc}",
                function=qualified,
                error_kind=exc.__class__.__name__,
                compat_anchor=anchor_for(qualified),
                cause=exc,
            ) from exc
        alias.where = candidate_where
        alias.selection = {
            "selection_type": normalized_type,
            "where": candidate_where,
            "invert": invert,
        }
        record["result_shape"] = _shape_of({"layer": alias.name, "count": count})
        return Selection(
            layer_name=alias.name,
            count=count,
            where=candidate_where,
            selection_type=normalized_type,
        )


def _apply_selection(existing: str | None, selection_type: str, where: str | None) -> str | None:
    if selection_type == "CLEAR_SELECTION":
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


def _layer_count(session, alias: LayerAlias, where: str | None) -> int:
    """Count features for an alias under ``where``.

    ``where`` is the candidate predicate to count against; callers pass the
    selection they are about to commit so the count can be observed before
    mutating ``alias.where`` / ``alias.selection``. Backend failures
    propagate so the audit record (and the caller) see the real exception
    instead of a misleading ``Selection(count=0)`` success.
    """

    client = session.client()
    if not hasattr(client, "source"):
        raise HonuaArcpyConfigurationError("Configured Honua client does not expose Source facade.")
    resolved = resolve(alias.source, session=session)
    descriptor = descriptor_mapping(resolved, session=session)
    source = client.source(descriptor)
    result = source.query(where=where) if where else source.query()
    total = getattr(result, "total_count", None)
    if isinstance(total, int):
        return total
    features = getattr(result, "features", None)
    if features is not None:
        return len(features)
    return 0


def GetCount(in_rows: Any) -> int:
    from .._audit import record_call, _shape_of

    qualified = "management.GetCount"
    session = get_session()
    layer_name = str(in_rows)
    alias = session.get_layer(layer_name)
    resolved = (
        resolve(alias.source, session=session)
        if alias is not None
        else resolve(in_rows, session=session)
    )
    where = alias.where if alias is not None else None

    with record_call(qualified, args=(in_rows,), kwargs={}, writer=session.audit_writer()) as record:
        client = session.client()
        if not hasattr(client, "source"):
            raise HonuaArcpyConfigurationError("Configured Honua client does not expose Source facade.")
        descriptor = descriptor_mapping(resolved, session=session)
        try:
            source = client.source(descriptor)
            result = source.query(where=where) if where else source.query()
        except (ExecuteError, HonuaArcpyConfigurationError, HonuaArcpyResolveError):
            raise
        except Exception as exc:
            raise ExecuteError(
                f"{qualified} failed: {exc}",
                function=qualified,
                error_kind=exc.__class__.__name__,
                compat_anchor=anchor_for(qualified),
                cause=exc,
            ) from exc
        total = getattr(result, "total_count", None)
        if isinstance(total, int):
            count = total
        else:
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
# Schema-shaped value objects (kept for typed return shapes)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


def AddField(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.AddField", args=args, kwargs=kwargs)


def DeleteField(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.DeleteField", args=args, kwargs=kwargs)


def Rename(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.Rename", args=args, kwargs=kwargs)


def ListFields(*args: Any, **kwargs: Any) -> Iterable[FieldDescribe]:
    raise_unsupported("management.ListFields", args=args, kwargs=kwargs)


def Describe(*args: Any, **kwargs: Any) -> DescribeResult:
    """``arcpy.Describe(value)`` -- not currently supported by HonuaAdminClient."""

    raise_unsupported("management.Describe", args=args, kwargs=kwargs)


def SelectLayerByLocation(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.SelectLayerByLocation", args=args, kwargs=kwargs)


def Append(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.Append", args=args, kwargs=kwargs)


def Merge(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.Merge", args=args, kwargs=kwargs)


def CreateFeatureclass(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.CreateFeatureclass", args=args, kwargs=kwargs)


def CreateTable(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.CreateTable", args=args, kwargs=kwargs)


def Sort(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.Sort", args=args, kwargs=kwargs)


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
