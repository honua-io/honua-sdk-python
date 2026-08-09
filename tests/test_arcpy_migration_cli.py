"""Tests for the ``honua_sdk.migration`` CLI entrypoint (``honua-migrate``)."""

from __future__ import annotations

import json
from pathlib import Path

from honua_sdk.migration._cli import main

# Buffer -> translatable (geometry.buffer); Erase -> manual-review
# (feature-class-vs-single-geometry semantics, honua-server#1228); Kriging ->
# unsupported (an honest honua_gp.sa stub with no working mapping).
SCRIPT = """
import arcpy
arcpy.analysis.Buffer("roads", "roads_buffer", "25 Meters")
arcpy.analysis.Erase("a", "b", "c")
arcpy.sa.Kriging("stations", "PredZ")
"""

PYT = '''
import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "T"
        self.alias = "t"
        self.tools = [A]


class A(object):
    def __init__(self):
        self.label = "A tool"

    def getParameterInfo(self):
        return [arcpy.Parameter(name="in_features", displayName="In", datatype="GPFeatureLayer")]

    def execute(self, parameters, messages):
        arcpy.cartography.SimplifyPolygon("poly", "poly_s", "POINT_REMOVE", "10 Meters")
'''


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_cli_scan_writes_classified_report(tmp_path: Path) -> None:
    script = _write(tmp_path, "wf.py", SCRIPT)
    out = tmp_path / "scan.json"

    rc = main(["scan", str(script), "--output", str(out)])

    assert rc == 0
    report = json.loads(out.read_text())
    statuses = {(c["tool"], c["status"]) for c in report["calls"]}
    assert ("Buffer", "translatable") in statuses
    assert ("Erase", "manual-review") in statuses
    assert ("Kriging", "unsupported") in statuses
    assert report["translatableCount"] == 1
    assert report["manualReviewCount"] == 1
    assert report["unsupportedCount"] == 1
    # The classified Buffer call records its reconciled-server job id.
    buffer_call = next(c for c in report["calls"] if c["tool"] == "Buffer")
    assert buffer_call["jobProcessId"] == "geometry.buffer"


def test_cli_translate_emits_plan_and_evidence(tmp_path: Path, capsys) -> None:
    script = _write(tmp_path, "wf.py", SCRIPT)
    plan_out = tmp_path / "plan.json"
    evidence_out = tmp_path / "evidence.json"

    rc = main(["translate", str(script), "--output", str(plan_out), "--evidence", str(evidence_out)])

    assert rc == 0
    plan = json.loads(plan_out.read_text())
    # The OGC plan translates every supported call (buffer + erase); coverage
    # gating to job-executable tools is reported in the evidence, not by
    # dropping translations.
    assert [t["processId"] for t in plan["translations"]] == ["buffer", "erase"]

    evidence = json.loads(evidence_out.read_text())
    assert evidence["schema"] == "honua.migration.arcpy.parity-evidence/v1"
    assert evidence["summary"]["translatableCalls"] == 1
    assert evidence["summary"]["manualReviewCalls"] == 1
    assert evidence["summary"]["unsupportedCalls"] == 1

    captured = capsys.readouterr()
    assert "coverage:" in captured.err


def test_cli_run_dry_run_emits_only_job_executable_payloads(tmp_path: Path) -> None:
    script = _write(tmp_path, "wf.py", SCRIPT)
    out = tmp_path / "run.json"

    rc = main(["run", str(script), "--server", "http://example.test", "--dry-run", "--output", str(out)])

    assert rc == 0
    result = json.loads(out.read_text())
    assert result["dryRun"] is True
    # Only the job-executable Buffer is queued to run; Erase is skipped.
    assert [e["processId"] for e in result["executions"]] == ["buffer"]
    assert [e["jobProcessId"] for e in result["executions"]] == ["geometry.buffer"]
    assert "arcpy.analysis.Erase" in result["skipped"]


