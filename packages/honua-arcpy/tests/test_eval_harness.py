"""Smoke tests for the eval harness itself."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from honua_arcpy._cli import render_compat_matrix


_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_EVAL_ROOT = _PACKAGE_ROOT / "eval"
if str(_EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(_EVAL_ROOT))


def test_eval_scripts_directory_contains_50_scripts() -> None:
    scripts = sorted(_PACKAGE_ROOT.glob("eval/scripts/*.py"))
    assert len(scripts) == 50, f"Expected 50 scripts, found {len(scripts)}"


def test_eval_scripts_pair_with_golden_records() -> None:
    scripts = sorted(_PACKAGE_ROOT.glob("eval/scripts/*.py"))
    for script in scripts:
        golden = _PACKAGE_ROOT / "eval" / "golden" / f"{script.stem}.json"
        assert golden.exists(), f"Missing golden file for {script.name}"


def test_committed_matrix_matches_generated_output() -> None:
    committed = (_PACKAGE_ROOT / "docs" / "compatibility-matrix.md").read_text(encoding="utf-8")
    generated = render_compat_matrix()
    assert committed == generated, (
        "Compatibility matrix is out of sync; re-run `python scripts/render_compat_matrix.py`."
    )


def test_top_level_workspace_matrix_matches_package_matrix() -> None:
    package_matrix = (_PACKAGE_ROOT / "docs" / "compatibility-matrix.md").read_text(encoding="utf-8")
    workspace_matrix_path = _PACKAGE_ROOT.parent.parent / "docs" / "honua-arcpy" / "compatibility-matrix.md"
    if not workspace_matrix_path.exists():
        pytest.skip("workspace-level matrix not present (legacy layout)")
    assert workspace_matrix_path.read_text(encoding="utf-8") == package_matrix, (
        "Top-level docs/honua-arcpy/compatibility-matrix.md drifted from the package copy."
    )


def test_classify_expected_failure_honours_golden_audit_lines(tmp_path: Path) -> None:
    """An expected_failure script that emits the wrong number of audit lines
    must fail eval, not silently pass. Previously ``_classify`` accepted any
    audit count inside the expected_failure branch, so a regression that
    dropped the refusal-time audit line was invisible."""

    from run_eval import _classify

    script = tmp_path / "expected_failure_widget.py"
    script.write_text("", encoding="utf-8")

    matching_golden = {
        "audit_lines": 1,
        "expected_failure": True,
        "stdout_contains": "expected_failure_widget",
    }
    status, expected_failure, reason = _classify(
        script,
        exit_code=0,
        audit_lines=1,
        golden=matching_golden,
        stdout="expected_failure_widget caught analysis.Widget\n",
        stderr="",
    )
    assert status == "pass"
    assert expected_failure is True
    assert reason == "caught expected unsupported error"

    # Same golden, but the script actually wrote 0 audit lines (regression).
    status, expected_failure, reason = _classify(
        script,
        exit_code=0,
        audit_lines=0,
        golden=matching_golden,
        stdout="expected_failure_widget caught analysis.Widget\n",
        stderr="",
    )
    assert status == "fail"
    assert expected_failure is True
    assert reason is not None and "audit line count" in reason


def test_run_script_always_rebuilds_pythonpath_when_host_sets_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``_run_script`` must always append the sibling-package paths to
    ``PYTHONPATH`` -- previously it used ``env.setdefault(...)``, which
    left a host-provided PYTHONPATH untouched so eval scripts on CI / shell
    hosts with PYTHONPATH already set could fail to import
    ``honua_arcpy`` / ``honua_sdk`` / ``honua_admin``.
    """

    import subprocess
    from run_eval import _build_pythonpath, _run_script

    monkeypatch.setenv("PYTHONPATH", "/host/preexisting")

    captured: dict[str, str] = {}

    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, *, capture_output, text, env, timeout, check):  # type: ignore[no-untyped-def]
        captured["pythonpath"] = env["PYTHONPATH"]
        return _FakeResult()

    monkeypatch.setattr(subprocess, "run", fake_run)

    script = tmp_path / "noop_eval.py"
    script.write_text("", encoding="utf-8")
    audit_root = tmp_path / "audit"
    audit_root.mkdir()

    _run_script(script, audit_root=audit_root, timeout=5.0)

    rebuilt = _build_pythonpath("/host/preexisting")
    assert captured["pythonpath"] == rebuilt, (
        "Host-provided PYTHONPATH was not augmented with the eval-package extras"
    )
    parts = captured["pythonpath"].split(os.pathsep)
    assert "/host/preexisting" in parts, "Existing PYTHONPATH entry must be preserved"
    assert str(_PACKAGE_ROOT) in parts, "honua-arcpy package path must be appended"


def test_run_script_builds_pythonpath_when_host_has_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When no PYTHONPATH is set on the host, ``_run_script`` must still
    seed it with the sibling-package paths so the subprocess can import the
    workspace packages."""

    import subprocess
    from run_eval import _run_script

    monkeypatch.delenv("PYTHONPATH", raising=False)

    captured: dict[str, str] = {}

    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, *, capture_output, text, env, timeout, check):  # type: ignore[no-untyped-def]
        captured["pythonpath"] = env["PYTHONPATH"]
        return _FakeResult()

    monkeypatch.setattr(subprocess, "run", fake_run)

    script = tmp_path / "noop_eval.py"
    script.write_text("", encoding="utf-8")
    audit_root = tmp_path / "audit"
    audit_root.mkdir()

    _run_script(script, audit_root=audit_root, timeout=5.0)

    parts = captured["pythonpath"].split(os.pathsep)
    assert str(_PACKAGE_ROOT) in parts
