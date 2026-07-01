"""Layer-aware GP tool projection: arcpy signature -> honua-server process.

Each promoted tool (Buffer, SpatialJoin, Dissolve, Project) is exercised
through a faked OGC API Processes transport that models
the async job lifecycle honua-server uses: ``execute`` returns a ``201``
StatusInfo with a ``jobID`` + ``accepted`` status, ``job(jobID)`` resolves to
``successful``, and ``job_results(jobID)`` returns the results document. The
tests assert the projected process id, the typed inputs, that the job was
submitted + polled, and the arcpy-style ``Result`` mapping.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import honua_gp
from honua_gp._process_tools import Result


class _FakeProcessesClient:
    """Models the honua-server async OGC API Processes job lifecycle.

    ``execute`` records the call and returns an ``accepted`` StatusInfo with a
    ``jobID``. The first ``job(...)`` poll returns ``running``; the second (and
    later) returns ``successful`` so the poll loop is genuinely exercised.
    """

    def __init__(self, *, terminal_status: str = "successful", poll_terminal_after: int = 1) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.job_polls: list[str] = []
        self.results_fetches: list[str] = []
        self.dismissed: list[str] = []
        self._terminal_status = terminal_status
        self._poll_terminal_after = poll_terminal_after
        self._poll_count = 0

    def execute(self, process_id: str, payload: dict) -> dict:
        self.calls.append((process_id, payload))
        return {"processID": process_id, "jobID": "job-1", "status": "accepted"}

    def job(self, job_id: str) -> dict:
        self.job_polls.append(job_id)
        self._poll_count += 1
        status = "running" if self._poll_count < self._poll_terminal_after else self._terminal_status
        return {"jobID": job_id, "status": status, "message": "boom" if status == "failed" else None}

    def job_results(self, job_id: str) -> dict:
        self.results_fetches.append(job_id)
        return {"jobID": job_id, "outputs": {"result": {"href": f"honua://jobs/{job_id}/result"}}}

    def dismiss_job(self, job_id: str) -> None:
        self.dismissed.append(job_id)


def _configure(proc: _FakeProcessesClient) -> None:
    honua_gp.configure(processes_client=proc)
    honua_gp.env.overwriteOutput = True


def _no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the submit/poll loop deterministic and instant in tests."""

    import honua_gp._process_jobs as jobs

    monkeypatch.setattr(jobs.time, "sleep", _no_sleep)


