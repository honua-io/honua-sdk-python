"""Smoke tests for the eval harness itself."""

from __future__ import annotations

from pathlib import Path

import pytest

from honua_arcpy._cli import render_compat_matrix


_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


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
