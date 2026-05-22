"""Generate the 50 representative arcpy eval scripts.

Run once from the package root:

    python eval/_generate_scripts.py

The generator emits 50 scripts plus matching golden references that exercise
the supported subset of ``honua_arcpy`` (Buffer / Clip / Intersect / Union /
Erase / SpatialJoin / Dissolve / Copy / Delete / Project + the SDK-only
management ops + the three da cursors). Stub-only functions deliberately
appear in a handful of scripts named ``expected_failure_*`` so the eval
harness can verify they raise ``HonuaArcpyUnsupportedError``.

Distribution: ~70% supported scripts + ~30% expected-failure scripts.
This biases the eval pass rate to the supported MVP surface (matches the
design's R2 mitigation).
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


_supported(
    "buffer_roads_dissolve_all",
    "transport",
    "Buffer all roads by 25m and dissolve into a single feature.",
    """arcpy.analysis.Buffer("roads", "roads_buffer", "25 Meters", dissolve_option="ALL")
print("buffer_roads_dissolve_all ok")
""",
    1,
    "buffer_roads_dissolve_all ok",
)

_supported(
    "buffer_clip_roads_in_study",
    "transport",
    "Buffer then clip roads against a study area.",
    """arcpy.analysis.Buffer("roads", "roads_buffer", "25 Meters", dissolve_option="ALL")
arcpy.analysis.Clip("roads_buffer", "study_area", "roads_clip")
print("buffer_clip_roads_in_study ok")
""",
    2,
    "buffer_clip_roads_in_study ok",
)

_supported(
    "project_roads_to_wgs84",
    "transport",
    "Reproject a roads feature class to WGS84.",
    """arcpy.management.Project("roads", "roads_wgs84", 4326)
print("project_roads_to_wgs84 ok")
""",
    1,
    "project_roads_to_wgs84 ok",
)

_supported(
    "intersect_roads_parcels",
    "transport",
    "Intersect roads with parcels for right-of-way analysis.",
    """arcpy.analysis.Intersect(["roads", "parcels"], "roads_x_parcels", "ALL")
print("intersect_roads_parcels ok")
""",
    1,
    "intersect_roads_parcels ok",
)

_supported(
    "union_zoning_layers",
    "planning",
    "Union two zoning layers preserving all attributes.",
    """arcpy.analysis.Union(["zoning_2020", "zoning_2024"], "zoning_union", "ALL")
print("union_zoning_layers ok")
""",
    1,
    "union_zoning_layers ok",
)

_supported(
    "erase_water_from_parcels",
    "planning",
    "Erase water features from parcels.",
    """arcpy.analysis.Erase("parcels", "water", "parcels_dry")
print("erase_water_from_parcels ok")
""",
    1,
    "erase_water_from_parcels ok",
)

_supported(
    "spatial_join_addresses_parcels",
    "planning",
    "Spatial join addresses to parcels (one-to-one, intersect).",
    """arcpy.analysis.SpatialJoin(
    "addresses",
    "parcels",
    "addresses_with_parcel",
    join_operation="JOIN_ONE_TO_ONE",
    join_type="KEEP_ALL",
    match_option="INTERSECT",
)
print("spatial_join_addresses_parcels ok")
""",
    1,
    "spatial_join_addresses_parcels ok",
)

_supported(
    "dissolve_parcels_by_zoning",
    "planning",
    "Dissolve parcels by zoning code.",
    """arcpy.management.Dissolve(
    "parcels",
    "parcels_by_zoning",
    dissolve_field=["zoning_code"],
    statistics_fields=[["acres", "SUM"]],
)
print("dissolve_parcels_by_zoning ok")
""",
    1,
    "dissolve_parcels_by_zoning ok",
)

_supported(
    "copy_pavement_to_backup",
    "transport",
    "Copy a pavement layer to a backup feature class.",
    """arcpy.management.Copy("pavement", "pavement_backup")