def test_cli_pyt_parses_toolbox(tmp_path: Path) -> None:
    toolbox = _write(tmp_path, "tb.pyt", PYT)
    out = tmp_path / "tb.json"
    evidence = tmp_path / "tb_evidence.json"

    rc = main(["pyt", str(toolbox), "--output", str(out), "--evidence", str(evidence)])

    assert rc == 0
    parsed = json.loads(out.read_text())
    assert parsed["label"] == "T"
    assert [t["className"] for t in parsed["tools"]] == ["A"]
    assert [x["processId"] for x in parsed["tools"][0]["plan"]["translations"]] == ["simplify"]

    agg = json.loads(evidence.read_text())
    assert agg["summary"]["coveragePercent"] == 100.0


def test_cli_pyt_binary_tbx_reports_stub(tmp_path: Path, capsys) -> None:
    binary = tmp_path / "legacy.tbx"
    binary.write_bytes(b"\x00binary\x00")

    rc = main(["pyt", str(binary)])

    assert rc == 3
    assert ".tbx" in capsys.readouterr().err


def _write_atbx(path: Path) -> Path:
    import io
    import zipfile

    model = {
        "name": "BufferModel",
        "processes": [
            {
                "toolName": "Buffer",
                "toolbox": "analysis",
                "parameters": {
                    "in_features": "a",
                    "out_feature_class": "b",
                    "buffer_distance_or_field": "5 Meters",
                },
            }
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("BufferModel.tool/tool.content", json.dumps(model))
    path.write_bytes(buffer.getvalue())
    return path


def test_cli_atbx_parses_models(tmp_path: Path, capsys) -> None:
    atbx = _write_atbx(tmp_path / "wf.atbx")
    evidence = tmp_path / "atbx-evidence.json"

    rc = main(["atbx", str(atbx), "--evidence", str(evidence)])

    assert rc == 0
    agg = json.loads(evidence.read_text())
    assert agg["schema"] == "honua.migration.arcpy.atbx-parity-evidence/v1"
    assert agg["summary"]["modelCount"] == 1
    assert agg["summary"]["translatableCalls"] == 1


def test_cli_atbx_rejects_binary_tbx(tmp_path: Path, capsys) -> None:
    tbx = tmp_path / "legacy.tbx"
    tbx.write_bytes(b"\x00binary\x00")

    rc = main(["atbx", str(tbx)])

    assert rc == 3
    assert "not clean-room parseable" in capsys.readouterr().err


def test_cli_gpservice_classifies_tasks(tmp_path: Path) -> None:
    service_def = {"tasks": ["Buffer", "MysteryTask"]}
    path = _write(tmp_path, "gpservice.json", json.dumps(service_def))
    evidence = tmp_path / "gp-evidence.json"

    rc = main(["gpservice", str(path), "--url", "https://x/GPServer", "--evidence", str(evidence)])

    assert rc == 0
    agg = json.loads(evidence.read_text())
    assert agg["schema"] == "honua.migration.arcpy.gp-service-parity-evidence/v1"
    assert agg["url"] == "https://x/GPServer"
    assert agg["summary"]["taskCount"] == 2
    assert agg["summary"]["translatableCalls"] == 1


def test_cli_run_executes_via_mock_transport(tmp_path: Path, monkeypatch) -> None:
    import httpx

    import honua_sdk
    from honua_sdk import HonuaClient

    script = _write(tmp_path, "wf.py", SCRIPT)
    out = tmp_path / "run.json"

    def handler(request: httpx.Request) -> httpx.Response:
        process_id = request.url.path.split("/")[-2]
        return httpx.Response(200, json={"processID": process_id, "status": "accepted"})

    def fake_client(base_url, *args, **kwargs):
        return HonuaClient(base_url, transport=httpx.MockTransport(handler))

    # The CLI imports HonuaClient lazily from the top-level package.
    monkeypatch.setattr(honua_sdk, "HonuaClient", fake_client)

    rc = main(["run", str(script), "--server", "http://example.test", "--output", str(out)])

    assert rc == 0
    result = json.loads(out.read_text())
    assert [e["processId"] for e in result["executions"]] == ["buffer"]
    assert result["executions"][0]["result"]["status"] == "accepted"
    assert "arcpy.analysis.Erase" in result["skipped"]


def test_cli_run_with_no_job_executable_calls_reports_skips(tmp_path: Path, capsys) -> None:
    script = _write(tmp_path, "manual.py", 'import arcpy\narcpy.analysis.Erase("a", "b", "c")\n')
    out = tmp_path / "run.json"

    rc = main(["run", str(script), "--server", "http://example.test", "--output", str(out)])

    assert rc == 0
    result = json.loads(out.read_text())
    assert result["executions"] == []
    assert "arcpy.analysis.Erase" in result["skipped"]
    assert "no translatable" in capsys.readouterr().err


def test_cli_scan_reports_syntax_error_exit_code(tmp_path: Path, capsys) -> None:
    script = _write(tmp_path, "bad.py", "import arcpy\narcpy.analysis.Buffer(")

    rc = main(["scan", str(script)])

    assert rc == 2
    assert "syntax error" in capsys.readouterr().err


def test_cli_translate_reports_syntax_error_and_emits_no_plan(tmp_path: Path, capsys) -> None:
    script = _write(tmp_path, "bad.py", "import arcpy\narcpy.analysis.Buffer(")
    plan_out = tmp_path / "plan.json"
    evidence_out = tmp_path / "evidence.json"

    rc = main(["translate", str(script), "--output", str(plan_out), "--evidence", str(evidence_out)])

    assert rc == 2
    captured = capsys.readouterr()
    assert "syntax error" in captured.err
    # On a syntax error no plan/evidence/coverage is emitted.
    assert not plan_out.exists()
    assert not evidence_out.exists()
    assert "coverage:" not in captured.err
    assert captured.out == ""


# ---------------------------------------------------------------------------
# Server attestation (honua-sdk-python#188)
# ---------------------------------------------------------------------------


def _attesting_admin_client(monkeypatch, handler):
    """Point the CLI's lazily-imported admin client at a MockTransport."""

    import httpx

    import honua_admin
    from honua_admin import HonuaAdminClient

    seen: dict = {}

    def fake_client(base_url, **kwargs):
        seen["base_url"] = base_url
        seen["api_key"] = kwargs.get("api_key")
        seen["timeout"] = kwargs.get("timeout")
        return HonuaAdminClient(base_url, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(honua_admin, "HonuaAdminClient", fake_client)
    return seen


def _report_for(request, classifications: dict[str, str] | None = None) -> dict:
    """Echo back a server report classifying every tool in the posted manifest."""

    manifest = json.loads(request.content.decode("utf-8"))
    overrides = classifications or {}
    return {
        "artifactKind": "honua.migration.toolbox-translation-report",
        "artifactVersion": "1.0",
        "toolboxName": manifest["toolboxName"],
        "sourceFormat": manifest["sourceFormat"],
        "summary": {},
        "tools": [
            {
                "toolName": tool["toolName"],
                "classification": overrides.get(tool["toolName"], "translated"),
                "processId": tool.get("targetProcessId"),
                "parameterBindings": [],
                "issues": [],
            }
            for tool in manifest["tools"]
        ],
    }


def test_cli_pyt_without_server_marks_the_report_local_only(tmp_path: Path, capsys) -> None:
    toolbox = _write(tmp_path, "tb.pyt", PYT)
    out = tmp_path / "tb.json"

    rc = main(["pyt", str(toolbox), "--output", str(out)])

    assert rc == 0
    attestation = json.loads(out.read_text())["attestation"]
    assert attestation["verdictSource"] == "local-only"
    assert attestation["attested"] is False
    assert attestation["fallbackReason"]
    assert "local-only (NOT server-attested)" in capsys.readouterr().err


def test_cli_pyt_with_server_emits_a_server_attested_report(tmp_path: Path, monkeypatch, capsys) -> None:
    import httpx

    toolbox = _write(tmp_path, "tb.pyt", PYT)
    out = tmp_path / "tb.json"
    attested_out = tmp_path / "attestation.json"
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=_report_for(request))

    seen = _attesting_admin_client(monkeypatch, handler)

    rc = main(
        [
            "pyt",
            str(toolbox),
            "--output",
            str(out),
            "--server",
            "http://honua.test",
            "--api-key",
            "admin-secret",
            "--attestation",
            str(attested_out),
        ]
    )

    assert rc == 0
    assert paths == ["/api/v1/admin/import/toolbox/translation/validate"]
    assert seen["base_url"] == "http://honua.test"
    assert seen["api_key"] == "admin-secret"

    attestation = json.loads(out.read_text())["attestation"]
    assert attestation["verdictSource"] == "server-attested"
    assert attestation["attested"] is True
    assert attestation["server"] == "http://honua.test"
    assert attestation["fallbackReason"] is None
    # The standalone attestation artifact matches the embedded one.
    assert json.loads(attested_out.read_text()) == attestation
    assert "server-attested by http://honua.test" in capsys.readouterr().err


def test_cli_api_key_falls_back_to_the_environment(tmp_path: Path, monkeypatch) -> None:
    import httpx

    toolbox = _write(tmp_path, "tb.pyt", PYT)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_report_for(request))

    seen = _attesting_admin_client(monkeypatch, handler)
    monkeypatch.setenv("HONUA_ADMIN_API_KEY", "from-env")

    rc = main(["pyt", str(toolbox), "--output", str(tmp_path / "tb.json"), "--server", "http://honua.test"])

    assert rc == 0
    assert seen["api_key"] == "from-env"


def test_cli_surfaces_a_server_vs_local_disagreement(tmp_path: Path, monkeypatch, capsys) -> None:
    import httpx

    toolbox = _write(tmp_path, "tb.pyt", PYT)
    out = tmp_path / "tb.json"

    def handler(request: httpx.Request) -> httpx.Response:
        # The SDK classified tool A as translatable; the catalog disagrees.
        return httpx.Response(200, json=_report_for(request, {"A": "unsupported"}))

    _attesting_admin_client(monkeypatch, handler)

    rc = main(["pyt", str(toolbox), "--output", str(out), "--server", "http://honua.test"])

    assert rc == 0
    attestation = json.loads(out.read_text())["attestation"]
    assert attestation["summary"]["disagreementCount"] == 1
    assert attestation["disagreements"] == [{"toolName": "A", "local": "translated", "server": "unsupported"}]
    # The server's verdict is the effective one.
    assert attestation["tools"][0]["classification"] == "unsupported"
    assert attestation["tools"][0]["localClassification"] == "translated"
    assert "disagreement: A local=translated server=unsupported (server wins)" in capsys.readouterr().err


def test_cli_unreachable_server_degrades_to_local_only(tmp_path: Path, monkeypatch, capsys) -> None:
    import httpx

    toolbox = _write(tmp_path, "tb.pyt", PYT)
    out = tmp_path / "tb.json"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _attesting_admin_client(monkeypatch, handler)

    rc = main(["pyt", str(toolbox), "--output", str(out), "--server", "http://offline.test"])

    # An unreachable server is not a hard failure: the local report still emits.
    assert rc == 0
    attestation = json.loads(out.read_text())["attestation"]
    assert attestation["attested"] is False
    assert attestation["verdictSource"] == "local-only"
    assert "connection refused" in attestation["fallbackReason"]
    assert attestation["tools"][0]["classification"] == "translated"
    assert "local-only (NOT server-attested)" in capsys.readouterr().err


def test_cli_unauthorized_call_never_claims_attestation(tmp_path: Path, monkeypatch, capsys) -> None:
    import httpx

    toolbox = _write(tmp_path, "tb.pyt", PYT)
    out = tmp_path / "tb.json"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Unauthorized"})

    _attesting_admin_client(monkeypatch, handler)

    rc = main(["pyt", str(toolbox), "--output", str(out), "--server", "http://honua.test"])

    assert rc == 0
    attestation = json.loads(out.read_text())["attestation"]
    assert attestation["attested"] is False
    assert attestation["verdictSource"] == "local-only"
    assert attestation["fallbackReason"]
    assert all(tool["serverClassification"] is None for tool in attestation["tools"])
    assert "local-only (NOT server-attested)" in capsys.readouterr().err


def test_cli_require_attested_fails_when_the_call_is_refused(tmp_path: Path, monkeypatch, capsys) -> None:
    import httpx

    from honua_sdk.migration._cli import EXIT_NOT_ATTESTED

    toolbox = _write(tmp_path, "tb.pyt", PYT)
    out = tmp_path / "tb.json"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "Forbidden"})

    _attesting_admin_client(monkeypatch, handler)

    rc = main(
        ["pyt", str(toolbox), "--output", str(out), "--server", "http://honua.test", "--require-attested"]
    )

    assert rc == EXIT_NOT_ATTESTED
    assert "--require-attested" in capsys.readouterr().err
    # The report is still written, marked local-only, so the failure is diagnosable.
    assert json.loads(out.read_text())["attestation"]["attested"] is False


