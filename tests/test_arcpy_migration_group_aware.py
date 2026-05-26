"""Codemod coverage for the group-aware layer-scope GP processes.

Stream 2 uplift unlocked when honua-server made ``generalization.dissolve``
execute at LAYER scope: group input features by attribute field(s) (or
dissolve-all), union geometry per group, optional COUNT/SUM/MEAN/MIN/MAX/FIRST
summary stats. Target for ArcGIS ``Dissolve_management``.

Honesty is the point: only the forms the server actually executes are
``translatable`` and ArcGIS-only options that do not map (multi_part /
unsplit_lines / non-server stat tokens) are recorded as notes, never faked.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from honua_sdk import HonuaClient
from honua_sdk.migration import (
    EXECUTABLE_PROCESS_IDS,
    ArcPyProcessRunner,
    scan_arcpy_source,
    translate_arcpy_source,
)


# ---------------------------------------------------------------------------
# Executable-coverage gate.
# ---------------------------------------------------------------------------
def test_generalization_dissolve_is_executable() -> None:
    assert "generalization.dissolve" in EXECUTABLE_PROCESS_IDS
    # The bare single-geometry ``dissolve`` primitive remains distinct.
    assert "dissolve" in EXECUTABLE_PROCESS_IDS  # geometry.dissolve primitive


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
# Run path through the GP client.
# ---------------------------------------------------------------------------
def test_run_path_executes_dissolve_via_gp_client() -> None:
    plan = translate_arcpy_source(
        "import arcpy\n"
        'arcpy.management.Dissolve("parcels", "out", "ZONE", [["AREA", "SUM"]])\n'
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

    assert [r.result["processID"] for r in results] == ["generalization.dissolve"]
    assert seen[0]["method"] == "POST"
    assert seen[0]["path"] == "/ogc/processes/processes/generalization.dissolve/execution"
    # The full translated body (bespoke inputs + migration metadata) is forwarded.
    assert seen[0]["body"]["inputs"]["statistics"] == [{"field": "AREA", "statistic": "SUM"}]
    assert seen[0]["body"]["metadata"]["honuaMigration"]["tool"] == "Dissolve"
