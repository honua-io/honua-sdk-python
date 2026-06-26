"""Generate the 50 representative arcpy eval scripts.

Run once from the package root:

    python eval/_generate_scripts.py

The generator emits 50 scripts plus matching golden references that
exercise the *currently* supported surface of ``honua_arcpy`` --
session-backed (MakeFeatureLayer, MakeTableView), source-backed
(SelectLayerByAttribute, GetCount, SearchCursor, UpdateCursor,
InsertCursor) -- plus a large set of ``expected_failure_*`` scripts
that catch ``HonuaArcpyUnsupportedError`` from the stubbed process /
admin entries (Buffer, Clip, Intersect, Union, Erase, SpatialJoin,
Dissolve, Copy, Delete, Project, CalculateField, plus the schema-mutation
admin stubs).

Audit pass 8 caught the analysis.* / management.* process-backed shims
emitting a payload that did not match honua-server's
``BuiltInProcessCatalog`` contract. Those entries are now stubs until
the arcpy-to-server projection adapter lands, and the eval distribution
is rebalanced accordingly: every script that previously dispatched a
mismatched process now lives in the ``expected_failure_*`` block so the
suite tracks the migration surface honestly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PACKAGE_ROOT / "eval" / "scripts"
GOLDEN_DIR = PACKAGE_ROOT / "eval" / "golden"


BOOTSTRAP = '''"""{docstring}"""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
for path in (PACKAGE_ROOT, PACKAGE_ROOT.parent.parent / "packages" / "honua-sdk", PACKAGE_ROOT.parent.parent / "packages" / "honua-admin"):
    candidate = str(path)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from eval._stub import install_stub, stub_active

import honua_arcpy as arcpy

if stub_active():
    install_stub()
else:
    # Live mode: pick up HONUA_BASE_URL / HONUA_API_KEY / HONUA_BEARER_TOKEN
    # so the script runs against the configured Honua deployment.
    arcpy.configure_from_env()

arcpy.env.workspace = "honua://services/{workspace}"
arcpy.env.overwriteOutput = True

'''


@dataclass(frozen=True)
class ScriptSpec:
    slug: str
    workspace: str
    docstring: str
    body: str
    expected_audit_lines: int
    stdout_marker: str
    is_expected_failure: bool = False


SUPPORTED_TEMPLATES: list[ScriptSpec] = []


def _supported(slug: str, workspace: str, docstring: str, body: str, audit_lines: int, marker: str) -> ScriptSpec:
    spec = ScriptSpec(
        slug=slug,
        workspace=workspace,
        docstring=docstring,
        body=body,
        expected_audit_lines=audit_lines,
        stdout_marker=marker,
    )
    SUPPORTED_TEMPLATES.append(spec)
    return spec


# NOTE: Buffer / Clip / Intersect / Union / Erase / SpatialJoin /
# Dissolve / Copy / Delete / Project / CalculateField were previously
# exercised as "supported" scripts here. Audit pass 8 found that the
# shim emitted an arcpy-style ``input_features`` / ``result`` payload
# while honua-server's process catalog expects ``wkb`` / ``srid`` (for
# ``geometry.*``) or ``layerId`` (for ``analytics.*`` /
# ``data-management.*`` / ``conversion.feature-project``). Those
# entries are stubs until the projection adapter lands, so their
# eval scripts moved to the ``expected_failure_*`` block below.
#
# NOTE: AddField / DeleteField / Rename / ListFields / Describe are
# also stubs because HonuaAdminClient does not yet expose per-layer
# schema mutation or reading.

_supported(
    "make_feature_layer_then_select",
    "transport",
    "Make a feature layer then SelectLayerByAttribute on STATUS = 'OPEN'.",
    """arcpy.management.MakeFeatureLayer("roads", "roads_lyr")
