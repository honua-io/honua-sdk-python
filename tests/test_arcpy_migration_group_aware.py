"""Codemod coverage for the group-aware layer-scope GP processes.

These cover the Stream 2 uplift unlocked when honua-server made two further
processes execute at LAYER scope:

* ``generalization.dissolve`` -- group input features by attribute field(s)
  (or dissolve-all), union geometry per group, optional COUNT/SUM/MEAN/MIN/MAX/
  FIRST summary stats. Target for ArcGIS ``Dissolve_management``.
* ``analytics.spatial-join`` -- one-to-one summarizing spatial join with an
  inline ``joinGeoJson`` join layer + a spatial predicate. Target for the
  summarizing one-to-one form of ArcGIS ``SpatialJoin_analysis``.

Honesty is the point of these tests: only the forms the server actually
executes are ``translatable``. One-to-many spatial joins, feature-class join
inputs that cannot be inlined, and ArcGIS-only options that do not map are
classified ``manual-review`` with a specific reason -- never faked as runnable.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from honua_sdk import HonuaClient
from honua_sdk.migration import (
    EXECUTABLE_PROCESS_IDS,
    ArcPyProcessRunner,
    build_parity_evidence_for_source,
    scan_arcpy_source,
    translate_arcpy_source,
)

# A literal inline GeoJSON FeatureCollection, the only join_features form the
# spatial-join translator can inline as joinGeoJson.
_INLINE_JOIN = '{"type": "FeatureCollection", "features": []}'


# ---------------------------------------------------------------------------
# Executable-coverage gate: 13 -> 15.
# ---------------------------------------------------------------------------
def test_group_aware_processes_are_executable() -> None:
    assert "generalization.dissolve" in EXECUTABLE_PROCESS_IDS
    assert "analytics.spatial-join" in EXECUTABLE_PROCESS_IDS
    # The bare single-geometry primitives remain; the two group-aware
    # layer-scope processes are net-new, taking the count to 15.
    assert len(EXECUTABLE_PROCESS_IDS) == 15
    # The bare ``dissolve`` / ``spatial-join`` ids are NOT the group-aware
    # targets: bare dissolve is the geometry.dissolve primitive, and bare
    # spatial-join was never executable.
    assert "dissolve" in EXECUTABLE_PROCESS_IDS  # geometry.dissolve primitive
    assert "spatial-join" not in EXECUTABLE_PROCESS_IDS


# ---------------------------------------------------------------------------
# Dissolve_management -> generalization.dissolve.
# ---------------------------------------------------------------------------
def test_dissolve_translates_to_generalization_dissolve_with_stats() -> None:
    plan = translate_arcpy_source(
        "import arcpy\n"
        'arcpy.management.Dissolve("parcels", "out", "ZONE", '
        '[["AREA", "SUM"], ["POP", "MEAN"]])'
    )

    assert [t.process_id for t in plan.translations] == ["generalization.dissolve"]
    inputs = plan.translations[0].payload["inputs"]
    assert inputs["layerId"] == "parcels"
    assert inputs["groupByFields"] == ["ZONE"]
    assert inputs["statistics"] == [
        {"field": "AREA", "statistic": "SUM"},
        {"field": "POP", "statistic": "MEAN"},
    ]


def test_dissolve_classified_translatable_in_scan() -> None:
    report = scan_arcpy_source('import arcpy\narcpy.management.Dissolve("parcels", "out", "ZONE")')
    (call,) = report.calls
    assert call.supported is True
    assert call.translatable is True
    assert call.status == "translatable"
    assert call.process_id == "generalization.dissolve"


def test_dissolve_all_records_a_dissolve_all_note() -> None:
    plan = translate_arcpy_source('import arcpy\narcpy.management.Dissolve("parcels", "out")')
    translation = plan.translations[0]
    assert translation.payload["inputs"]["groupByFields"] == []
    assert any("single group" in note for note in translation.notes)


def test_dissolve_multiple_group_fields_semicolon_and_list() -> None:
    semi = translate_arcpy_source(
        'import arcpy\narcpy.management.Dissolve("p", "out", "ZONE;CLASS")'
    ).translations[0]
    assert semi.payload["inputs"]["groupByFields"] == ["ZONE", "CLASS"]

    as_list = translate_arcpy_source(
        'import arcpy\narcpy.management.Dissolve("p", "out", ["ZONE", "CLASS"])'
    ).translations[0]
    assert as_list.payload["inputs"]["groupByFields"] == ["ZONE", "CLASS"]


def test_dissolve_unsupported_stat_token_is_reported_not_dropped_silently() -> None:
    plan = translate_arcpy_source(
        'import arcpy\narcpy.management.Dissolve("p", "out", "ZONE", [["AREA", "STD"]])'
    )
    translation = plan.translations[0]
    # STD is not server-computable; it must NOT appear in the statistics spec...
    assert "statistics" not in translation.payload["inputs"]
    # ...but the drop must be reported as a note (no inflated parity).
    assert any("STD" in note and "Recompute" in note for note in translation.notes)


def test_dissolve_multipart_and_unsplit_recorded_as_notes() -> None:
    plan = translate_arcpy_source(
        'import arcpy\narcpy.management.Dissolve("p", "out", "ZONE", None, "SINGLE_PART", "UNSPLIT_LINES")'
    )
    notes = plan.translations[0].notes
    assert any("multi_part" in note for note in notes)
    assert any("unsplit_lines" in note for note in notes)


def test_pairwise_dissolve_aliases_to_generalization_dissolve() -> None:
    plan = translate_arcpy_source(
        'import arcpy\narcpy.analysis.PairwiseDissolve("p", "out", "ZONE")'
    )
    assert [t.process_id for t in plan.translations] == ["generalization.dissolve"]


# ---------------------------------------------------------------------------
# SpatialJoin_analysis -> analytics.spatial-join (supported one-to-one form).
# ---------------------------------------------------------------------------
def test_spatial_join_one_to_one_inline_translates() -> None:
    plan = translate_arcpy_source(
        "import arcpy\n"
        f'arcpy.analysis.SpatialJoin("parcels", {_INLINE_JOIN}, "out", '
        '"JOIN_ONE_TO_ONE", "KEEP_ALL", None, "INTERSECT")'
    )
    assert [t.process_id for t in plan.translations] == ["analytics.spatial-join"]
    inputs = plan.translations[0].payload["inputs"]
    assert inputs["layerId"] == "parcels"
    assert json.loads(inputs["joinGeoJson"]) == {"type": "FeatureCollection", "features": []}
    assert inputs["predicate"] == "intersects"


def test_spatial_join_predicate_mapping_contains_and_within() -> None:
    for match_option, predicate in (("CONTAINS", "contains"), ("WITHIN", "within")):
        plan = translate_arcpy_source(
            "import arcpy\n"
            f'arcpy.analysis.SpatialJoin("t", {_INLINE_JOIN}, "out", '
            f'"JOIN_ONE_TO_ONE", "KEEP_ALL", None, "{match_option}")'
        )
        assert plan.translations[0].payload["inputs"]["predicate"] == predicate


def test_spatial_join_defaults_predicate_to_intersects_with_note() -> None:
    plan = translate_arcpy_source(
        f'import arcpy\narcpy.analysis.SpatialJoin("t", {_INLINE_JOIN}, "out")'
    )
    translation = plan.translations[0]
    assert translation.payload["inputs"]["predicate"] == "intersects"
    assert any("defaulting predicate to intersects" in note for note in translation.notes)


def test_spatial_join_field_mapping_recorded_as_note() -> None:
    plan = translate_arcpy_source(
        "import arcpy\n"
        f'arcpy.analysis.SpatialJoin("t", {_INLINE_JOIN}, "out", '
        '"JOIN_ONE_TO_ONE", "KEEP_ALL", "POP \\"Population\\" SUM", "INTERSECT")'
    )
    assert any("field_mapping" in note for note in plan.translations[0].notes)


# ---------------------------------------------------------------------------
# SpatialJoin honesty: unsupported forms are manual-review with a reason.
# ---------------------------------------------------------------------------
def test_spatial_join_one_to_many_is_manual_review() -> None:
    src = (
        "import arcpy\n"
        f'arcpy.analysis.SpatialJoin("t", {_INLINE_JOIN}, "out", "JOIN_ONE_TO_MANY")'
    )
    report = scan_arcpy_source(src)
    (call,) = report.calls
    assert call.status == "manual-review"
    assert call.process_id == "analytics.spatial-join"
    assert translate_arcpy_source(src).translations == ()

    evidence = build_parity_evidence_for_source(src)
    reason = evidence["calls"][0]["reason"]
    assert "JOIN_ONE_TO_MANY" in reason
    assert "one-to-one" in reason


def test_spatial_join_feature_class_join_input_is_manual_review() -> None:
    src = 'import arcpy\narcpy.analysis.SpatialJoin("targets", "join_fc", "out")'
    report = scan_arcpy_source(src)
    (call,) = report.calls
    assert call.status == "manual-review"
    assert translate_arcpy_source(src).translations == ()

    reason = build_parity_evidence_for_source(src)["calls"][0]["reason"]
    assert "inline GeoJSON FeatureCollection" in reason
    assert "feature-class reference 'join_fc'" in reason


def test_spatial_join_non_literal_join_input_is_manual_review() -> None:
    # A join layer bound to a variable cannot be inlined at codemod time.
    src = (
        "import arcpy\n"
        "fc = arcpy.management.MakeFeatureLayer('districts', 'd')\n"
        'arcpy.analysis.SpatialJoin("targets", fc, "out")'
    )
    join_call = next(c for c in scan_arcpy_source(src).calls if c.tool == "SpatialJoin")
    assert join_call.status == "manual-review"
    reason = next(
        c["reason"]
        for c in build_parity_evidence_for_source(src)["calls"]
        if c["tool"] == "SpatialJoin"
    )
    assert "non-literal expression" in reason


def test_spatial_join_unsupported_match_option_is_manual_review() -> None:
    src = (
        "import arcpy\n"
        f'arcpy.analysis.SpatialJoin("t", {_INLINE_JOIN}, "out", '
        '"JOIN_ONE_TO_ONE", "KEEP_ALL", None, "CLOSEST")'
    )
    (call,) = scan_arcpy_source(src).calls
    assert call.status == "manual-review"
    reason = build_parity_evidence_for_source(src)["calls"][0]["reason"]
    assert "CLOSEST" in reason


# ---------------------------------------------------------------------------
# Coverage rollup + run path through the GP client.
# ---------------------------------------------------------------------------
def test_coverage_rollup_dissolve_translatable_join_split_by_form() -> None:
    src = (
        "import arcpy\n"
        'arcpy.management.Dissolve("p", "out", "ZONE")\n'
        f'arcpy.analysis.SpatialJoin("t", {_INLINE_JOIN}, "j1", "JOIN_ONE_TO_ONE")\n'
        'arcpy.analysis.SpatialJoin("t", "fc", "j2")\n'
    )
    plan = translate_arcpy_source(src)
    assert [t.process_id for t in plan.translations] == [
        "generalization.dissolve",
        "analytics.spatial-join",
    ]
    assert [(c.tool, c.status) for c in plan.report.calls] == [
        ("Dissolve", "translatable"),
        ("SpatialJoin", "translatable"),
        ("SpatialJoin", "manual-review"),
    ]


def test_run_path_executes_group_aware_translations_via_gp_client() -> None:
    plan = translate_arcpy_source(
        "import arcpy\n"
        'arcpy.management.Dissolve("parcels", "out", "ZONE", [["AREA", "SUM"]])\n'
        f'arcpy.analysis.SpatialJoin("targets", {_INLINE_JOIN}, "out2", "JOIN_ONE_TO_ONE", '
        '"KEEP_ALL", None, "WITHIN")\n'
    )
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "path": request.url.raw_path.decode("ascii").split("?")[0],
                "body": json.loads(request.content) if request.content else None,
            }
        )
        process_id = request.url.path.split("/")[-2]
        return httpx.Response(201, json={"jobID": "j", "status": "accepted", "processID": process_id})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        runner = ArcPyProcessRunner(client)
        assert runner._geoprocessing is not None
        assert runner._processes is None
        results = runner.execute_plan(plan)

    assert [r.result["processID"] for r in results] == [
        "generalization.dissolve",
        "analytics.spatial-join",
    ]
    assert [(e["method"], e["path"]) for e in seen] == [
        ("POST", "/ogc/processes/processes/generalization.dissolve/execution"),
        ("POST", "/ogc/processes/processes/analytics.spatial-join/execution"),
    ]
    # The full translated body (bespoke inputs + migration metadata) is forwarded.
    assert seen[0]["body"]["inputs"]["statistics"] == [{"field": "AREA", "statistic": "SUM"}]
    assert seen[0]["body"]["metadata"]["honuaMigration"]["tool"] == "Dissolve"
    assert seen[1]["body"]["inputs"]["predicate"] == "within"
    assert seen[1]["body"]["metadata"]["honuaMigration"]["tool"] == "SpatialJoin"
