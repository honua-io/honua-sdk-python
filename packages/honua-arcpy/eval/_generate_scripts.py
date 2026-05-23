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


# Downgraded process-backed entries (audit pass 8). Each previously
# appeared in the supported block but emitted an arcpy-style payload
# the honua-server BuiltInProcessCatalog rejects. These will be re-promoted
# once the projection adapter lands; meanwhile they exercise the
# raise_unsupported / audit-write contract.
_expected_failure(
    "buffer_roads",
    "    arcpy.analysis.Buffer('roads', 'roads_buffer', '25 Meters', dissolve_option='ALL')",
    "analysis.Buffer",
)
_expected_failure(
    "buffer_legacy_suffix",
    "    arcpy.analysis.Buffer('trails', 'trails_buffer', '15 Meters')",
    "analysis.Buffer",
)
_expected_failure(
    "buffer_then_clip",
    "    arcpy.analysis.Buffer('roads', 'roads_buffer', '25 Meters')",
    "analysis.Buffer",
)
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
    "spatial_join_addresses_parcels",
    "    arcpy.analysis.SpatialJoin('addresses', 'parcels', 'addresses_with_parcel',"
    " join_operation='JOIN_ONE_TO_ONE', join_type='KEEP_ALL', match_option='INTERSECT')",
    "analysis.SpatialJoin",
)
_expected_failure(
    "spatial_join_with_radius",
    "    arcpy.analysis.SpatialJoin('facilities', 'parcels', 'out',"
    " join_operation='JOIN_ONE_TO_ONE', match_option='WITHIN_A_DISTANCE',"
    " search_radius='100 Meters')",
    "analysis.SpatialJoin",
)
_expected_failure(
    "dissolve_parcels_by_zoning",
    "    arcpy.management.Dissolve('parcels', 'parcels_by_zoning',"
    " dissolve_field=['zoning_code'], statistics_fields=[['acres', 'SUM']])",
    "management.Dissolve",
)
_expected_failure(
    "copy_pavement_to_backup",
    "    arcpy.management.Copy('pavement', 'pavement_backup')",
    "management.Copy",
)
_expected_failure(
    "copy_features_alias",
    "    arcpy.management.CopyFeatures('parcels_stage', 'parcels_published')",
    "management.Copy",
)
_expected_failure(
    "delete_obsolete_layer",
    "    arcpy.management.Delete('scratch_layer')",
    "management.Delete",
)
_expected_failure(
    "project_roads_to_wgs84",
    "    arcpy.management.Project('roads', 'roads_wgs84', 4326)",
    "management.Project",
)
_expected_failure(
    "project_parcels_then_clip",
    "    arcpy.management.Project('parcels', 'parcels_wgs', 4326)",
    "management.Project",
)
_expected_failure(
    "calculate_field_speed",
    "    arcpy.management.CalculateField('segments', 'avg_speed', '!miles! / !hours!',"
    " expression_type='PYTHON3')",
    "management.CalculateField",
)
_expected_failure(
    "calculate_field_group",
    "    arcpy.management.CalculateField('parcels', 'group', '!zoning_code!',"
    " expression_type='PYTHON3')",
    "management.CalculateField",
)
_expected_failure(
    "buffer_intersect_union",
    "    arcpy.analysis.Buffer('roads', 'roads_buffer', '5 Meters', dissolve_option='ALL')",
    "analysis.Buffer",
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