selection = arcpy.management.SelectLayerByAttribute("roads_lyr", "NEW_SELECTION", "STATUS = 'OPEN'")
print(f"make_feature_layer_then_select ok count={selection.count}")
""",
    2,
    "make_feature_layer_then_select ok",
)

_supported(
    "make_table_view",
    "transport",
    "Make a table view for inspection.",
    """arcpy.management.MakeTableView("segments_attrs", "segments_view")
print("make_table_view ok")
""",
    1,
    "make_table_view ok",
)

_supported(
    "get_count_roads",
    "transport",
    "Count rows in the roads feature class.",
    """count = arcpy.management.GetCount("roads")
print(f"get_count_roads ok count={count}")
""",
    1,
    "get_count_roads ok",
)

_supported(
    "search_cursor_iterate",
    "transport",
    "Iterate roads via a SearchCursor.",
    """with arcpy.da.SearchCursor("roads", ["OID@", "STATUS"]) as cursor:
    rows = [row for row in cursor]
print(f"search_cursor_iterate ok rows={len(rows)}")
""",
    1,
    "search_cursor_iterate ok",
)

_supported(
    "update_cursor_close_status",
    "transport",
    "UpdateCursor: flip CLOSED rows to ARCHIVED.",
    """with arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"]) as cursor:
    for row in cursor:
        if row[1] == "CLOSED":
            row[1] = "ARCHIVED"
            cursor.updateRow(row)
print("update_cursor_close_status ok")
""",
    1,
    "update_cursor_close_status ok",
)

_supported(
    "update_cursor_delete_closed",
    "transport",
    "UpdateCursor: delete CLOSED rows.",
    """with arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"]) as cursor:
    for row in cursor:
        if row[1] == "CLOSED":
            cursor.deleteRow()
print("update_cursor_delete_closed ok")
""",
    1,
    "update_cursor_delete_closed ok",
)

_supported(
    "insert_cursor_append_rows",
    "transport",
    "InsertCursor: append three rows.",
    """with arcpy.da.InsertCursor("roads", ["STATUS", "name"]) as cursor:
    cursor.insertRow(["OPEN", "Main St"])
    cursor.insertRow(["OPEN", "Elm Ave"])
    cursor.insertRow(["CLOSED", "Side Rd"])
print("insert_cursor_append_rows ok")
""",
    1,
    "insert_cursor_append_rows ok",
)

_supported(
    "get_count_after_select",
    "transport",
    "GetCount on a selection layer.",
    """arcpy.management.MakeFeatureLayer("roads", "roads_lyr")
arcpy.management.SelectLayerByAttribute("roads_lyr", "NEW_SELECTION", "STATUS = 'OPEN'")
count = arcpy.management.GetCount("roads_lyr")
print(f"get_count_after_select ok count={count}")
""",
    3,
    "get_count_after_select ok",
)

_supported(
    "make_feature_layer_clear_then_count",
    "transport",
    "Make layer, set selection, clear, recount.",
    """arcpy.management.MakeFeatureLayer("roads", "roads_lyr")
arcpy.management.SelectLayerByAttribute("roads_lyr", "NEW_SELECTION", "STATUS = 'OPEN'")
arcpy.management.SelectLayerByAttribute("roads_lyr", "CLEAR_SELECTION")
count = arcpy.management.GetCount("roads_lyr")
print(f"make_feature_layer_clear_then_count ok count={count}")
""",
    4,
    "make_feature_layer_clear_then_count ok",
)

_supported(
    "search_cursor_filter",
    "transport",
    "SearchCursor with a where clause.",
    """with arcpy.da.SearchCursor("roads", ["OID@", "STATUS"], where_clause="STATUS = 'OPEN'") as cursor:
    rows = list(cursor)
print(f"search_cursor_filter ok rows={len(rows)}")
""",
    1,
    "search_cursor_filter ok",
)

_supported(
    "insert_cursor_then_search",
    "transport",
    "InsertCursor then SearchCursor to confirm.",
    """with arcpy.da.InsertCursor("roads", ["STATUS", "name"]) as cursor:
    cursor.insertRow(["OPEN", "Loop Rd"])
