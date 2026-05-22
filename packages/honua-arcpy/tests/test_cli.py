"""``honua-arcpy assess`` and ``honua-arcpy matrix`` CLI."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from honua_arcpy._cli import (
    assess_inventory,
    main,
    render_assessment,
    render_compat_matrix,
)


SAMPLE_INVENTORY = {
    "toolCalls": [
        {"call": "arcpy.analysis.Buffer", "tool": "Buffer", "toolbox": "analysis"},
        {"call": "arcpy.analysis.Buffer", "tool": "Buffer", "toolbox": "analysis"},
        {"call": "arcpy.management.SelectLayerByLocation", "tool": "SelectLayerByLocation", "toolbox": "management"},
        {"call": "arcpy.sa.Slope", "tool": "Slope", "toolbox": "sa"},
        {"call": "arcpy.da.SearchCursor", "tool": "SearchCursor", "toolbox": "da"},
    ]
}


def test_assess_inventory_buckets_supported_stub_and_out_of_scope() -> None:
    rows = assess_inventory(SAMPLE_INVENTORY)
    statuses = {row.qualified_name: (row.status, row.occurrences) for row in rows}
    assert statuses["analysis.Buffer"] == ("supported", 2)
    assert statuses["management.SelectLayerByLocation"] == ("stub", 1)
    assert statuses["sa.Slope"] == ("out-of-scope", 1)
    assert statuses["da.SearchCursor"] == ("supported", 1)


def test_render_assessment_prints_buckets() -> None:
    rows = assess_inventory(SAMPLE_INVENTORY)
    text = render_assessment(rows)
    assert "Supported" in text
    assert "analysis.Buffer" in text
    assert "SelectLayerByLocation" in text
    assert "Out of MVP scope" in text


def test_assess_cli_writes_machine_readable_file(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(SAMPLE_INVENTORY), encoding="utf-8")

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main(["assess", str(inventory_path)])
    assert exit_code == 0
    assert "analysis.Buffer" in buf.getvalue()

    machine = json.loads((tmp_path / "honua-arcpy-assessment.json").read_text(encoding="utf-8"))
    summary = machine["summary"]
    assert summary["supported"] >= 2
    assert summary["stub"] >= 1
    assert summary["out-of-scope"] >= 1


def test_matrix_renders_and_check_detects_drift(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.md"
    assert main(["matrix", "--output", str(matrix_path)]) == 0
    content = matrix_path.read_text(encoding="utf-8")
    assert "## arcpy.analysis.*" in content
    assert "## arcpy.management.*" in content
    assert "## arcpy.da.*" in content

    # Check drift: matrix matches itself
    assert main(["matrix", "--output", str(matrix_path), "--check", str(matrix_path)]) == 0

    # Mutate and expect drift detection
    matrix_path.write_text(content + "\n# drift", encoding="utf-8")
    assert main(["matrix", "--check", str(matrix_path)]) == 1


def test_render_compat_matrix_contains_anchors() -> None:
    text = render_compat_matrix()
    assert "<a id=\"analysisbuffer\"></a>" in text
    assert "<a id=\"dasearchcursor\"></a>" in text


def test_assess_inventory_accepts_sdk_migration_scan_report_calls_key() -> None:
    """The honua_sdk.migration.scan_arcpy_source(...).to_dict() report stores
    its entries under the top-level ``calls`` key (vs. honua_admin's
    ``toolCalls`` / ``tool_calls``). ``assess_inventory`` must accept both."""

    from honua_sdk.migration import scan_arcpy_source

    report = scan_arcpy_source(
        "import arcpy\n"
        "arcpy.analysis.Buffer('roads', 'roads_buffer', '25 Meters')\n"
        "arcpy.management.SelectLayerByLocation('roads', 'INTERSECT', 'parcels')\n"
    )
    rows = assess_inventory(report.to_dict())
    statuses = {row.qualified_name: (row.status, row.occurrences) for row in rows}
    assert statuses["analysis.Buffer"] == ("supported", 1)
    assert statuses["management.SelectLayerByLocation"] == ("stub", 1)


def test_assess_inventory_accepts_minimal_sdk_calls_shape() -> None:
    """A hand-rolled SDK-shape payload (``calls`` + ``qualifiedName``)
    must classify cleanly, since the SDK scan report is one of the two
    documented assess inputs."""

    rows = assess_inventory(
        {
            "calls": [
                {
                    "qualifiedName": "arcpy.analysis.Buffer",
                    "family": "analysis",
                    "tool": "Buffer",
                },
                {
                    "qualifiedName": "arcpy.management.SelectLayerByLocation",
                    "family": "management",
                    "tool": "SelectLayerByLocation",
                },
            ]
        }
    )
    statuses = {row.qualified_name: row.status for row in rows}
    assert statuses["analysis.Buffer"] == "supported"
    assert statuses["management.SelectLayerByLocation"] == "stub"
