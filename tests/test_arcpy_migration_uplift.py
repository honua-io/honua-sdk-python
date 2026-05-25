"""Codemod coverage-uplift tests coupled to layer-scope GP executability.

These cover the Stream 5 <-> Stream 2 coupling: now that the server executes
``geometry.make-valid`` at layer scope, ArcPy ``RepairGeometry`` becomes a
runnable (``translatable``) migration, and the ArcPyProcessRunner ``run`` path
flows through the first-class geoprocessing client.
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


def test_make_valid_is_executable_but_erase_remains_manual_review() -> None:
    # make-valid is the net-new executable operation unlocked by layer-scope GP.
    assert "make-valid" in EXECUTABLE_PROCESS_IDS
    # Layer-scope difference erases against a WKT region, not ArcPy Erase's
    # feature-class semantics, so erase must stay non-executable (honest gate).
    assert "erase" not in EXECUTABLE_PROCESS_IDS


def test_repair_geometry_translates_to_make_valid() -> None:
    plan = translate_arcpy_source(
        'import arcpy\narcpy.management.RepairGeometry("parcels", "DELETE_NULL")'
    )

    assert [t.process_id for t in plan.translations] == ["make-valid"]
    payload = plan.translations[0].payload
    assert payload["inputs"]["input_features"] == "parcels"
    assert payload["inputs"]["delete_null"] == "DELETE_NULL"


def test_repair_geometry_classified_translatable_in_scan() -> None:
    report = scan_arcpy_source('import arcpy\narcpy.management.RepairGeometry("parcels")')
    (call,) = report.calls
    assert call.supported is True
    assert call.translatable is True
    assert call.status == "translatable"
    assert call.process_id == "make-valid"


def test_coverage_delta_includes_repair_geometry_alongside_buffer() -> None:
    # Buffer (always executable) + RepairGeometry (now executable) + Erase
    # (still manual-review). Two of three translatable.
    src = (
        "import arcpy\n"
        'arcpy.analysis.Buffer("roads", "rb", "25 Meters")\n'
        'arcpy.management.RepairGeometry("rb")\n'
        'arcpy.analysis.Erase("rb", "holes", "out")\n'
    )
    plan = translate_arcpy_source(src)
    assert [t.process_id for t in plan.translations] == ["buffer", "make-valid"]
    assert [(c.tool, c.status) for c in plan.report.calls] == [
        ("Buffer", "translatable"),
        ("RepairGeometry", "translatable"),
        ("Erase", "manual-review"),
    ]


def test_run_path_uses_geoprocessing_client_and_forwards_full_payload() -> None:
    plan = translate_arcpy_source(
        'import arcpy\narcpy.management.RepairGeometry("parcels", "DELETE_NULL")'
    )
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "path": request.url.raw_path.decode("ascii").split("?")[0],
                "body": json.loads(request.content) if request.content else None,
                "prefer": request.headers.get("Prefer"),
            }
        )
        process_id = request.url.path.split("/")[-2]
        return httpx.Response(201, json={"jobID": "j", "status": "accepted", "processID": process_id})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        runner = ArcPyProcessRunner(client)
        # Confirm the GP-client path is selected over the legacy ogc_processes path.
        assert runner._geoprocessing is not None
        assert runner._processes is None
        (execution,) = runner.execute_plan(plan)

    assert execution.result["processID"] == "make-valid"
    assert seen[0]["method"] == "POST"
    assert seen[0]["path"] == "/ogc/processes/processes/make-valid/execution"
    # The full translated body (inputs + metadata) is forwarded verbatim.
    assert seen[0]["body"]["inputs"] == {"input_features": "parcels", "delete_null": "DELETE_NULL"}
    assert seen[0]["body"]["metadata"]["honuaMigration"]["tool"] == "RepairGeometry"


def test_run_path_falls_back_to_ogc_processes_for_legacy_clients() -> None:
    """A client exposing only ogc_processes() (no geoprocessing()) still works."""
    plan = translate_arcpy_source('import arcpy\narcpy.analysis.Buffer("roads", "rb", "5 Meters")')

    class _LegacyProcesses:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def execute(self, process_id: str, payload: dict[str, Any]) -> dict[str, Any]:
            self.calls.append((process_id, payload))
            return {"processID": process_id, "status": "accepted"}

    class _LegacyClient:
        def __init__(self, processes: _LegacyProcesses) -> None:
            self._processes = processes

        def ogc_processes(self) -> _LegacyProcesses:
            return self._processes

    processes = _LegacyProcesses()
    runner = ArcPyProcessRunner(_LegacyClient(processes))
    assert runner._geoprocessing is None
    (execution,) = runner.execute_plan(plan)

    assert execution.result["processID"] == "buffer"
    assert processes.calls[0][0] == "buffer"