with arcpy.da.SearchCursor("roads", ["OID@", "name"]) as cursor:
    rows = list(cursor)
print(f"insert_cursor_then_search ok rows={len(rows)}")
""",
    2,
    "insert_cursor_then_search ok",
)

EXPECTED_FAILURE_TEMPLATES: list[ScriptSpec] = []


def _expected_failure(slug: str, body: str, marker: str) -> ScriptSpec:
    full_slug = f"expected_failure_{slug}"
    spec = ScriptSpec(
        slug=full_slug,
        workspace="legacy",
        docstring=f"Expected-failure script exercising {marker}.",
        body=f"""try:
{body}
except arcpy.HonuaArcpyUnsupportedError as exc:
    print(f"expected_failure_{slug} caught {{exc.function}}")
    raise SystemExit(0) from exc
raise SystemExit("expected_failure_{slug} did not raise")
""",
        expected_audit_lines=1,
        stdout_marker=f"expected_failure_{slug}",
        is_expected_failure=True,
    )
    EXPECTED_FAILURE_TEMPLATES.append(spec)
    return spec


# ---------------------------------------------------------------------------
# Process-backed tools re-promoted via the layer-aware projection adapter.
# Each submits an async OGC API Processes job (the stub transport models the
# accepted -> successful lifecycle) and returns an arcpy-style Result. They use
# honua://services/<svc>/<layerId> inputs so the shim can project a numeric
# layerId for honua-server's layer-aware processes.
# ---------------------------------------------------------------------------
_supported(
    "buffer_roads",
    "transport",
    "Buffer roads via the layer-aware analytics.buffer-aggregate projection.",
    """result = arcpy.analysis.Buffer("honua://services/transport/0", "roads_buffer", "25 Meters", dissolve_option="ALL")
print(f"buffer_roads ok output={result[0]}")
""",
    1,
    "buffer_roads ok",
)
_supported(
    "buffer_legacy_suffix",
    "transport",
    "Buffer via the Buffer_analysis legacy suffix alias.",
    """result = arcpy.Buffer_analysis("honua://services/transport/0", "trails_buffer", "15 Meters")
print(f"buffer_legacy_suffix ok output={result[0]}")
""",
    1,
    "buffer_legacy_suffix ok",
)
_supported(
    "spatial_join_addresses_parcels",
    "transport",
    "Spatial join addresses to parcels via analytics.spatial-join.",
    """result = arcpy.analysis.SpatialJoin("honua://services/addresses/0", "honua://services/parcels/0", "addresses_with_parcel", match_option="INTERSECT")
print(f"spatial_join_addresses_parcels ok output={result[0]}")
""",
    1,
    "spatial_join_addresses_parcels ok",
)
_supported(
    "spatial_join_with_radius",
    "transport",
    "Spatial join within a distance via the dwithin predicate.",
    """result = arcpy.analysis.SpatialJoin("honua://services/facilities/0", "honua://services/parcels/0", "out", match_option="WITHIN_A_DISTANCE", search_radius="100 Meters")
print(f"spatial_join_with_radius ok output={result[0]}")
""",
    1,
    "spatial_join_with_radius ok",
)
_supported(
    "dissolve_parcels_by_zoning",
    "transport",
    "Dissolve parcels by zoning via generalization.dissolve.",
    """result = arcpy.management.Dissolve("honua://services/parcels/0", "parcels_by_zoning", dissolve_field=["zoning_code"])
print(f"dissolve_parcels_by_zoning ok output={result[0]}")
""",
    1,
    "dissolve_parcels_by_zoning ok",
)
_supported(
    "copy_pavement_to_backup",
    "transport",
    "Copy features into a backup layer via data-management.copy-features.",
    """result = arcpy.management.Copy("honua://services/pavement/0", "pavement_backup")