def test_cli_require_attested_offline_fails_without_contacting_a_server(tmp_path: Path) -> None:
    from honua_sdk.migration._cli import EXIT_NOT_ATTESTED

    toolbox = _write(tmp_path, "tb.pyt", PYT)

    rc = main(["pyt", str(toolbox), "--output", str(tmp_path / "tb.json"), "--require-attested"])

    assert rc == EXIT_NOT_ATTESTED


def test_cli_attestation_degrades_when_honua_admin_is_not_installed(tmp_path: Path, monkeypatch, capsys) -> None:
    import builtins

    toolbox = _write(tmp_path, "tb.pyt", PYT)
    out = tmp_path / "tb.json"
    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "honua_admin":
            raise ImportError("No module named 'honua_admin'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    rc = main(["pyt", str(toolbox), "--output", str(out), "--server", "http://honua.test"])

    # honua-admin is an optional dependency: without it the toolbox still
    # translates, it just cannot be attested.
    assert rc == 0
    attestation = json.loads(out.read_text())["attestation"]
    assert attestation["attested"] is False
    assert "honua_admin" in attestation["fallbackReason"]


def test_cli_atbx_with_server_attests_model_steps(tmp_path: Path, monkeypatch) -> None:
    import httpx

    atbx = _write_atbx(tmp_path / "wf.atbx")
    out = tmp_path / "wf.json"
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json=_report_for(request))

    _attesting_admin_client(monkeypatch, handler)

    rc = main(["atbx", str(atbx), "--output", str(out), "--server", "http://honua.test"])

    assert rc == 0
    assert bodies[0]["sourceFormat"] == "atbx"
    assert [tool["toolName"] for tool in bodies[0]["tools"]] == ["BufferModel"]
    assert bodies[0]["tools"][0]["targetProcessId"] == "geometry.buffer"
    assert json.loads(out.read_text())["attestation"]["verdictSource"] == "server-attested"


