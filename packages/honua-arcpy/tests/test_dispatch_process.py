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
