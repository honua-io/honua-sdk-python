"""In-code compatibility manifest -- the single source of truth.

Every shim function reads its dispatch metadata from ``COMPAT``. The same
dictionary backs:

* ``scripts/render_compat_matrix.py`` (documents the compatibility surface).
* ``honua-arcpy assess`` (pivots scanner inventories against this table).
* ``_dispatch.py`` (chooses the backend per call).

Adding or moving a function therefore requires a single source edit; doc and
CLI output stay in lock-step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Backend = Literal["process", "source", "admin", "session", "not_implemented"]
Status = Literal["supported", "partial", "stub"]


@dataclass(frozen=True)
class FunctionEntry:
    """Compatibility manifest row for one shim function."""

    backend: Backend
    status: Status
    process_id: str | None = None
    notes: str = ""
    replacement_hint: str | None = None
    tracking: str | None = None
    param_map: dict[str, str] = field(default_factory=dict)
    arcpy_params: tuple[str, ...] = ()
    """Full ordered arcpy positional signature for a process-backed tool.

    ``param_map`` only carries the arcpy keyword -> honua-server process-input
    mappings (validated as a subset of the server catalog by
    ``test_process_backed_entries_match_honua_server_catalog``). Output and
    other non-input parameters (e.g. ``out_feature_class``) are *not* server
    inputs, so they cannot live in ``param_map`` without breaking that
    contract. ``arcpy_params`` therefore declares the complete positional
    order the projection adapter binds against, so a call like
    ``Buffer("roads", "out", "25 Meters")`` binds ``out`` to
    ``out_feature_class`` rather than to the distance slot.
    """

    output_params: tuple[str, ...] = ()
    source_params: tuple[str, ...] = ()
    """Arcpy parameter names that carry source/feature paths.

    Elements of these parameters are passed through
    :func:`honua_arcpy._resolve.resolve` (including ``HONUA_ARCPY_PATH_MAP``
    overrides). Sequence-valued source params (e.g. ``Intersect`` /
    ``Union`` ``in_features``) have each element resolved individually so
    path-map entries apply inside lists.
    """

    @property
    def is_supported(self) -> bool:
        return self.status in {"supported", "partial"}


COMPAT_REPO_DOC = "docs/honua-arcpy/compatibility-matrix.md"
"""Repo-relative path used to build anchor URLs for shim error messages.

