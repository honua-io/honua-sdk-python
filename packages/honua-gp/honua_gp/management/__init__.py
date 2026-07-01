"""``arcpy.management`` shim -- 20 functions.

Mapped functions split across backends:

* ``session``: MakeFeatureLayer, MakeTableView (in-process aliases).
* ``source``: SelectLayerByAttribute, GetCount (via the Source facade;
  GetCount is ``partial`` until the Source facade exposes a count-only helper).
* ``process``: CalculateField, Dissolve, Copy / CopyFeatures, Project --
  projected onto honua-server's layer-aware processes
  (``data-management.calculate-field`` / ``generalization.dissolve`` /
  ``data-management.copy-features`` / ``conversion.feature-project``) by
  :mod:`honua_gp._process_tools` and run as async OGC API Processes jobs.

The remaining stubs:

* ``Delete`` -- arcpy deletes a whole dataset; honua-server's
  ``data-management.delete-features`` only deletes features matching a filter
  inside a layer, so the semantics differ and faking it would do the wrong
  thing.
* The schema-shaped entries (AddField, DeleteField, Rename, ListFields,
  Describe) -- the real ``HonuaAdminClient`` does not yet expose per-layer
  schema mutation or reading, so we surface the gap explicitly.
* Append, Merge, CreateFeatureclass, CreateTable, Sort, SelectLayerByLocation
  -- no catalog op maps cleanly today.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .._compat import anchor_for, entry_for
from .._dispatch import (
    dispatch_session,
    raise_unsupported,
)
from .._errors import (
    ExecuteError,
    HonuaGpConfigurationError,
    HonuaGpResolveError,
)
from .._process_tools import Result, run_layer_process
from .._resolve import descriptor_mapping, resolve
from .._session import LayerAlias, get_session

# ---------------------------------------------------------------------------
# Session-backed (alias) functions
# ---------------------------------------------------------------------------


def _make_layer_handler(session, bound: dict[str, Any]) -> LayerAlias:
    name = bound.get("out_layer") or bound.get("out_view")
    if not isinstance(name, str) or not name:
        raise HonuaGpConfigurationError("MakeFeatureLayer/MakeTableView requires an output layer name.")
    source_path = bound.get("in_features") or bound.get("in_table")
    if not isinstance(source_path, str) or not source_path:
        raise HonuaGpConfigurationError("MakeFeatureLayer/MakeTableView requires an input source name.")
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
    from .._audit import _shape_of, record_call

    qualified = "management.SelectLayerByAttribute"
    entry = entry_for(qualified)
    if entry is None:
        raise HonuaGpConfigurationError(f"{qualified} is not registered in the compatibility manifest.")

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
            raise HonuaGpConfigurationError(
                f"SelectLayerByAttribute requires a layer registered via MakeFeatureLayer; got {in_layer_or_view!r}."
            )

        if normalized_type not in _SELECTION_TYPES:
            raise HonuaGpConfigurationError(
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
        except (ExecuteError, HonuaGpConfigurationError, HonuaGpResolveError):
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
        raise HonuaGpConfigurationError("Configured Honua client does not expose Source facade.")
    resolved = resolve(alias.name, session=session)
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
    from .._audit import _shape_of, record_call

    qualified = "management.GetCount"
    session = get_session()

    # Alias lookup, path resolution, and backend query all run inside the
    # surrounding ``record_call`` so the documented "every shim call writes
    # one JSONL line" contract holds even when resolution fails before the
    # backend is reached (e.g. ``GetCount(None)`` -> ``HonuaGpResolveError``,
    # or an unconfigured session -> ``HonuaGpConfigurationError``).
    with record_call(qualified, args=(in_rows,), kwargs={}, writer=session.audit_writer()) as record:
        layer_name = str(in_rows) if isinstance(in_rows, str) else None
        alias = session.get_layer(layer_name) if layer_name is not None else None
        resolved = resolve(alias.name if alias is not None else in_rows, session=session)
        where = alias.where if alias is not None else None

        client = session.client()
        if not hasattr(client, "source"):
            raise HonuaGpConfigurationError("Configured Honua client does not expose Source facade.")
        descriptor = descriptor_mapping(resolved, session=session)
        try:
            source = client.source(descriptor)
            result = source.query(where=where) if where else source.query()
        except (ExecuteError, HonuaGpConfigurationError, HonuaGpResolveError):
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
# Process-backed tools (layer-aware projection adapter)
# ---------------------------------------------------------------------------
# Dissolve / Project project their arcpy signatures onto honua-server's
# layer-aware processes (generalization.dissolve, conversion.feature-project)
# via ``honua_gp._process_tools.run_layer_process``: the input feature class /
# layer alias resolves to a numeric ``layerId``, the remaining arcpy params map
# onto the process's typed inputs, and the call submits + polls an async OGC
# API Processes job before returning an arcpy-style ``Result``.
#
# ``CalculateField`` / ``Copy`` / ``CopyFeatures`` are stubs: their honua-server
# targets (data-management.calculate-field / data-management.copy-features) are
# classified CanServe=false and are never projected as standalone OGC API
# processes -- they are only reachable as steps inside a honua-geoprocessing
# analysis plan, so a one-shot POST .../execution 404s on every server version.
# ``Delete`` likewise stays a stub: arcpy.Delete removes an entire dataset,
# while honua-server's data-management.delete-features only deletes features
# matching a filter *inside* a layer. The semantics differ, so faking any of
# these would silently do the wrong thing.


def CalculateField(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.CalculateField", args=args, kwargs=kwargs)


def Dissolve(*args: Any, **kwargs: Any) -> Result:
    return run_layer_process("management.Dissolve", *args, **kwargs)


def Copy(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.Copy", args=args, kwargs=kwargs)


# Alias for `arcpy.management.CopyFeatures`, which the scanner also calls "Copy".
CopyFeatures = Copy


def Delete(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.Delete", args=args, kwargs=kwargs)


def Project(*args: Any, **kwargs: Any) -> Result:
    return run_layer_process("management.Project", *args, **kwargs)


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
    "Result",
    "SelectLayerByAttribute",
    "SelectLayerByLocation",
    "Selection",
    "Sort",
]