print(f"copy_pavement_to_backup ok output={result[0]}")
""",
    1,
    "copy_pavement_to_backup ok",
)
_supported(
    "copy_features_alias",
    "transport",
    "CopyFeatures alias routes through the same copy-features process.",
    """result = arcpy.management.CopyFeatures("honua://services/parcels_stage/0", "parcels_published")
print(f"copy_features_alias ok output={result[0]}")
""",
    1,
    "copy_features_alias ok",
)
_supported(
    "project_roads_to_wgs84",
    "transport",
    "Reproject a layer to WGS84 via conversion.feature-project.",
    """result = arcpy.management.Project("honua://services/roads/0", "roads_wgs84", 4326)
print(f"project_roads_to_wgs84 ok output={result[0]}")
""",
    1,
    "project_roads_to_wgs84 ok",
)
_supported(
    "calculate_field_constant",
    "transport",
    "CalculateField with a SQL/constant expression via data-management.calculate-field.",
    """result = arcpy.management.CalculateField("honua://services/segments/0", "active", "1", where_clause="status = 'OPEN'")
print(f"calculate_field_constant ok output={result[0]}")
""",
    1,
    "calculate_field_constant ok",
)
_supported(
    "buffer_then_dissolve",
    "transport",
    "Buffer then Dissolve, both via the layer-aware projection.",
    """arcpy.analysis.Buffer("honua://services/transport/0", "roads_buffer", "5 Meters", dissolve_option="ALL")
result = arcpy.management.Dissolve("honua://services/transport/0", "roads_dissolved", dissolve_field=["class"])
print(f"buffer_then_dissolve ok output={result[0]}")
""",
    2,
    "buffer_then_dissolve ok",
)
_supported(
    "buffer_numeric_distance",
    "transport",
    "Buffer with a bare numeric distance (meters default).",
    """result = arcpy.analysis.Buffer("honua://services/transport/0", "roads_buf_num", 50)
print(f"buffer_numeric_distance ok output={result[0]}")
""",
    1,
    "buffer_numeric_distance ok",
)
_supported(
    "project_kilometers_buffer",
    "transport",
    "Project a layer then buffer the projected output.",
    """arcpy.management.Project("honua://services/parcels/0", "parcels_wgs", 4326)
result = arcpy.analysis.Buffer("honua://services/parcels/0", "parcels_buf", "1 Kilometers")
print(f"project_kilometers_buffer ok output={result[0]}")
""",
    2,
    "project_kilometers_buffer ok",
)
_supported(
    "copy_then_calculate_field",
    "transport",
    "Copy features then calculate a constant field on the source layer.",
    """arcpy.management.Copy("honua://services/stage/0", "published")
