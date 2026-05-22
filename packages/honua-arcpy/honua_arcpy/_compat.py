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


COMPAT_REPO_DOC = "docs/compatibility-matrix.md"
"""Repo-relative path used to build anchor URLs for shim error messages."""


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
    "analysis.Buffer": FunctionEntry(
        backend="process",
        status="supported",
        process_id="geometry.buffer",
        notes="Vector buffer; dispatches to honua-server geometry.buffer.",
        param_map={
            "in_features": "input_features",
            "out_feature_class": "result",
            "buffer_distance_or_field": "distance",
            "line_side": "line_side",
            "line_end_type": "line_end_type",
            "dissolve_option": "dissolve_option",
            "dissolve_field": "dissolve_fields",
            "method": "method",
        },
        output_params=("out_feature_class",),
        source_params=("in_features",),
    ),
    "analysis.Clip": FunctionEntry(
        backend="process",
        status="supported",
        process_id="geometry.clip",
        notes="Vector clip against another feature class.",
        param_map={
            "in_features": "input_features",
            "clip_features": "clip_features",
            "out_feature_class": "result",
            "cluster_tolerance": "cluster_tolerance",
        },
        output_params=("out_feature_class",),
        source_params=("in_features", "clip_features"),
    ),
    "analysis.Intersect": FunctionEntry(
        backend="process",
        status="supported",
        process_id="geometry.intersect",
        notes="Pairwise vector intersect; respects join_attributes.",
        param_map={
            "in_features": "input_features",
            "out_feature_class": "result",
            "join_attributes": "join_attributes",
            "cluster_tolerance": "cluster_tolerance",
            "output_type": "output_type",
        },
        output_params=("out_feature_class",),
        source_params=("in_features",),
    ),
    "analysis.Union": FunctionEntry(
        backend="process",
        status="supported",
        process_id="geometry.union",
        notes="Vector union; gaps allowance forwarded as a process parameter.",
        param_map={
            "in_features": "input_features",
            "out_feature_class": "result",
            "join_attributes": "join_attributes",
            "cluster_tolerance": "cluster_tolerance",
            "gaps": "gaps",
        },
        output_params=("out_feature_class",),
        source_params=("in_features",),
    ),
    "analysis.Erase": FunctionEntry(
        backend="process",
        status="supported",
        process_id="geometry.difference",
        notes="Vector erase (arcpy's name for geometric difference).",
        param_map={
            "in_features": "input_features",
            "erase_features": "erase_features",
            "out_feature_class": "result",
            "cluster_tolerance": "cluster_tolerance",
        },
        output_params=("out_feature_class",),
        source_params=("in_features", "erase_features"),
    ),
    "analysis.SpatialJoin": FunctionEntry(
        backend="process",
        status="supported",
        process_id="analytics.spatial-join",
        notes="Spatial join with optional match-option and search radius.",
        param_map={
            "target_features": "target_features",
            "join_features": "join_features",
            "out_feature_class": "result",
            "join_operation": "join_operation",
            "join_type": "join_type",
            "field_mapping": "field_mapping",
            "match_option": "match_option",
            "search_radius": "search_radius",
            "distance_field_name": "distance_field_name",
            "match_fields": "match_fields",
        },
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
        notes="Multi-ring buffer wraps geometry.buffer across distance bands.",
        replacement_hint="Loop honua_arcpy.analysis.Buffer over each distance band and merge.",
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
        notes="Returns features that fall in exactly one input.",
        replacement_hint="Compose Union minus Intersect; both processes are supported.",
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
        notes="Computes geometric identity between two layers.",
        replacement_hint="Compose Intersect + retain unmatched input rows client-side.",
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
        status="supported",
        notes="Where-clause selection; updates the in-process layer state.",
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
        notes="Spatial selection composed of buffer + intersect when no native process exists.",
        replacement_hint="Use honua_arcpy.analysis.Buffer + analysis.Intersect, then SelectLayerByAttribute.",
        tracking="honua-server#spatial-filter",
    ),
    "management.CalculateField": FunctionEntry(
        backend="process",
        status="supported",
        process_id="data-management.calculate-field",
        notes="Python expression sent to server-side calculator.",
        param_map={
            "in_table": "input_features",
            "field": "field",
            "expression": "expression",
            "expression_type": "expression_type",
            "code_block": "code_block",
            "field_type": "field_type",
        },
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
        status="supported",
        process_id="geometry.dissolve",
        notes="Geometry dissolve on optional field list.",
        param_map={
            "in_features": "input_features",
            "out_feature_class": "result",
            "dissolve_field": "dissolve_fields",
            "statistics_fields": "statistics_fields",
            "multi_part": "multi_part",
            "unsplit_lines": "unsplit_lines",
        },
        output_params=("out_feature_class",),
        source_params=("in_features",),
    ),
    "management.Copy": FunctionEntry(
        backend="process",
        status="supported",
        process_id="data-management.copy-features",
        notes="Copies features into a new resource via copy-features process.",
        param_map={
            "in_data": "input_features",
            "out_data": "result",
            "data_type": "data_type",
        },
        output_params=("out_data",),
        source_params=("in_data",),
    ),
    "management.Delete": FunctionEntry(
        backend="process",
        status="supported",
        process_id="data-management.delete-features",
        notes="Deletes a feature class or table.",
        param_map={
            "in_data": "input_features",
            "data_type": "data_type",
        },
        source_params=("in_data",),
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
        notes="Reprojects a feature class via conversion.feature-project.",
        param_map={
            "in_dataset": "input_features",
            "out_dataset": "result",
            "out_coor_system": "out_crs",
            "transform_method": "transform_method",
            "in_coor_system": "in_crs",
            "preserve_shape": "preserve_shape",
            "max_deviation": "max_deviation",
            "vertical": "vertical",
        },
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
        status="supported",
        notes="Read-only iteration over Source.iter_features; context-manager safe.",
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
    "Backend",
    "Status",
    "FunctionEntry",
    "COMPAT",
    "COMPAT_REPO_DOC",
    "SUPPORTED_FUNCTIONS",
    "STUBBED_FUNCTIONS",
    "anchor_for",
    "entry_for",
]
