"""Tests for the local ArcPy migration scanner."""

from __future__ import annotations

import json
from pathlib import Path

from honua_admin import ArcPyScriptInventoryArtifact, scan_arcpy_script, scan_arcpy_source
from honua_admin._arcpy_scanner import main as arcpy_scan_main


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "arcpy"


def test_scan_arcpy_script_finds_automated_vector_candidates() -> None:
    artifact = scan_arcpy_script(FIXTURES / "automated_vector.py")
    payload = artifact.to_dict()

    assert isinstance(artifact, ArcPyScriptInventoryArtifact)
    assert payload["artifactKind"] == "honua.migration.arcpy-script-inventory"
    assert payload["sourceKind"] == "arcpy-python-script"
    assert artifact.summary.tool_call_count == 4
    assert artifact.summary.automated_candidate_count == 4
    assert {call.honua_process_id for call in artifact.tool_calls} == {
        "honua.process.vector.buffer",
        "honua.process.vector.clip",
        "honua.process.vector.intersect",
        "honua.process.vector.project",
    }
    assert {call.tool for call in artifact.tool_calls} == {"Buffer", "Clip", "Intersect", "Project"}
    assert [parameter.index for parameter in artifact.parameters] == [0, 1]
    assert scan_arcpy_script(FIXTURES / "automated_vector.py").to_dict() == payload
    json.dumps(payload, sort_keys=True)


def test_scan_arcpy_script_classifies_unsupported_destructive_and_unknown_calls() -> None:
    artifact = scan_arcpy_script(FIXTURES / "unsupported_destructive.py")
    calls = {call.tool: call for call in artifact.tool_calls}

    assert calls["Raster"].classification == "unsupported"
    assert calls["Raster"].category == "raster-surface"
    assert calls["Slope"].classification == "unsupported"
    assert calls["Slope"].category == "raster-surface"
    assert calls["Delete"].classification == "manual-review"
    assert calls["Delete"].category == "destructive"
    assert calls["SomeMysteryTool"].classification == "manual-review"
    assert calls["SomeMysteryTool"].category == "unknown"
    assert artifact.summary.unsupported_count == 2
    assert artifact.summary.manual_review_count == 2


def test_scan_arcpy_script_detects_parameters_env_and_license_calls() -> None:
    artifact = scan_arcpy_script(FIXTURES / "parameters_env_redaction.py")

    assert [(parameter.function, parameter.direction, parameter.index) for parameter in artifact.parameters] == [
        ("GetParameterAsText", "input", 0),
        ("GetParameter", "input", 1),
        ("SetParameterAsText", "output", 2),
    ]
    assert artifact.parameters[2].value == "<local-path>/customer_project.gdb/buffered_output"

    environments = {environment.name: environment.value for environment in artifact.environments}
    assert environments == {
        "workspace": "<local-path>/customer_project.gdb",
        "overwriteOutput": True,
    }

    assert len(artifact.license_calls) == 1
    assert artifact.license_calls[0].function == "CheckOutExtension"
    assert artifact.license_calls[0].action == "checkout"
    assert artifact.license_calls[0].extension == "Spatial"
    assert artifact.summary.parameter_count == 3
    assert artifact.summary.environment_assignment_count == 2
    assert artifact.summary.license_call_count == 1


def test_scan_arcpy_script_redacts_paths_urls_and_secrets() -> None:
    artifact = scan_arcpy_script(FIXTURES / "parameters_env_redaction.py")
    payload_text = json.dumps(artifact.to_dict(), sort_keys=True)

    assert "portal-password" not in payload_text
    assert "super-token" not in payload_text
    assert "plain-text-password" not in payload_text
    assert "/home/makani" not in payload_text
    assert "C:\\Users" not in payload_text
    assert "C:/Users" not in payload_text

    literals = artifact.literals
    assert any(literal.kind == "secret" and literal.value == "<redacted>" for literal in literals)
    assert any(
        literal.kind == "url"
        and "<redacted>@example.com" in literal.value
        and "token=<redacted>" in literal.value
        for literal in literals
    )
    assert any(
        literal.kind == "url"
        and literal.value == "file://<local-path>/private.gdb/parcels"
        for literal in literals
    )
    assert any(literal.kind == "path" and literal.value == "<local-path>/private_connection.sde" for literal in literals)
    assert artifact.source.path.endswith("/parameters_env_redaction.py")
    assert artifact.source.path.startswith("<local-path>/")


def test_scan_arcpy_source_warns_when_no_arcpy_imports() -> None:
    artifact = scan_arcpy_source("print('hello')\n", filename="inline.py")

    assert artifact.scan_completeness.status == "complete"
    assert artifact.scan_completeness.warnings == ["No arcpy imports detected."]
    assert artifact.summary.tool_call_count == 0


def test_arcpy_scan_cli_emits_inventory_json(capsys) -> None:
    exit_code = arcpy_scan_main([str(FIXTURES / "automated_vector.py")])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["artifactKind"] == "honua.migration.arcpy-script-inventory"
    assert payload["summary"]["automatedCandidateCount"] == 4