def _audit_lines(audit_root: Path) -> list[dict]:
    out: list[dict] = []
    for path in sorted(audit_root.glob("audit-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# analysis.Buffer -> analytics.buffer-aggregate
# ---------------------------------------------------------------------------


def test_buffer_projects_layer_id_distance_unit_and_dissolve(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    result = honua_gp.analysis.Buffer(
        "honua://services/transport/3", "roads_buffer", "25 Kilometers", dissolve_option="ALL"
    )

    assert isinstance(result, Result)
    assert str(result) == "roads_buffer"
    assert result[0] == "roads_buffer"
    assert int(result) == 4  # esriJobSucceeded
    assert result.job_id == "job-1"

    process_id, payload = proc.calls[0]
    assert process_id == "analytics.buffer-aggregate"
    assert payload == {
        "inputs": {
            "layerId": 3,
            "distance": 25.0,
            "unit": "kilometers",
            "dissolve": True,
        }
    }
    # Job was submitted and polled to a terminal state, then results fetched.
    assert proc.job_polls == ["job-1"]
    assert proc.results_fetches == ["job-1"]


def test_buffer_dissolve_none_maps_to_dissolve_false(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    honua_gp.analysis.Buffer("honua://services/t/0", "out", 10, dissolve_option="NONE")

    _, payload = proc.calls[0]
    assert payload["inputs"]["dissolve"] is False
    assert payload["inputs"]["distance"] == 10.0
    assert payload["inputs"]["unit"] == "meters"


def test_buffer_registers_output_alias(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    honua_gp.analysis.Buffer("honua://services/t/0", "roads_buffer", "5 Meters")

    assert honua_gp.get_session().get_layer("roads_buffer") is not None


def test_buffer_writes_single_audit_line(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    honua_gp.analysis.Buffer("honua://services/t/0", "out", "5 Meters")

    lines = [r for r in _audit_lines(_isolated_audit_dir) if r["function"] == "analysis.Buffer"]
    assert len(lines) == 1
    assert lines[0]["status"] == "ok"
    assert lines[0]["process_id"] == "analytics.buffer-aggregate"
    assert lines[0]["job_id"] == "job-1"


# ---------------------------------------------------------------------------
# analysis.SpatialJoin -> analytics.spatial-join
# ---------------------------------------------------------------------------


def test_spatial_join_projects_layer_ids_and_predicate(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    honua_gp.analysis.SpatialJoin(
        "honua://services/addr/1",
        "honua://services/parcels/2",
        "addr_parcel",
        match_option="INTERSECT",
    )

    process_id, payload = proc.calls[0]
    assert process_id == "analytics.spatial-join"
    assert payload["inputs"] == {
        "layerId": 1,
        "joinLayerId": 2,
        "predicate": "intersects",
    }


def test_spatial_join_within_a_distance_maps_to_dwithin_with_distance(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    honua_gp.analysis.SpatialJoin(
        "honua://services/fac/0",
        "honua://services/parcels/0",
        "out",
        match_option="WITHIN_A_DISTANCE",
        search_radius="100 Meters",
    )

    _, payload = proc.calls[0]
    assert payload["inputs"]["predicate"] == "dwithin"
    assert payload["inputs"]["distance"] == 100.0


def test_spatial_join_within_a_distance_without_radius_raises(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        honua_gp.analysis.SpatialJoin(
            "honua://services/fac/0", "honua://services/p/0", "out",
            match_option="WITHIN_A_DISTANCE",
        )
    # No job submitted on a pre-dispatch validation failure.
    assert proc.calls == []


# ---------------------------------------------------------------------------
# management.Dissolve -> generalization.dissolve
# ---------------------------------------------------------------------------


def test_dissolve_projects_group_by_fields(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    honua_gp.management.Dissolve(
        "honua://services/parcels/0", "parcels_dissolved", dissolve_field=["zoning", "city"]
    )

    process_id, payload = proc.calls[0]
    assert process_id == "generalization.dissolve"
    assert payload["inputs"] == {"layerId": 0, "groupByFields": "zoning,city"}


# ---------------------------------------------------------------------------
# management.CalculateField / Copy / CopyFeatures are unsupported stubs.
#
# honua-server classifies data-management.calculate-field and
# data-management.copy-features as CanServe=false: they are never projected as
# standalone OGC API processes (only reachable as steps inside a
# honua-geoprocessing analysis plan), so a one-shot POST .../execution 404s on
# every server version. The shim refuses them client-side without touching the
# transport.
# ---------------------------------------------------------------------------


def test_calculate_field_raises_unsupported(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    with pytest.raises(honua_gp.HonuaGpUnsupportedError):
        honua_gp.management.CalculateField(
            "honua://services/segments/5", "speed", "miles / hours", where_clause="miles > 0"
        )
    assert proc.calls == []


def test_copy_raises_unsupported(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    with pytest.raises(honua_gp.HonuaGpUnsupportedError):
        honua_gp.management.Copy("honua://services/stage/4", "published")
    assert proc.calls == []


def test_copy_features_alias_raises_unsupported(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    with pytest.raises(honua_gp.HonuaGpUnsupportedError):
        honua_gp.management.CopyFeatures("honua://services/stage/0", "out")
    assert proc.calls == []


# ---------------------------------------------------------------------------
# management.Project -> conversion.feature-project
# ---------------------------------------------------------------------------


def test_project_projects_layer_id_and_target_srid(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    honua_gp.management.Project("honua://services/roads/2", "roads_wgs84", 4326)

    process_id, payload = proc.calls[0]
    assert process_id == "conversion.feature-project"
    assert payload["inputs"] == {"layerId": 2, "targetSrid": 4326}


def test_project_numeric_string_srid(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    honua_gp.management.Project("honua://services/roads/0", "out", "3857")

    assert proc.calls[0][1]["inputs"]["targetSrid"] == 3857


def test_project_non_numeric_srid_raises(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    with pytest.raises(honua_gp.HonuaGpConfigurationError):
        honua_gp.management.Project("honua://services/roads/0", "out", "GCS_WGS_1984")
    assert proc.calls == []


# ---------------------------------------------------------------------------
# Job lifecycle: failure, polling, rollback
# ---------------------------------------------------------------------------


def test_failed_job_raises_execute_error_with_message(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient(terminal_status="failed")
    _configure(proc)

    with pytest.raises(honua_gp.ExecuteError) as info:
        honua_gp.management.Project("honua://services/s/0", "out", 4326)
    assert info.value.error_kind == "failed"
    assert "boom" in str(info.value)

    lines = [r for r in _audit_lines(_isolated_audit_dir) if r["function"] == "management.Project"]
    assert lines[-1]["status"] == "error"
    assert lines[-1]["error_kind"] == "failed"


def test_poll_loop_runs_until_terminal(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient(poll_terminal_after=3)
    _configure(proc)

    honua_gp.management.Project("honua://services/s/0", "out", 4326)

    # running, running, successful -> three polls before terminal.
    assert proc.job_polls == ["job-1", "job-1", "job-1"]


def test_failed_job_rolls_back_output_alias(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient(terminal_status="failed")
    honua_gp.configure(processes_client=proc)
    honua_gp.env.overwriteOutput = False

    with pytest.raises(honua_gp.ExecuteError):
        honua_gp.management.Project("honua://services/s/0", "scratch", 4326)

    # A failed job must not leave the output alias behind (so a retry is not
    # blocked by the duplicate-output guard).
    assert honua_gp.get_session().get_layer("scratch") is None


def test_unresolvable_layer_id_raises_resolve_error(_isolated_audit_dir: Path) -> None:
    proc = _FakeProcessesClient()
    _configure(proc)

    # A bare workspace-relative name resolves to a non-numeric service id, so
    # descriptor_mapping yields layerId=0 -- that is valid. A honua://services
    # URI with a non-numeric layer segment is the unresolvable case.
    with pytest.raises(honua_gp.HonuaGpResolveError):
        honua_gp.management.Project("honua://services/roads/notalayer", "out", 4326)
    assert proc.calls == []