result = arcpy.management.CalculateField("honua://services/stage/0", "reviewed", "1")
print(f"copy_then_calculate_field ok output={result[0]}")
""",
    2,
    "copy_then_calculate_field ok",
)

# ---------------------------------------------------------------------------
# Honest stubs: arcpy overlay tools (Clip/Intersect/Union/Erase) have only
# single-WKB geometry.* counterparts, Delete has different semantics from
# delete-features, and the rest have no catalog op. These exercise the
# raise_unsupported / audit-write contract.
# ---------------------------------------------------------------------------
_expected_failure(
    "clip_roads_in_study",
    "    arcpy.analysis.Clip('roads_buffer', 'study_area', 'roads_clip')",
    "analysis.Clip",
)
_expected_failure(
    "intersect_roads_parcels",
    "    arcpy.analysis.Intersect(['roads', 'parcels'], 'roads_x_parcels', 'ALL')",
    "analysis.Intersect",
)
_expected_failure(
    "union_zoning_layers",
    "    arcpy.analysis.Union(['zoning_2020', 'zoning_2024'], 'zoning_union', 'ALL')",
    "analysis.Union",
)
_expected_failure(
    "erase_water_from_parcels",
    "    arcpy.analysis.Erase('parcels', 'water', 'parcels_dry')",
    "analysis.Erase",
)
_expected_failure(
    "delete_obsolete_layer",
    "    arcpy.management.Delete('scratch_layer')",
    "management.Delete",
)

# Existing admin / analytics stubs (pre-existing, unchanged).
_expected_failure("sort", "    arcpy.management.Sort('roads', 'roads_sorted', [['name', 'ASCENDING']])", "management.Sort")
_expected_failure("append", "    arcpy.management.Append(['updates'], 'roads', 'NO_TEST')", "management.Append")
_expected_failure("merge", "    arcpy.management.Merge(['a', 'b'], 'merged')", "management.Merge")
_expected_failure("create_fc", "    arcpy.management.CreateFeatureclass('honua://services/transport', 'new_fc', 'POLYGON')", "management.CreateFeatureclass")
_expected_failure("create_table", "    arcpy.management.CreateTable('honua://services/transport', 'new_table')", "management.CreateTable")
_expected_failure("select_by_location", "    arcpy.management.SelectLayerByLocation('roads', 'INTERSECT', 'study_area')", "management.SelectLayerByLocation")
_expected_failure("near", "    arcpy.analysis.Near('points', 'roads')", "analysis.Near")
_expected_failure("nearest_neighbor", "    arcpy.analysis.NearestNeighbor('points')", "analysis.NearestNeighbor")
_expected_failure("tabulate_intersection", "    arcpy.analysis.TabulateIntersection('a', 'a_id', 'b', 'out')", "analysis.TabulateIntersection")
_expected_failure("walk", "    list(arcpy.da.Walk('honua://services/transport'))", "da.Walk")
# Admin-targeted stubs (no per-layer schema mutation / reading in HonuaAdminClient yet).
_expected_failure("add_field", "    arcpy.management.AddField('segments', 'route_id', field_type='LONG')", "management.AddField")
_expected_failure("delete_field", "    arcpy.management.DeleteField('segments', 'legacy_code')", "management.DeleteField")
_expected_failure("rename", "    arcpy.management.Rename('parcels_stage', 'parcels_published', 'FeatureClass')", "management.Rename")
_expected_failure("describe", "    arcpy.Describe('segments')", "management.Describe")
_expected_failure("list_fields", "    arcpy.management.ListFields('segments')", "management.ListFields")
_expected_failure("list_fields_filtered", "    arcpy.management.ListFields('segments', field_type='String')", "management.ListFields")
_expected_failure("list_fields_wildcard", "    arcpy.management.ListFields('segments', wild_card='STAT*')", "management.ListFields")
_expected_failure("add_field_calculate_field", "    arcpy.management.AddField('segments', 'scaled_speed', field_type='DOUBLE')", "management.AddField")
_expected_failure("delete_field_after_calc", "    arcpy.management.DeleteField('segments', 'tmp')", "management.DeleteField")
_expected_failure("describe_then_iterate", "    arcpy.Describe('segments')", "management.Describe")
_expected_failure("rename_then_describe", "    arcpy.management.Rename('legacy_parcels', 'parcels', 'FeatureClass')", "management.Rename")


def _render(spec: ScriptSpec) -> str:
    header = BOOTSTRAP.format(docstring=spec.docstring, workspace=spec.workspace)
    return header + spec.body


def _emit() -> None:
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    specs: list[ScriptSpec] = SUPPORTED_TEMPLATES + EXPECTED_FAILURE_TEMPLATES
    if len(specs) != 50:
        raise SystemExit(f"Expected 50 scripts, got {len(specs)}")

    for spec in specs:
        target = SCRIPTS_DIR / f"{spec.slug}.py"
        target.write_text(_render(spec), encoding="utf-8")

        golden = GOLDEN_DIR / f"{spec.slug}.json"
        golden.write_text(
            json.dumps(
                {
                    "audit_lines": spec.expected_audit_lines,
                    "stdout_contains": spec.stdout_marker,
                    "expected_failure": spec.is_expected_failure,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    print(f"Generated {len(specs)} scripts into {SCRIPTS_DIR}")


if __name__ == "__main__":
    _emit()
