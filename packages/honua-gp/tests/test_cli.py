"""Tests for the compatibility-matrix CLI."""

from __future__ import annotations

from pathlib import Path

from honua_gp._cli import main, render_compat_matrix


def test_matrix_renders_and_check_detects_drift(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.md"
    assert main(["matrix", "--output", str(matrix_path)]) == 0
    content = matrix_path.read_text(encoding="utf-8")
    assert "## gp.analysis.*" in content
    assert "## gp.management.*" in content
    assert "## gp.da.*" in content
    assert main(["matrix", "--output", str(matrix_path), "--check", str(matrix_path)]) == 0
    matrix_path.write_text(content + "\n# drift", encoding="utf-8")
    assert main(["matrix", "--check", str(matrix_path)]) == 1


def test_matrix_check_runs_before_output_so_same_path_cannot_mask_drift(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.md"
    matrix_path.write_text("stale committed content\n", encoding="utf-8")
    exit_code = main(["matrix", "--output", str(matrix_path), "--check", str(matrix_path)])
    assert exit_code == 1
    assert matrix_path.read_text(encoding="utf-8") == "stale committed content\n"


def test_render_compat_matrix_contains_anchors() -> None:
    text = render_compat_matrix()
    assert '<a id="analysisbuffer"></a>' in text
    assert '<a id="dasearchcursor"></a>' in text
