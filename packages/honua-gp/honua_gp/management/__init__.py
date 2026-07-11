"""``arcpy.management`` shim -- 20 functions.

Mapped functions split across backends:

* ``session``: MakeFeatureLayer, MakeTableView (in-process aliases).
* ``source``: SelectLayerByAttribute, GetCount (via the Source facade;
  GetCount is ``partial`` until the Source facade exposes a count-only
  helper), and Describe / ListFields (via
  ``honua_sdk.HonuaClient.feature_server(...).schema(layer_id)`` -- the
  FeatureServer layer-metadata endpoint, parsed into a typed
  ``honua_sdk.models.LayerSchema``).
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
* The schema-mutating entries (AddField, DeleteField, Rename) -- the real
  ``HonuaAdminClient`` does not yet expose per-layer schema mutation, so we
  surface the gap explicitly. (Describe / ListFields are schema *reads*,
  which the FeatureServer layer-metadata endpoint does support -- see above.)
* Append, Merge, CreateFeatureclass, CreateTable, Sort, SelectLayerByLocation
  -- no catalog op maps cleanly today.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .._audit import _shape_of, record_call
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
# Raster tools that live in the arcpy *management* toolbox in real arcpy
# ---------------------------------------------------------------------------
# ``ProjectRaster`` / ``Resample`` / ``Clip`` (raster) / ``Mosaic`` are Data
# Management tools in real arcpy (``arcpy.management.ProjectRaster`` etc.), but
# their honua-server targets are raster/surface processes, so the
# implementation + COMPAT manifest rows live under ``honua_gp.sa`` (single
# source of truth). These thin re-exports make ``arcpy.management.ProjectRaster``
# resolve for drop-in scripts, mirroring the ``CopyFeatures = Copy`` alias
# pattern. ``honua-gp assess`` canonicalizes the scanned ``management.*`` names
# onto the ``sa.*`` manifest rows via ``_cli._ALIAS_TO_CANONICAL``.
from ..sa import Clip as Clip  # noqa: E402 -- alias re-export after the management defs.
from ..sa import Mosaic as Mosaic  # noqa: E402
from ..sa import ProjectRaster as ProjectRaster  # noqa: E402
from ..sa import Resample as Resample  # noqa: E402

# arcpy also exposes the new-raster variant name; both map to raster.mosaic.
MosaicToNewRaster = Mosaic


# ---------------------------------------------------------------------------
# Schema-shaped value objects (kept for typed return shapes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldDescribe:
    """``arcpy.Field``-shaped lightweight record returned by ``ListFields`` /
    ``Describe(...).fields``.

    ``type`` is normalized from honua-server's raw ``esriFieldType*`` token
    (see ``honua_sdk.models.Field.type``) to arcpy's ``Field.type``
    vocabulary via ``_ARCPY_FIELD_TYPES`` -- e.g. ``esriFieldTypeString`` ->
    ``"String"``. ``raw`` keeps the untranslated server token for callers
    that need it. ``precision`` / ``scale`` are always ``None``: honua-server's
    FeatureServer field JSON does not carry them today (see the
    ``management.ListFields`` manifest note for the full list of gaps).
    """

    name: str
    type: str | None = None
    aliasName: str | None = None
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    nullable: bool | None = None
    domain: Mapping[str, Any] | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class SpatialReferenceInfo:
    """Minimal read-only stand-in for ``arcpy.SpatialReference``.

    honua-server's FeatureServer layer metadata advertises a spatial
    reference as an Esri ``{"wkid": ..., "latestWkid": ...}`` mapping (see
    ``honua_sdk.models.LayerSchema.srid`` / ``.spatial_reference``). Real
    ``arcpy.SpatialReference`` supports dozens of properties (``PCSCode``,
    ``GCSCode``, projection parameters, ``exportToString()``, ...); this
    wrapper only covers what a schema-introspection script actually reads:
    the resolved EPSG/WKID code (``factoryCode`` -- matches arcpy's property
    name) and a display ``name`` when the server happens to advertise one
    (most only advertise a WKID, so ``name`` is commonly ``None``).

    This is NOT accepted as an input to ``honua_gp`` process calls (e.g.
    ``management.Project``'s ``out_coor_system``); those still require a
    bare WKID int/numeric string per ``_process_tools``'s SRID coercion.
    """

    factoryCode: int | None = None
    name: str | None = None

    @property
    def wkid(self) -> int | None:
        """Alias for :attr:`factoryCode` -- some scripts read ``.wkid`` instead."""
        return self.factoryCode


@dataclass(frozen=True)
class DescribeResult:
    """arcpy.Describe-shaped lightweight record.

    Populated by ``management.Describe`` from honua-server's FeatureServer
    layer-metadata endpoint via a typed ``honua_sdk.models.LayerSchema``.
    See the ``management.Describe`` manifest entry in ``_compat.py`` for what
    is deliberately out of scope (raster Describe properties, the arcpy
    ``data_type`` filter argument, a verified ``catalogPath``, ...).
    """

    name: str
    dataType: str | None = None
    shapeType: str | None = None
    spatialReference: SpatialReferenceInfo | None = None
    extent: Any | None = None
    fields: tuple[FieldDescribe, ...] = ()
    OIDFieldName: str | None = None
    catalogPath: str | None = None
    raw: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Schema introspection (source-backed: FeatureServer layer metadata)
# ---------------------------------------------------------------------------
# Describe / ListFields fetch a typed LayerSchema via
# honua_sdk.HonuaClient.feature_server(service_id).schema(layer_id) -- the
# same FeatureServer layer-metadata endpoint honua_admin/honua_sdk already
# expose. The dataset argument resolves through the same alias / path-map /
# workspace machinery every other shim function uses (``_resolve.resolve`` +
# ``_resolve.descriptor_mapping``), so a MakeFeatureLayer alias, a
# ``honua://services/<svc>/<layer>`` URI, or a plain workspace-relative name
# all work identically.

# esriFieldType* (honua_sdk.models.Field.type, verbatim from the server) ->
# arcpy's Field.type vocabulary. Unknown / unmapped tokens pass through
# unchanged so a caller always sees a value even for a server type this
# table has not been taught yet.
_ARCPY_FIELD_TYPES: dict[str, str] = {
    "esriFieldTypeSmallInteger": "SmallInteger",
    "esriFieldTypeInteger": "Integer",
    "esriFieldTypeBigInteger": "BigInteger",
    "esriFieldTypeSingle": "Single",
    "esriFieldTypeDouble": "Double",
    "esriFieldTypeString": "String",
    "esriFieldTypeDate": "Date",
    "esriFieldTypeDateOnly": "DateOnly",
    "esriFieldTypeTimeOnly": "TimeOnly",
    "esriFieldTypeTimestampOffset": "TimestampOffset",
    "esriFieldTypeOID": "OID",
    "esriFieldTypeGeometry": "Geometry",
    "esriFieldTypeBlob": "Blob",
    "esriFieldTypeRaster": "Raster",
    "esriFieldTypeGUID": "GUID",
    "esriFieldTypeGlobalID": "GlobalID",
    "esriFieldTypeXML": "XML",
}


def _resolve_layer_locator(dataset: Any) -> tuple[str, int]:
    """Resolve an arcpy dataset argument to a honua-server ``(serviceId, layerId)``."""

    session = get_session()
    alias = session.get_layer(dataset) if isinstance(dataset, str) else None
    resolved = resolve(alias.name if alias is not None else dataset, session=session)
    descriptor = descriptor_mapping(resolved, session=session)
    locator = descriptor.get("locator") or {}
    service_id = locator.get("serviceId")
    layer_id = locator.get("layerId")
    if not isinstance(service_id, str) or not service_id:
        raise HonuaGpResolveError(
            str(dataset),
            hint=(
                "Describe/ListFields could not resolve a Honua serviceId for this "
                "dataset. Set arcpy.env.workspace to a honua://services/<service> "
                "URI, register the dataset via MakeFeatureLayer, or add a "
                "HONUA_GP_PATH_MAP entry."
            ),
        )
    if not isinstance(layer_id, int) or isinstance(layer_id, bool) or layer_id < 0:
        layer_id = 0
    return service_id, layer_id


def _fetch_layer_schema(dataset: Any) -> Any:
    session = get_session()
    service_id, layer_id = _resolve_layer_locator(dataset)
    client = session.client()
    if not hasattr(client, "feature_server"):
        raise HonuaGpConfigurationError(
            "Configured Honua client does not expose feature_server(); "
            "Describe/ListFields require a FeatureServer-capable client."
        )
    feature_server = client.feature_server(service_id)
    if not hasattr(feature_server, "schema"):
        raise HonuaGpConfigurationError(
            "Configured feature_server() client does not expose schema(layer_id)."
        )
    return feature_server.schema(layer_id)


def _field_describe_from_schema_field(entry: Any) -> FieldDescribe:
    raw_type = getattr(entry, "type", None)
    return FieldDescribe(
        name=getattr(entry, "name", "") or "",
        type=_ARCPY_FIELD_TYPES.get(raw_type, raw_type) if raw_type else None,
        aliasName=getattr(entry, "alias", None),
        length=getattr(entry, "length", None),
        nullable=getattr(entry, "nullable", None),
        domain=getattr(entry, "domain", None),
        raw={"esriFieldType": raw_type} if raw_type else None,
    )


def _spatial_reference_from_schema(schema: Any) -> SpatialReferenceInfo | None:
    srid = getattr(schema, "srid", None)
    raw = getattr(schema, "spatial_reference", None)
    if srid is None and not raw:
        return None
    name = None
    if isinstance(raw, Mapping):
        candidate = raw.get("name")
        name = candidate if isinstance(candidate, str) and candidate else None
    return SpatialReferenceInfo(factoryCode=srid, name=name)


def _describe_result_from_schema(dataset: Any, schema: Any) -> DescribeResult:
    fields = tuple(_field_describe_from_schema_field(f) for f in getattr(schema, "fields", ()))
    geometry_type = getattr(schema, "geometry_type", None)
    name = getattr(schema, "name", None) or str(dataset)
    return DescribeResult(
        name=name,
        dataType="FeatureClass" if geometry_type else "Table",
        shapeType=geometry_type,
        spatialReference=_spatial_reference_from_schema(schema),
        extent=getattr(schema, "extent", None),
        fields=fields,
        OIDFieldName=getattr(schema, "object_id_field", None),
        catalogPath=str(dataset),
        raw=dict(getattr(schema, "raw", None) or {}),
    )


def _matches_wild_card(name: str, pattern: str | None) -> bool:
    if not pattern:
        return True
    # arcpy's wild_card only documents ``*`` as a wildcard and matches
    # case-insensitively; normalize both sides to upper-case and use
    # fnmatchcase so behaviour does not depend on the host OS's path
    # case-folding rules (plain fnmatch.fnmatch varies by platform).
    return fnmatch.fnmatchcase(name.upper(), pattern.upper())


def _normalize_field_type_filter(field_type: Any) -> set[str] | None:
    if field_type is None:
        return None
    if isinstance(field_type, str):
        values: Iterable[Any] = field_type.split(";")
    else:
        values = field_type
    normalized = {str(value).strip().upper() for value in values if str(value).strip()}
    if not normalized or "ALL" in normalized:
        return None
    return normalized


def _filter_fields(
    fields: list[FieldDescribe],
    *,
    wild_card: str | None,
    field_type: Any,
) -> list[FieldDescribe]:
    type_filter = _normalize_field_type_filter(field_type)
    filtered: list[FieldDescribe] = []
    for entry in fields:
        if not _matches_wild_card(entry.name, wild_card):
            continue
        if type_filter is not None and (entry.type or "").upper() not in type_filter:
            continue
        filtered.append(entry)
    return filtered


def Describe(dataset: Any, data_type: Any = None) -> DescribeResult:
    """``arcpy.Describe(value, {datatype})`` -- feature-class/table schema
    introspection.

    Fetches the dataset's typed ``LayerSchema`` from honua-server's
    FeatureServer layer-metadata endpoint and projects it onto an
    arcpy-shaped ``DescribeResult``. See the ``management.Describe``
    manifest entry for the properties this does not populate.

    ``data_type`` is arcpy's optional second positional argument (a hint that
    disambiguates which child element to describe when a name is ambiguous).
    honua-server always describes the resolved dataset as-is, so this shim
    does NOT honor ``data_type`` as a filter. It is accepted (so a migrated
    ``Describe(path, "FeatureClass")`` call does not crash at the wrapper
    boundary) and recorded in the audit trail (so it is not silently
    swallowed), then ignored -- see the ``management.Describe`` manifest note.
    """

    qualified = "management.Describe"
    session = get_session()
    # ``data_type`` is accepted-but-not-honored: record it in the audit kwargs
    # so operators can see it was supplied (and ignored) rather than dropping
    # it silently. It never influences the resolved schema.
    audit_kwargs = {"data_type": data_type} if data_type is not None else {}
    with record_call(qualified, args=(dataset,), kwargs=audit_kwargs, writer=session.audit_writer()) as record:
        try:
            schema = _fetch_layer_schema(dataset)
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
        result = _describe_result_from_schema(dataset, schema)
        record["result_shape"] = _shape_of({"fields": len(result.fields), "shapeType": result.shapeType})
        return result


def ListFields(
    dataset: Any,
    wild_card: str | None = None,
    field_type: Any = None,
) -> list[FieldDescribe]:
    """``arcpy.ListFields(dataset, wild_card, field_type)``.

    ``wild_card`` supports the ``*`` glob character (case-insensitive).
    ``field_type`` accepts ``None``/``"All"`` (no filter), a single arcpy
    field-type string (e.g. ``"String"``), a semicolon-delimited string
    (``"String;Double"``), or a Python sequence of strings; matching is
    case-insensitive against the normalized ``FieldDescribe.type`` values.
    """

    qualified = "management.ListFields"
    session = get_session()
    with record_call(
        qualified, args=(dataset, wild_card, field_type), kwargs={}, writer=session.audit_writer()
    ) as record:
        try:
            schema = _fetch_layer_schema(dataset)
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
        fields = [_field_describe_from_schema_field(entry) for entry in getattr(schema, "fields", ())]
        fields = _filter_fields(fields, wild_card=wild_card, field_type=field_type)
        record["result_shape"] = _shape_of({"fields": len(fields)})
        return fields


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


def AddField(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.AddField", args=args, kwargs=kwargs)


def DeleteField(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.DeleteField", args=args, kwargs=kwargs)


def Rename(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("management.Rename", args=args, kwargs=kwargs)


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
    "Clip",
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
    "Mosaic",
    "MosaicToNewRaster",
    "Project",
    "ProjectRaster",
    "Rename",
    "Resample",
    "Result",
    "SelectLayerByAttribute",
    "SelectLayerByLocation",
    "Selection",
    "Sort",
    "SpatialReferenceInfo",
]
