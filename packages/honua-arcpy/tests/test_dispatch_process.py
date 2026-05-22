"""Process-backed dispatch: payload shape, audit JSONL, error wrapping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import honua_arcpy


class _CapturingProcessesClient:
    def __init__(self, response: dict | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.response = response or {"processID": "geometry.buffer", "status": "accepted"}

    def execute(self, process_id: str, payload: dict) -> dict:
        self.calls.append((process_id, payload))
        return self.response


def _audit_lines(audit_root: Path) -> list[dict]:
    out: list[dict] = []
    for path in sorted(audit_root.glob("audit-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def test_buffer_emits_geometry_buffer_payload(_isolated_audit_dir: Path) -> None:
    proc = _CapturingProcessesClient()
    honua_arcpy.configure(processes_client=proc)
    honua_arcpy.analysis.Buffer("roads", "roads_buffer", "25 Meters", dissolve_option="ALL")

    assert proc.calls == [
        (
            "geometry.buffer",
            {
                "inputs": {
                    "input_features": "roads",
                    "distance": "25 Meters",
                    "dissolve_option": "ALL",
                },
                "outputs": {"result": "roads_buffer"},
            },
        )
    ]
    lines = _audit_lines(_isolated_audit_dir)
    assert len(lines) == 1
    record = lines[0]
    assert record["function"] == "analysis.Buffer"
    assert record["status"] == "ok"
    assert record["process_id"] == "geometry.buffer"
    assert record["result_shape"] is not None


def test_clip_resolves_workspace_and_writes_outputs(_isolated_audit_dir: Path) -> None:
    proc = _CapturingProcessesClient(response={"processID": "geometry.clip"})
    honua_arcpy.configure(processes_client=proc)
    honua_arcpy.env.workspace = "honua://services/transport"
    honua_arcpy.env.overwriteOutput = True

    honua_arcpy.analysis.Clip("roads_buffer", "study_area", "roads_clip")

    assert proc.calls[0][0] == "geometry.clip"
    payload = proc.calls[0][1]
    assert payload["inputs"] == {
        "input_features": "roads_buffer",
        "clip_features": "study_area",
    }
    assert payload["outputs"] == {"result": "roads_clip"}
    assert payload["metadata"]["honuaArcpy"]["workspace"] == "honua://services/transport"
    assert payload["metadata"]["honuaArcpy"]["overwriteOutput"] is True


def test_process_failure_wraps_in_execute_error(_isolated_audit_dir: Path) -> None:
    class _FailingProcessClient:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    honua_arcpy.configure(processes_client=_FailingProcessClient())
    with pytest.raises(honua_arcpy.ExecuteError) as info:
        honua_arcpy.analysis.Buffer("a", "b", 1)
    err = info.value
    assert err.function == "analysis.Buffer"
    assert err.error_kind == "RuntimeError"
    assert "compatibility-matrix" in (err.compat_anchor or "")

    lines = _audit_lines(_isolated_audit_dir)
    assert lines[0]["status"] == "error"
    assert lines[0]["error_kind"] == "RuntimeError"


def test_stub_raises_unsupported_with_anchor_and_hint() -> None:
    with pytest.raises(honua_arcpy.HonuaArcpyUnsupportedError) as info:
        honua_arcpy.analysis.Near("points", "roads")
    err = info.value
    assert err.function == "analysis.Near"
    assert "compatibility-matrix" in (err.compat_anchor or "")
    assert err.replacement_hint and "Source.query" in err.replacement_hint
    assert err.tracking and err.tracking.startswith("honua-server#")


def test_buffer_skips_none_kwargs(_isolated_audit_dir: Path) -> None:
    proc = _CapturingProcessesClient()
    honua_arcpy.configure(processes_client=proc)
    honua_arcpy.analysis.Buffer("roads", "roads_buffer", "5 Meters")
    payload = proc.calls[0][1]
    assert "line_side" not in payload["inputs"]
    assert "line_end_type" not in payload["inputs"]


def test_overwrite_output_guard_prevents_duplicate_output(_isolated_audit_dir: Path) -> None:
    """Two Buffer calls to the same output must fail when overwriteOutput=False."""

    proc = _CapturingProcessesClient()
    honua_arcpy.configure(processes_client=proc)
    honua_arcpy.env.overwriteOutput = False

    honua_arcpy.analysis.Buffer("roads", "roads_buffer", "5 Meters")
    with pytest.raises(honua_arcpy.HonuaArcpyConfigurationError):
        honua_arcpy.analysis.Buffer("roads", "roads_buffer", "10 Meters")

    # Only the first call should have reached the process client.
    assert len(proc.calls) == 1


def test_overwrite_output_true_allows_replace(_isolated_audit_dir: Path) -> None:
    proc = _CapturingProcessesClient()
    honua_arcpy.configure(processes_client=proc)
    honua_arcpy.env.overwriteOutput = True

    honua_arcpy.analysis.Buffer("roads", "roads_buffer", "5 Meters")
    honua_arcpy.analysis.Buffer("roads", "roads_buffer", "10 Meters")

    assert len(proc.calls) == 2


def test_failed_process_rolls_back_output_alias(_isolated_audit_dir: Path) -> None:
    """A failed process call must not leave its output alias behind.

    Output aliases were previously registered *before* ``processes.execute()``
    ran, so a transport failure left ``roads_buffer`` in the session's alias
    map and any retry tripped the duplicate-output guard with
    ``HonuaArcpyConfigurationError`` -- never reaching the process client at
    all. The dispatcher now rolls the alias map back when ``execute()`` raises.
    """

    class _FailingProcessClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def execute(self, process_id: str, payload: dict) -> dict:
            self.calls.append((process_id, payload))
            raise RuntimeError("backend boom")

    proc = _FailingProcessClient()
    honua_arcpy.configure(processes_client=proc)
    honua_arcpy.env.overwriteOutput = False

    with pytest.raises(honua_arcpy.ExecuteError):
        honua_arcpy.analysis.Buffer("roads", "roads_buffer", "5 Meters")

    # The output alias must NOT remain in the session after a failed call;
    # otherwise the retry below would fail with the overwrite guard before
    # even reaching the process client.
    assert honua_arcpy.get_session().get_layer("roads_buffer") is None

    # Retry against a working client: the second call must reach the
    # process client and complete cleanly, proving the prior failure did
    # not corrupt session state.
    working = _CapturingProcessesClient()
    honua_arcpy.configure(processes_client=working)
    honua_arcpy.analysis.Buffer("roads", "roads_buffer", "5 Meters")
    assert len(working.calls) == 1
    assert honua_arcpy.get_session().get_layer("roads_buffer") is not None


def test_failed_process_restores_prior_output_alias_under_overwrite(
    _isolated_audit_dir: Path,
) -> None:
    """When ``overwriteOutput=True``, a failed process call must restore the
    prior alias rather than leaving the half-written replacement in place."""

    class _FailingProcessClient:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("backend boom")

    # First, register a successful output via a working client.
    working = _CapturingProcessesClient()
    honua_arcpy.configure(processes_client=working)
    honua_arcpy.env.overwriteOutput = True
    honua_arcpy.analysis.Buffer("roads", "roads_buffer", "5 Meters")
    first_alias = honua_arcpy.get_session().get_layer("roads_buffer")
    assert first_alias is not None
    first_alias_source = first_alias.source

    # Second call overwrites the alias mid-projection, then execute() fails.
    honua_arcpy.configure(processes_client=_FailingProcessClient())
    with pytest.raises(honua_arcpy.ExecuteError):
        honua_arcpy.analysis.Buffer("highways", "roads_buffer", "25 Meters")

    # The prior alias for ``roads_buffer`` must survive the failed call so
    # downstream consumers do not see a phantom "highways"-derived alias.
    restored = honua_arcpy.get_session().get_layer("roads_buffer")
    assert restored is not None
    assert restored.source == first_alias_source


def test_path_map_applies_inside_intersect_in_features_list(
    _isolated_audit_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HONUA_ARCPY_PATH_MAP overrides must apply to list-valued source params."""

    monkeypatch.setenv(
        "HONUA_ARCPY_PATH_MAP",
        '{"roads": "honua://services/transport/roads", "parcels": "honua://services/land/parcels"}',
    )
    proc = _CapturingProcessesClient()
    honua_arcpy.configure(processes_client=proc)

    honua_arcpy.analysis.Intersect(["roads", "parcels"], "joined")

    payload = proc.calls[0][1]
    assert payload["inputs"]["input_features"] == [
        "honua://services/transport/roads",
        "honua://services/land/parcels",
    ]