def test_cli_translate_routes_a_pyt_toolbox_through_attestation(tmp_path: Path, monkeypatch) -> None:
    import httpx

    toolbox = _write(tmp_path, "tb.pyt", PYT)
    out = tmp_path / "tb.json"
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json=_report_for(request))

    _attesting_admin_client(monkeypatch, handler)

    rc = main(["translate", str(toolbox), "--output", str(out), "--server", "http://honua.test"])

    assert rc == 0
    assert bodies[0]["sourceFormat"] == "pyt"
    document = json.loads(out.read_text())
    assert document["attestation"]["verdictSource"] == "server-attested"
    # The submitted manifest travels with the plan so the report is reproducible.
    assert document["translationManifest"]["artifactKind"] == "honua.migration.toolbox-translation"


def test_cli_translate_rejects_attesting_a_bare_arcpy_script(tmp_path: Path, capsys) -> None:
    script = _write(tmp_path, "wf.py", SCRIPT)

    rc = main(["translate", str(script), "--server", "http://honua.test"])

    # Refusing beats inventing a toolbox source format the server would reject.
    assert rc == 2
    assert "is a script rather than a toolbox" in capsys.readouterr().err


def test_cli_translate_of_a_binary_tbx_gives_export_instructions(tmp_path: Path, capsys) -> None:
    binary = tmp_path / "legacy.tbx"
    binary.write_bytes(b"\x00binary\x00")

    rc = main(["translate", str(binary)])

    assert rc == 3
    err = capsys.readouterr().err
    # The refusal is policy, so it has to read as a migration instruction.
    assert "Export the toolbox to an open format first" in err
    assert "New ArcGIS Toolbox (.atbx)" in err
    assert "deliberately never parsed" in err
