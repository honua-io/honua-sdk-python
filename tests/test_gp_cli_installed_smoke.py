"""Subprocess smoke against a real, separately installed ``honua-gp-devkit``.

The engine is never bundled with the SDK. These tests run only when
``HONUA_GP_CLI`` names an executable or ``honua-gp-devkit`` is on PATH; the
missing-engine case needs no engine and always runs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

_PRODUCT_CLI = [sys.executable, "-m", "honua_sdk.cli"]


def _engine() -> str | None:
    configured = os.environ.get("HONUA_GP_CLI", "").strip()
    return shutil.which(configured) if configured else shutil.which("honua-gp-devkit")


needs_engine = pytest.mark.skipif(_engine() is None, reason="no installed honua-gp-devkit (set HONUA_GP_CLI)")


def _run(args: list[str], **env: str) -> subprocess.CompletedProcess[str]:
    merged = {**os.environ, **env}
    # argv is fixed test input plus the engine path resolved from the test environment.
    return subprocess.run(args, capture_output=True, text=True, env=merged, timeout=300, check=False)  # noqa: S603


@needs_engine
def test_installed_engine_doctor_json_passes_through() -> None:
    result = _run([*_PRODUCT_CLI, "gp", "doctor", "--managed-only", "--json"])
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert isinstance(report, dict) and report


@needs_engine
def test_installed_engine_output_and_exit_code_match_direct_invocation() -> None:
    engine = _engine()
    assert engine is not None
    for args in (["list", "--json"], ["describe", "no such tool", "--json"]):
        via_product = _run([*_PRODUCT_CLI, "gp", *args])
        direct = _run([engine, *args])
        assert via_product.returncode == direct.returncode, (via_product.stderr, direct.stderr)
        assert via_product.stdout == direct.stdout
    failing = _run([*_PRODUCT_CLI, "gp", "describe", "no such tool", "--json"])
    assert failing.returncode != 0
    assert "no such tool" in failing.stdout + failing.stderr


@needs_engine
def test_installed_engine_honours_explicit_executable_path() -> None:
    engine = _engine()
    assert engine is not None
    result = _run([*_PRODUCT_CLI, "gp", "list", "--json"], HONUA_GP_CLI=engine, PATH="/nonexistent")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)


def test_missing_engine_returns_127_with_installation_guidance(tmp_path) -> None:
    result = _run([*_PRODUCT_CLI, "gp", "list"], HONUA_GP_CLI=str(tmp_path / "honua-gp-devkit"), PATH=str(tmp_path))
    assert result.returncode == 127
    assert "honua-gp-devkit" in result.stderr
    assert "HONUA_GP_CLI" in result.stderr
    assert result.stdout == ""