Must point at a committed compatibility-matrix copy so the URL embedded in
``HonuaArcpyUnsupportedError.compat_anchor`` resolves when a customer pastes
it into the repo browser. The matching package-local copy under
``packages/honua-arcpy/docs/`` is byte-equal -- the rendered manifest is the
single source of truth -- but the top-level docs path is the public-facing
one, so we anchor against that copy.
"""


def anchor_for(qualified_name: str) -> str:
    """Return the in-repo anchor for a given ``arcpy`` qualified name."""

    fragment = qualified_name.replace(".", "").lower()
    return f"{COMPAT_REPO_DOC}#{fragment}"


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

# Notes on the manifest:
#
# * ``backend="process"`` -- payload is sent through
#   :class:`honua_sdk.protocols.OgcProcessesClient.execute`.
# * ``backend="source"`` -- routed through ``HonuaClient.source(...)`` and
#   either ``Source.query`` / ``Source.iter_features`` / ``Source.apply_edits``.
# * ``backend="admin"`` -- routed through ``HonuaAdminClient``.
# * ``backend="session"`` -- handled inside ``honua_arcpy`` itself
#   (``MakeFeatureLayer``, ``MakeTableView``).
# * ``backend="not_implemented"`` -- raises
#   :class:`~honua_arcpy._errors.HonuaArcpyUnsupportedError`. The replacement
#   hint is the recommended honua-sdk-python call.
#
# ``param_map`` maps the arcpy keyword to either:
#   * a process-input name (process backend), or
#   * a session/source attribute name (source/session/admin backend).
# ``output_params`` lists arcpy positional/keyword names that carry the
# output feature class -- the dispatcher caches the resolved source under
# those names so the next call can use the same workspace-relative path.


COMPAT: dict[str, FunctionEntry] = {
    # -----------------------------------------------------------------
    # analysis.* (15)
    # -----------------------------------------------------------------
    # NOTE on the analysis.* and management.* process-backed stubs below:
    # honua-server's ``geometry.*`` processes (``buffer``, ``clip``,
    # ``intersect``, ``union``, ``difference``, ``dissolve``) take raw WKB
    # geometries with an explicit ``srid``, not arcpy-style feature class
    # paths -- they buffer / clip / etc. a *single* geometry, not every
    # feature in a layer. honua-server's ``analytics.*`` and
    # ``data-management.*`` and ``conversion.feature-project`` processes
    # take ``layerId``-shaped references, not arcpy paths. Either family
    # requires a projection adapter (feature -> WKB; arcpy path -> layer
    # id) to be invoked end-to-end. Until that adapter exists, every
    # process-backed shim is a stub so the migration tool surfaces them
    # accurately instead of the previous Supported-but-broken claim.
    "analysis.Buffer": FunctionEntry(
        backend="process",
        status="supported",
        process_id="analytics.buffer-aggregate",
        notes=(
            "Projects arcpy.analysis.Buffer onto honua-server's layer-aware "
            "analytics.buffer-aggregate process: in_features -> layerId, the "
            "linear distance is split into distance+unit, and dissolve_option "
            "NONE/ALL maps to dissolve=false/true. Runs as an async OGC API "
            "Processes job (submit + poll). Deviation: arcpy's per-feature "
            "FULL/LIST buffer side table is not modelled; dissolve is "
            "all-or-nothing plus optional groupByFields."
        ),
        param_map={
            "in_features": "layerId",
            "buffer_distance_or_field": "distance",
            "dissolve_option": "dissolve",
            "dissolve_field": "groupByFields",
            "where_clause": "where",
        },
        arcpy_params=(
            "in_features",
            "out_feature_class",
            "buffer_distance_or_field",
            "line_side",
            "line_end_type",
            "dissolve_option",
            "dissolve_field",
            "method",
            "where_clause",
        ),
        output_params=("out_feature_class",),
        source_params=("in_features",),
    ),
    "analysis.Clip": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes=(
            "honua-server's geometry.clip operates on a single targetWkb against a "
            "clipEnvelopeWkb (single envelope geometry), not on feature classes."
        ),
        replacement_hint=(
            "Iterate target features via honua_sdk.Source.iter_features, clip each "
            "geometry against the envelope WKB, and write the result back via apply_edits."
        ),
        tracking="honua-server#feature-class-geometry-ops",
    ),
    "analysis.Intersect": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes=(
            "honua-server's geometry.intersect operates on two single geometries "
            "(targetWkb, intersectorWkb), not on feature classes."
        ),
        replacement_hint=(
            "Use the layer-aware analytics.spatial-join process via "
            "honua_sdk.protocols.OgcProcessesClient with the predicate=intersects "
            "branch once the projection adapter lands."
        ),
        tracking="honua-server#feature-class-geometry-ops",
    ),
    "analysis.Union": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes=(
            "honua-server's geometry.union takes an array of single WKB geometries "
            "(wkbs[], srid), not a list of feature classes."
        ),
        replacement_hint=(
            "Collect features via honua_sdk.Source.iter_features, encode each as "
            "WKB, then call honua_sdk.protocols.OgcProcessesClient.execute('geometry.union')."
        ),
        tracking="honua-server#feature-class-geometry-ops",
    ),
    "analysis.Erase": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes=(
            "honua-server's geometry.difference operates on a single targetWkb "
            "minus a single eraserWkb, not on feature classes."
        ),
        replacement_hint=(
            "Iterate target features and subtract each geometry against the eraser "
            "WKB via honua_sdk.protocols.OgcProcessesClient('geometry.difference')."
        ),
        tracking="honua-server#feature-class-geometry-ops",
    ),
    "analysis.SpatialJoin": FunctionEntry(
        backend="process",
        status="partial",
        process_id="analytics.spatial-join",
        notes=(
            "Projects arcpy.analysis.SpatialJoin onto honua-server's "
            "analytics.spatial-join: target_features -> layerId, join_features "
            "-> joinLayerId, and match_option -> predicate "
            "(INTERSECT/CONTAINS/WITHIN/WITHIN_A_DISTANCE+search_radius -> "
            "intersects/contains/within/dwithin). Runs as an async job. "
            "Partial: arcpy's join_operation (ONE_TO_ONE vs ONE_TO_MANY), "
            "join_type (KEEP_ALL/KEEP_COMMON), and field_mapping vocabulary are "
            "not modelled; the process emits the server's carry-field join shape."
        ),
        param_map={
            "target_features": "layerId",
            "join_features": "joinLayerId",
            "match_option": "predicate",
            "search_radius": "distance",
            "where_clause": "where",
        },
        arcpy_params=(
            "target_features",
            "join_features",
            "out_feature_class",
            "join_operation",
            "join_type",
            "field_mapping",
            "match_option",
            "search_radius",
            "distance_field_name",
            "where_clause",
        ),
        output_params=("out_feature_class",),
        source_params=("target_features", "join_features"),
    ),
    "analysis.NearestNeighbor": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Average nearest neighbor; requires honua-server analytics process.",
        replacement_hint="Use honua_sdk.Source.query(...) with sort_by_distance and compute the ratio client-side.",
        tracking="honua-server#nearest-neighbor",
    ),
    "analysis.Near": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Computes distance to nearest feature; requires honua-server analytics process.",
        replacement_hint="Use honua_sdk.Source.query(...) with bbox + spatial filter and minimize distance client-side.",
        tracking="honua-server#near",
    ),
    "analysis.TabulateIntersection": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Cross-tabulates area / length of intersection.",
        replacement_hint="Use analytics.spatial-join + summarize-within client-side post-processing.",
        tracking="honua-server#tabulate-intersection",
    ),
    "analysis.MultipleRingBuffer": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes=(
            "Multi-ring buffer emits one ring per distance band with the band "
            "distance carried as an attribute. honua-server's layer-aware "
            "analytics.buffer-aggregate (which analysis.Buffer now uses) buffers "
            "a single distance per call and does not emit the per-band ring "
            "attribute, so the multi-ring semantic is not a single-call mapping."
        ),
        replacement_hint=(
            "Call honua_arcpy.analysis.Buffer(...) once per distance band (it is "
            "now supported) and merge the per-band outputs client-side, tagging "
            "each with its ring distance."
        ),
        tracking="honua-server#multiple-ring-buffer",
    ),
    "analysis.PointDistance": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Point-to-point distance matrix; requires honua-server analytics process.",
        replacement_hint="Use honua_sdk.Source.query(...) and compute pairwise distance client-side.",
        tracking="honua-server#point-distance",
    ),
    "analysis.SummarizeWithin": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Aggregates features inside polygon bins.",
        replacement_hint="Use analytics.spatial-join + groupby aggregation on the OGC API Features client.",
        tracking="honua-server#summarize-within",
    ),
    "analysis.SymmetricalDifference": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes=(
            "Returns features that fall in exactly one input. Blocked on the "
            "same projection adapter as analysis.Union / analysis.Intersect "
            "(both stubs today), so composing those shims is not a workaround."
        ),
        replacement_hint=(
            "Iterate features client-side via honua_sdk.Source.iter_features "
            "and compose the difference via "
            "honua_sdk.protocols.OgcProcessesClient.execute('geometry.union') "
            "and 'geometry.intersect' directly with base64-WKB geometries."
        ),
        tracking="honua-server#symmetrical-difference",
    ),
    "analysis.Update": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Replaces input geometries with updater layer features.",
        replacement_hint="Use admin apply_manifest with a replace operation.",
        tracking="honua-server#update-analysis",
    ),
    "analysis.Identity": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes=(
            "Computes geometric identity between two layers. Blocked on the "
            "same projection adapter as analysis.Intersect (a stub today), so "
            "composing that shim is not a workaround."
        ),
        replacement_hint=(
            "Iterate target features via honua_sdk.Source.iter_features, call "
            "honua_sdk.protocols.OgcProcessesClient.execute('geometry.intersect') "
            "to compute the intersected geometry, and retain unmatched input "
            "rows client-side."
        ),
        tracking="honua-server#identity",
    ),
    # -----------------------------------------------------------------
    # management.* (20)
    # -----------------------------------------------------------------
    "management.MakeFeatureLayer": FunctionEntry(
        backend="session",
        status="supported",
        notes="Creates an in-process layer alias; deviation: alias is bound to a Honua source descriptor.",
        param_map={
            "in_features": "source",
            "out_layer": "layer_name",
            "where_clause": "where",
            "workspace": "workspace",
            "field_info": "field_info",
        },
    ),
    "management.SelectLayerByAttribute": FunctionEntry(
        backend="source",
        status="partial",
        notes=(
            "Where-clause selection; updates the in-process layer state. "
            "SWITCH_SELECTION is not supported because the shim cannot invert "
            "the prior OID selection set as a SQL where clause."
        ),
        param_map={
            "in_layer_or_view": "layer_name",
            "selection_type": "selection_type",
            "where_clause": "where",
            "invert_where_clause": "invert_where_clause",
        },
    ),
    "management.SelectLayerByLocation": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes=(
            "Spatial selection by relationship to another layer. honua-server "
            "has no native spatial-select process today, and the natural "
            "compose path (analysis.Buffer + analysis.Intersect, then "
            "SelectLayerByAttribute) is blocked because Buffer and Intersect "
            "are themselves stubs pending the projection adapter."
        ),
        replacement_hint=(
            "Query the candidate features via honua_sdk.Source.query(...) with "
            "a bbox prefilter, compute the spatial relationship client-side "
            "(or via honua_sdk.protocols.OgcProcessesClient geometry.* calls "
            "with base64-WKB inputs), then call "
            "management.SelectLayerByAttribute with a where clause that pins "
            "the resulting OID set (OBJECTID IN (...))."
        ),
        tracking="honua-server#spatial-filter",
    ),
    "management.CalculateField": FunctionEntry(
        backend="process",
        status="partial",
        process_id="data-management.calculate-field",
        notes=(
            "Projects arcpy.management.CalculateField onto honua-server's "
            "data-management.calculate-field: in_table -> layerId, field -> "
            "fieldName, expression -> expression, where_clause -> where. Runs as "
            "an async (destructive, approval-gated) job and mutates the input "
            "table in place. Partial: the expression must pass honua-server's "
            "FeatureServer.Edits allow-list, so arcpy PYTHON3 expressions with "
            "!field! token syntax or arbitrary Python are rejected server-side; "
            "pass a SQL/constant expression."
        ),
        param_map={
            "in_table": "layerId",
            "field": "fieldName",
            "expression": "expression",
            "where_clause": "where",
        },
        arcpy_params=(
            "in_table",
            "field",
            "expression",
            "expression_type",
            "code_block",
            "field_type",
            "enforce_domains",
            "where_clause",
        ),
        source_params=("in_table",),
    ),
    "management.AddField": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Schema-mutating field add; HonuaAdminClient has no add_field/apply_manifest path that mutates layer schemas today.",
        replacement_hint="File a honua-server ticket for layer-schema mutation; meanwhile run schema changes through your manifest publishing flow.",
        tracking="honua-server#layer-schema-mutate",
    ),
    "management.DeleteField": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Schema-mutating field delete; HonuaAdminClient has no delete_field/apply_manifest path that mutates layer schemas today.",
        replacement_hint="File a honua-server ticket for layer-schema mutation; meanwhile run schema changes through your manifest publishing flow.",
        tracking="honua-server#layer-schema-mutate",
    ),
    "management.Append": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Append rows from inputs into a target table.",
        replacement_hint="Use honua_sdk.Source.apply_edits with adds payload after schema-translation.",
        tracking="honua-server#append",
    ),
    "management.Merge": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Merges multiple feature classes into one.",
        replacement_hint="Iterate honua_sdk.Source.iter_features and write via apply_edits in chunks.",
        tracking="honua-server#merge",
    ),
    "management.Dissolve": FunctionEntry(
        backend="process",
        status="partial",
        process_id="generalization.dissolve",
        notes=(
            "Projects arcpy.management.Dissolve onto honua-server's layer-aware "
            "generalization.dissolve: in_features -> layerId and the "
            "dissolve_field list -> comma-separated groupByFields. Runs as an "
            "async job. Partial: arcpy's statistics_fields (per-group SUM/MEAN/"
            "etc.) and multi_part / unsplit_lines flags are not modelled; the "
            "process emits one feature per group via the server's outStatistics "
            "shape only when configured server-side."
        ),
        param_map={
            "in_features": "layerId",
            "dissolve_field": "groupByFields",
            "where_clause": "where",
        },
        arcpy_params=(
            "in_features",
            "out_feature_class",
            "dissolve_field",
            "statistics_fields",
            "multi_part",
            "unsplit_lines",
            "where_clause",
        ),
        output_params=("out_feature_class",),
        source_params=("in_features",),
    ),
    "management.Copy": FunctionEntry(
        backend="process",
        status="supported",
        process_id="data-management.copy-features",
        notes=(
            "Projects arcpy.management.Copy / CopyFeatures onto honua-server's "
            "data-management.copy-features: in_features -> sourceLayerId, "
            "out_feature_class -> targetLayerName, where_clause -> where. "
            "Non-destructive; runs as an async job and registers the target as "
            "a session alias so downstream GP calls can reference it. "
            "Deviation: arcpy.Copy copies a whole dataset including schema; the "
            "process copies (optionally filtered) features into a new layer."
        ),
        param_map={
            "in_features": "sourceLayerId",
            "where_clause": "where",
        },
        arcpy_params=(
            "in_features",
            "out_feature_class",
            "where_clause",
        ),
        output_params=("out_feature_class",),
        source_params=("in_features",),
    ),
    "management.Delete": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes=(
            "honua-server's data-management.delete-features removes features that "
            "match where/objectIds inside a layer; it does NOT drop the dataset "
            "itself. arcpy's Delete deletes the whole feature class -- semantically "
            "different from the server process."
        ),
        replacement_hint=(
            "To delete the entire resource, use honua_admin.HonuaAdminClient with a "
            "delete-resource manifest entry. To delete features inside a layer, call "
            "honua_sdk.protocols.OgcProcessesClient.execute('data-management.delete-features')."
        ),
        tracking="honua-server#arcpy-delete-resource-adapter",
    ),
    "management.Rename": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Resource rename; HonuaAdminClient exposes apply_manifest but no rename_resource translation today.",
        replacement_hint="Republish the resource under the new name via honua_admin.HonuaAdminClient.apply_manifest and delete the old entry.",
        tracking="honua-server#rename-resource",
    ),
    "management.CreateFeatureclass": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Creates a new feature class; schema translation is the hard part.",
        replacement_hint="Use honua_admin.HonuaAdminClient.apply_manifest with a create-resource entry.",
        tracking="honua-server#create-feature-class",
    ),
    "management.CreateTable": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Creates a new table; schema translation is the hard part.",
        replacement_hint="Use honua_admin.HonuaAdminClient.apply_manifest with a create-resource entry.",
        tracking="honua-server#create-table",
    ),
    "management.Project": FunctionEntry(
        backend="process",
        status="supported",
        process_id="conversion.feature-project",
        notes=(
            "Projects arcpy.management.Project onto honua-server's "
            "conversion.feature-project: in_dataset -> layerId and the "
            "out_coor_system EPSG/WKID code -> targetSrid. Runs as an async job "
            "and registers the named out_dataset as a session alias. Deviation: "
            "out_coor_system must be an EPSG/WKID code (int or numeric string); "
            "arcpy.SpatialReference objects and named transformations are not "
            "resolvable by the shim."
        ),
        param_map={
            "in_dataset": "layerId",
            "out_coor_system": "targetSrid",
        },
        arcpy_params=(
            "in_dataset",
            "out_dataset",
            "out_coor_system",
            "transform_method",
            "in_coor_system",
            "preserve_shape",
            "max_deviation",
            "vertical",
        ),
        output_params=("out_dataset",),
        source_params=("in_dataset",),
    ),
    "management.Sort": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Sorts feature class rows by one or more fields.",
        replacement_hint="Use honua_sdk.Source.query(order_by=...) and write with apply_edits.",
        tracking="honua-server#sort",
    ),
    "management.MakeTableView": FunctionEntry(
        backend="session",
        status="supported",
        notes="Creates an in-process table-view alias; mirrors MakeFeatureLayer.",
        param_map={
            "in_table": "source",
            "out_view": "layer_name",
            "where_clause": "where",
            "workspace": "workspace",
            "field_info": "field_info",
        },
    ),
    "management.GetCount": FunctionEntry(
        backend="source",
        status="partial",
        notes="Returns a row count via Source.query; currently materializes the full result set because Source has no count-only helper yet.",
        param_map={"in_rows": "layer_name"},
    ),
    "management.ListFields": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Lists layer fields; HonuaAdminClient exposes discover_tables (per connection) but no per-layer schema reader today.",
        replacement_hint="Use honua_admin.HonuaAdminClient.discover_tables for the parent connection and project the field list locally.",
        tracking="honua-server#layer-schema-read",
    ),
    "management.Describe": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Inspects a dataset's schema; HonuaAdminClient does not expose a per-layer schema reader today.",
        replacement_hint="Use honua_admin.HonuaAdminClient.discover_tables for the parent connection or honua_sdk.HonuaClient.feature_server(...).layer_metadata(layer_id).",
        tracking="honua-server#layer-schema-read",
    ),
    # -----------------------------------------------------------------
    # da.* (10)
    # -----------------------------------------------------------------
    "da.SearchCursor": FunctionEntry(
        backend="source",
        status="partial",
        notes=(
            "Read-only iteration over Source.iter_features; forwards where/out_fields/order_by/out_sr where possible "
            "and rejects unsupported sql_clause variants or explode_to_points."
        ),
        param_map={
            "in_table": "layer_name",
            "field_names": "fields",
            "where_clause": "where",
            "spatial_reference": "spatial_reference",
            "explode_to_points": "explode_to_points",
            "sql_clause": "sql_clause",
        },
    ),
    "da.UpdateCursor": FunctionEntry(
        backend="source",
        status="supported",
        notes="Buffered updates; flush on __exit__ or explicit cursor.flush(). Deviates from arcpy's per-row commit.",
        param_map={
            "in_table": "layer_name",
            "field_names": "fields",
            "where_clause": "where",
        },
    ),
    "da.InsertCursor": FunctionEntry(
        backend="source",
        status="supported",
        notes="Buffered inserts; flush on __exit__. Deviates from arcpy's per-row commit.",
        param_map={
            "in_table": "layer_name",
            "field_names": "fields",
        },
    ),
    "da.Editor": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Workspace-level edit session context manager.",
        replacement_hint="Wrap honua_sdk.Source.apply_edits calls in a try/except; per-workspace transactions are not yet exposed.",
        tracking="honua-server#workspace-editor",
    ),
    "da.Walk": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Walks a workspace directory tree for datasets.",
        replacement_hint="Use honua_admin.HonuaAdminClient.list_services / list_metadata_resources.",
        tracking="honua-server#workspace-walk",
    ),
    "da.TableToNumPyArray": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Materializes table rows as a NumPy structured array.",
        replacement_hint="Use honua_sdk.Source.query(...).features and convert with numpy.array client-side.",
        tracking="honua-server#numpy-bridge",
    ),
    "da.FeatureClassToNumPyArray": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Materializes feature class rows as a NumPy structured array.",
        replacement_hint="Use honua_sdk.Source.query(...).features and convert with numpy.array client-side.",
        tracking="honua-server#numpy-bridge",
    ),
    "da.NumPyArrayToTable": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Writes a NumPy structured array into a table.",
        replacement_hint="Use honua_sdk.Source.apply_edits with rows derived from the structured array.",
        tracking="honua-server#numpy-bridge",
    ),
    "da.NumPyArrayToFeatureClass": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Writes a NumPy structured array into a feature class.",
        replacement_hint="Use honua_sdk.Source.apply_edits with feature rows derived from the structured array.",
        tracking="honua-server#numpy-bridge",
    ),
    "da.ExtendTable": FunctionEntry(
        backend="not_implemented",
        status="stub",
        notes="Joins a NumPy array onto an existing table.",
        replacement_hint="Use admin apply_manifest with a field-add + apply_edits update sequence.",
        tracking="honua-server#extend-table",
    ),
}


SUPPORTED_FUNCTIONS = tuple(name for name, entry in COMPAT.items() if entry.is_supported)
STUBBED_FUNCTIONS = tuple(name for name, entry in COMPAT.items() if entry.status == "stub")


def entry_for(qualified_name: str) -> FunctionEntry | None:
    """Return the manifest entry for ``family.Function`` (case-sensitive)."""

    return COMPAT.get(qualified_name)


__all__ = [
    "COMPAT",
    "COMPAT_REPO_DOC",
    "STUBBED_FUNCTIONS",
    "SUPPORTED_FUNCTIONS",
    "Backend",
    "FunctionEntry",
    "Status",
    "anchor_for",
    "entry_for",
]
