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
        {"call": "arcpy.analysis.Clip", "tool": "Clip", "toolbox": "analysis"},
        {"call": "arcpy.analysis.Clip", "tool": "Clip", "toolbox": "analysis"},
        {"call": "arcpy.analysis.Buffer", "tool": "Buffer", "toolbox": "analysis"},
        {"call": "arcpy.management.SelectLayerByLocation", "tool": "SelectLayerByLocation", "toolbox": "management"},
        {"call": "arcpy.management.MakeFeatureLayer", "tool": "MakeFeatureLayer", "toolbox": "management"},
        {"call": "arcpy.sa.Slope", "tool": "Slope", "toolbox": "sa"},
        {"call": "arcpy.da.SearchCursor", "tool": "SearchCursor", "toolbox": "da"},
    ]
}


def test_assess_inventory_buckets_supported_stub_and_out_of_scope() -> None:
    rows = assess_inventory(SAMPLE_INVENTORY)
    statuses = {row.qualified_name: (row.status, row.occurrences) for row in rows}
    # ``analysis.Clip`` is an honest stub: honua-server only exposes the
    # single-WKB ``geometry.clip`` op, with no layer-aware counterpart, so
    # the layer-projection adapter cannot promote it. ``analysis.Buffer`` is
    # now supported via the layer-aware analytics.buffer-aggregate projection.
    assert statuses["analysis.Clip"] == ("stub", 2)
    assert statuses["analysis.Buffer"] == ("supported", 1)
    assert statuses["management.SelectLayerByLocation"] == ("stub", 1)
    assert statuses["management.MakeFeatureLayer"] == ("supported", 1)
    assert statuses["sa.Slope"] == ("out-of-scope", 1)
    assert statuses["da.SearchCursor"] == ("partial", 1)


def test_render_assessment_prints_buckets() -> None:
    rows = assess_inventory(SAMPLE_INVENTORY)
    text = render_assessment(rows)
    assert "Supported" in text
    assert "Partial" in text
    assert "analysis.Clip" in text
    assert "SelectLayerByLocation" in text
    assert "Out of MVP scope" in text


def test_assess_cli_writes_machine_readable_file(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(SAMPLE_INVENTORY), encoding="utf-8")

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main(["assess", str(inventory_path)])
    assert exit_code == 0
    assert "analysis.Clip" in buf.getvalue()

    machine = json.loads((tmp_path / "honua-arcpy-assessment.json").read_text(encoding="utf-8"))
    summary = machine["summary"]
    # MakeFeatureLayer + Buffer are supported, SearchCursor is partial, Clip +
    # SelectLayerByLocation are stubs, and Slope is out-of-scope.
    assert summary["supported"] >= 1
    assert summary["partial"] >= 1
    assert summary["stub"] >= 2
    assert summary["out-of-scope"] >= 1


def test_assess_cli_creates_output_dir(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(SAMPLE_INVENTORY), encoding="utf-8")
    output_dir = tmp_path / "missing" / "nested"

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main(["assess", str(inventory_path), "--output-dir", str(output_dir)])

    assert exit_code == 0
    assert (output_dir / "honua-arcpy-assessment.json").exists()


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


def test_matrix_check_runs_before_output_so_same_path_cannot_mask_drift(tmp_path: Path) -> None:
    """A caller pointing both --output and --check at the same drifted file
    must still get a non-zero exit. Previously ``_matrix()`` wrote the
    fresh-rendered text first and then compared it against itself, so the
    CI drift gate always reported success regardless of committed drift."""

    matrix_path = tmp_path / "matrix.md"
    matrix_path.write_text("stale committed content\n", encoding="utf-8")

    exit_code = main(["matrix", "--output", str(matrix_path), "--check", str(matrix_path)])
    assert exit_code == 1
    # The drifted file must not have been overwritten with the rendered
    # text, otherwise re-running --check would silently pass on the next
    # invocation and hide whatever the committed file used to contain.
    assert matrix_path.read_text(encoding="utf-8") == "stale committed content\n"


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
        "arcpy.analysis.Clip('roads', 'study', 'roads_clip')\n"
        "arcpy.management.SelectLayerByLocation('roads', 'INTERSECT', 'parcels')\n"
    )
    rows = assess_inventory(report.to_dict())
    statuses = {row.qualified_name: (row.status, row.occurrences) for row in rows}
    # ``analysis.Clip`` stays a stub (no layer-aware honua-server op).
    assert statuses["analysis.Clip"] == ("stub", 1)
    assert statuses["management.SelectLayerByLocation"] == ("stub", 1)


def test_assess_inventory_accepts_minimal_sdk_calls_shape() -> None:
    """A hand-rolled SDK-shape payload (``calls`` + ``qualifiedName``)
    must classify cleanly, since the SDK scan report is one of the two
    documented assess inputs."""

    rows = assess_inventory(
        {
            "calls": [
                {
                    "qualifiedName": "arcpy.analysis.Clip",
                    "family": "analysis",
                    "tool": "Clip",
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
    # Both stay stubs: Clip has no layer-aware honua-server op, and
    # SelectLayerByLocation has no spatial-select process.
    assert statuses["analysis.Clip"] == "stub"
    assert statuses["management.SelectLayerByLocation"] == "stub"


def test_assess_inventory_canonicalizes_copy_features_to_manifest_row() -> None:
    """``arcpy.management.CopyFeatures`` is the SDK scanner's name for the
    same operation the shim exposes as ``management.Copy``; the shim itself
    exports ``CopyFeatures = Copy``. ``assess`` must report scans of
    ``CopyFeatures`` against the canonical manifest row instead of dropping
    them into the out-of-scope bucket because COMPAT only keys
    ``management.Copy``."""

    sdk_payload = {
        "calls": [
            {
                "qualifiedName": "arcpy.management.CopyFeatures",
                "family": "management",
                "tool": "CopyFeatures",
            },
        ]
    }
    rows = assess_inventory(sdk_payload)
    assert len(rows) == 1
    assert rows[0].qualified_name == "management.Copy"
    # The canonical ``management.Copy`` entry is now supported (layer-aware
    # data-management.copy-features projection); the canonicalization
    # invariant is independent of the bucket -- what matters is that
    # CopyFeatures maps to the same manifest row instead of dropping into
    # out-of-scope.
    assert rows[0].status == "supported"
    assert rows[0].occurrences == 1

    admin_payload = {
        "toolCalls": [
            {
                "call": "arcpy.management.CopyFeatures",
                "tool": "CopyFeatures",
                "toolbox": "management",
            },
        ]
    }
    rows = assess_inventory(admin_payload)
    assert len(rows) == 1
    assert rows[0].qualified_name == "management.Copy"
    assert rows[0].status == "supported"


def test_assess_inventory_combines_copy_and_copy_features_occurrences() -> None:
    """When a scan reports both ``Copy`` and ``CopyFeatures`` calls, they
    should aggregate under ``management.Copy`` so the assessment surfaces a
    single canonical row with the combined occurrence count."""

    rows = assess_inventory(
        {
            "calls": [
                {"qualifiedName": "arcpy.management.Copy", "family": "management", "tool": "Copy"},
                {"qualifiedName": "arcpy.management.CopyFeatures", "family": "management", "tool": "CopyFeatures"},
                {"qualifiedName": "arcpy.management.CopyFeatures", "family": "management", "tool": "CopyFeatures"},
            ]
        }
    )
    assert len(rows) == 1
    assert rows[0].qualified_name == "management.Copy"
    # Same canonicalization invariant as above; today's bucket is supported.
    assert rows[0].status == "supported"
    assert rows[0].occurrences == 3