def test_path_map_applies_inside_union_in_features_list(
    _isolated_audit_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "HONUA_ARCPY_PATH_MAP",
        '{"zone_a": "honua://services/land/zone_a", "zone_b": "honua://services/land/zone_b"}',
    )
    proc = _CapturingProcessesClient()
    honua_arcpy.configure(processes_client=proc)

    honua_arcpy.analysis.Union(["zone_a", "zone_b"], "merged")

    payload = proc.calls[0][1]
    assert payload["inputs"]["input_features"] == [
        "honua://services/land/zone_a",
        "honua://services/land/zone_b",
    ]


def test_path_map_applies_to_clip_secondary_source(
    _isolated_audit_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clip declares both in_features and clip_features as source_params."""

    monkeypatch.setenv(
        "HONUA_ARCPY_PATH_MAP",
        '{"roads_buffer": "honua://services/transport/roads-buffer",'
        ' "study_area": "honua://services/study/area"}',
    )
    proc = _CapturingProcessesClient()
    honua_arcpy.configure(processes_client=proc)

    honua_arcpy.analysis.Clip("roads_buffer", "study_area", "roads_clip")

    payload = proc.calls[0][1]
    assert payload["inputs"]["input_features"] == "honua://services/transport/roads-buffer"
    assert payload["inputs"]["clip_features"] == "honua://services/study/area"


def test_path_map_does_not_rewrite_non_source_string_params(
    _isolated_audit_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A HONUA_ARCPY_PATH_MAP entry that collides with a literal arcpy keyword
    (e.g. ``"ALL"``) must not rewrite the value when it is bound to a
    non-source parameter such as Buffer's ``dissolve_option``."""

    monkeypatch.setenv(
        "HONUA_ARCPY_PATH_MAP",
        '{"roads": "honua://services/transport/roads",'
        ' "ALL": "honua://services/policy/all",'
        ' "!speed! * 1.1": "honua://services/calc/expression"}',
    )
    proc = _CapturingProcessesClient()
    honua_arcpy.configure(processes_client=proc)

    honua_arcpy.analysis.Buffer("roads", "roads_buffer", "25 Meters", dissolve_option="ALL")
    honua_arcpy.management.CalculateField(
        "roads",
        "scaled_speed",
        "!speed! * 1.1",
        expression_type="PYTHON3",
    )

    buffer_payload = proc.calls[0][1]
    # Source param resolves through the path map.
    assert buffer_payload["inputs"]["input_features"] == "honua://services/transport/roads"
    # Non-source params (dissolve_option, distance) pass through unchanged.
    assert buffer_payload["inputs"]["dissolve_option"] == "ALL"
    assert buffer_payload["inputs"]["distance"] == "25 Meters"

    calc_payload = proc.calls[1][1]
    assert calc_payload["inputs"]["input_features"] == "honua://services/transport/roads"
    # expression / expression_type are not source paths.
    assert calc_payload["inputs"]["expression"] == "!speed! * 1.1"
    assert calc_payload["inputs"]["expression_type"] == "PYTHON3"