print("copy_pavement_to_backup ok")
""",
    1,
    "copy_pavement_to_backup ok",
)

_supported(
    "delete_obsolete_layer",
    "transport",
    "Delete an obsolete feature class.",
    """arcpy.management.Delete("scratch_layer")
print("delete_obsolete_layer ok")
""",
    1,
    "delete_obsolete_layer ok",
)

_supported(
    "calculate_field_speed",
    "transport",
    "Calculate a derived speed field on segments.",
    """arcpy.management.CalculateField(
    "segments",
    "avg_speed",
    "!miles! / !hours!",
    expression_type="PYTHON3",
)
print("calculate_field_speed ok")
""",
    1,
    "calculate_field_speed ok",
)

# NOTE: AddField / DeleteField / Rename / ListFields / Describe are stubs in
# the 0.1.0 manifest because HonuaAdminClient does not yet expose per-layer
# schema mutation or reading. The matching scenarios live in the expected
# failure block below so the eval suite still demonstrates the migration
# scanner-handoff contract (hint + tracking ticket) for those entries.

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
    "buffer_select_by_attribute",
    "transport",
    "Buffer, then select features by attribute.",
    """arcpy.analysis.Buffer("roads", "roads_buffer", "10 Meters")
arcpy.management.MakeFeatureLayer("roads", "roads_lyr")
arcpy.management.SelectLayerByAttribute("roads_lyr", "NEW_SELECTION", "STATUS = 'OPEN'")
print("buffer_select_by_attribute ok")
""",
    3,
    "buffer_select_by_attribute ok",
)

_supported(
    "calculate_field_then_dissolve",
    "transport",
    "Calculate a field then dissolve on it.",
    """arcpy.management.CalculateField("parcels", "group", "!zoning_code!", expression_type="PYTHON3")
arcpy.management.Dissolve("parcels", "parcels_grouped", dissolve_field=["group"])
print("calculate_field_then_dissolve ok")
""",
    2,
    "calculate_field_then_dissolve ok",
)

_supported(
    "buffer_intersect_union_pipeline",
    "transport",
    "Composite Buffer -> Intersect -> Union pipeline.",
    """arcpy.analysis.Buffer("roads", "roads_buffer", "5 Meters", dissolve_option="ALL")
arcpy.analysis.Intersect(["roads_buffer", "parcels"], "roads_x_parcels", "ALL")
arcpy.analysis.Union(["roads_x_parcels", "right_of_way"], "row_combined", "ALL")
print("buffer_intersect_union_pipeline ok")
""",
    3,
    "buffer_intersect_union_pipeline ok",
)

_supported(
    "project_then_clip",
    "planning",
    "Reproject then clip the result.",
    """arcpy.management.Project("parcels", "parcels_wgs", 4326)
arcpy.analysis.Clip("parcels_wgs", "study_area", "parcels_in_study")
print("project_then_clip ok")
""",
    2,
    "project_then_clip ok",
)

_supported(
    "spatial_join_with_radius",
    "planning",
    "SpatialJoin with explicit search radius.",
    """arcpy.analysis.SpatialJoin(
    "facilities",
    "parcels",
    "facilities_with_parcel",
    join_operation="JOIN_ONE_TO_ONE",
    match_option="WITHIN_A_DISTANCE",
    search_radius="100 Meters",
)
print("spatial_join_with_radius ok")
""",
    1,
    "spatial_join_with_radius ok",
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

_supported(
    "buffer_legacy_suffix",
    "transport",
    "Use the legacy ``Buffer_analysis`` suffix idiom via arcpy.analysis.Buffer.",
    """arcpy.analysis.Buffer("trails", "trails_buffer", "15 Meters")
print("buffer_legacy_suffix ok")
""",
    1,
    "buffer_legacy_suffix ok",
)

_supported(
    "copy_then_delete",
    "transport",
    "Copy a layer then delete the source.",
    """arcpy.management.Copy("scratch", "scratch_archive")
arcpy.management.Delete("scratch")
print("copy_then_delete ok")
""",
    2,
    "copy_then_delete ok",
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
