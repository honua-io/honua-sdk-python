"""Tests for migration status classification and parity-evidence emission."""

from __future__ import annotations

from honua_sdk.migration import (
    EXECUTABLE_PROCESS_IDS,
    build_parity_evidence,
    build_parity_evidence_for_source,
    scan_arcpy_source,
    translate_arcpy_source,
)

# Mix of: executable target (buffer), broadened executable targets
# (simplify / convex-hull / centroid / snap), a tool whose target process IS
# executable but whose invocation form is not -- SpatialJoin with a
# feature-class join input (here "b") cannot be inlined as joinGeoJson, so it
# is gated to manual-review with a specific reason -- and a wholly unmapped
# tool (sa.Slope).
MIXED_SOURCE = """
import arcpy

arcpy.analysis.Buffer("roads", "rb", "25 Meters")
arcpy.cartography.SimplifyPolygon("poly", "poly_s", "POINT_REMOVE", "10 Meters")
arcpy.management.MinimumBoundingGeometry("pts", "hull", "CONVEX_HULL")
arcpy.management.FeatureToPoint("poly", "cent", "INSIDE")
arcpy.edit.Snap("pts", [["lines", "EDGE", "5 Meters"]])
arcpy.analysis.SpatialJoin("a", "b", "joined")
arcpy.sa.Slope("dem")
"""


def test_migration_is_reachable_from_top_level_package() -> None:
    import honua_sdk
    from honua_sdk import migration

    assert migration is honua_sdk.migration
    assert hasattr(migration, "scan_arcpy_source")
    assert hasattr(migration, "build_parity_evidence")
    assert hasattr(migration, "parse_pyt_source")
    assert isinstance(migration.EXECUTABLE_PROCESS_IDS, frozenset)


def test_broadened_tools_map_to_executable_processes() -> None:
    plan = translate_arcpy_source(MIXED_SOURCE, filename="mixed.py")

    assert [t.process_id for t in plan.translations] == [
        "buffer",
        "simplify",
        "convex-hull",
        "centroid",
        "snap",
    ]
    # Every translated process id must be server-executable.
    assert all(t.process_id in EXECUTABLE_PROCESS_IDS for t in plan.translations)


def test_status_partitions_into_translatable_manual_unsupported() -> None:
    report = scan_arcpy_source(MIXED_SOURCE, filename="mixed.py")

    translatable = {(c.family, c.tool) for c in report.translatable_calls}
    manual = {(c.family, c.tool) for c in report.manual_review_calls}
    unsupported = {(c.family, c.tool) for c in report.unsupported_calls}

    assert ("analysis", "Buffer") in translatable
    assert ("cartography", "SimplifyPolygon") in translatable
    assert ("management", "MinimumBoundingGeometry") in translatable
    assert ("editing", "Snap") in translatable
    # SpatialJoin's target (analytics.spatial-join) is executable, but a
    # feature-class join input cannot be inlined -> gated to manual-review.
    assert ("analysis", "SpatialJoin") in manual
    # sa.Slope has no Honua mapping at all.
    assert ("spatial-analyst", "Slope") in unsupported
    # The three buckets are disjoint.
    assert translatable.isdisjoint(manual)
    assert translatable.isdisjoint(unsupported)
    assert manual.isdisjoint(unsupported)


def test_manual_review_call_is_not_translatable_and_has_process_id() -> None:
    report = scan_arcpy_source('import arcpy\narcpy.analysis.Erase("a", "b", "c")')
    (call,) = report.calls

    assert call.supported is True
    assert call.translatable is False
    assert call.status == "manual-review"
    assert call.process_id == "erase"
    assert "erase" not in EXECUTABLE_PROCESS_IDS


def test_parity_evidence_report_shape_and_coverage() -> None:
    evidence = build_parity_evidence_for_source(MIXED_SOURCE, filename="mixed.py")

    assert evidence["schema"] == "honua.migration.arcpy.parity-evidence/v1"
    assert evidence["source"] == "mixed.py"

    summary = evidence["summary"]
    assert summary["totalCalls"] == 7
    assert summary["translatableCalls"] == 5
    assert summary["manualReviewCalls"] == 1
    assert summary["unsupportedCalls"] == 1
    assert summary["coveragePercent"] == round(100.0 * 5 / 7, 2)
    assert summary["executableProcessIds"] == sorted(EXECUTABLE_PROCESS_IDS)

    by_tool = {(c["family"], c["tool"]): c for c in evidence["calls"]}
    # Translatable calls carry a runnable payload.
    assert "payload" in by_tool[("analysis", "Buffer")]
    # Manual-review calls carry a reason but no payload.
    spatial_join = by_tool[("analysis", "SpatialJoin")]
    assert spatial_join["status"] == "manual-review"
    assert "payload" not in spatial_join
    # The gate reason is specific: the feature-class join input cannot be inlined.
    assert "inline GeoJSON FeatureCollection" in spatial_join["reason"]
    # Unsupported calls carry a reason explaining there is no mapping.
    slope = by_tool[("spatial-analyst", "Slope")]
    assert slope["status"] == "unsupported"
    assert slope["processId"] is None
    assert "No Honua process mapping" in slope["reason"]

    tool_status = {(t["family"], t["tool"]): t for t in evidence["toolStatus"]}
    assert tool_status[("analysis", "Buffer")]["status"] == "translatable"
    assert tool_status[("analysis", "SpatialJoin")]["status"] == "manual-review"


def test_parity_evidence_counts_duplicate_calls_per_tool() -> None:
    src = """
import arcpy
arcpy.analysis.Buffer("a", "b", "1 Meters")
arcpy.analysis.Buffer("c", "d", "2 Meters")
"""
    evidence = build_parity_evidence(translate_arcpy_source(src))
    buffer_status = next(t for t in evidence["toolStatus"] if t["tool"] == "Buffer")
    assert buffer_status["count"] == 2
    assert evidence["summary"]["coveragePercent"] == 100.0


def test_parity_evidence_handles_syntax_error() -> None:
    evidence = build_parity_evidence_for_source("import arcpy\narcpy.analysis.Buffer(", filename="bad.py")
    assert evidence["syntaxError"] is not None
    assert evidence["summary"]["totalCalls"] == 0
    assert evidence["summary"]["coveragePercent"] == 0.0
