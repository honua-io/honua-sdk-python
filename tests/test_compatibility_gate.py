"""Tests for the repository compatibility gate."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "scripts" / "compatibility_gate.py"
SPEC = importlib.util.spec_from_file_location("compatibility_gate", GATE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
compatibility_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compatibility_gate)


def test_public_api_snapshot_is_current() -> None:
    assert compatibility_gate.check_public_api_snapshot(compatibility_gate.API_SNAPSHOT_PATH) == []


def test_public_api_snapshot_detects_removed_export(tmp_path: Path) -> None:
    snapshot = compatibility_gate.collect_public_api_surface()
    snapshot["modules"]["honua_sdk"]["exports"].remove("HonuaClient")

    snapshot_path = tmp_path / "public-api.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    failures = compatibility_gate.check_public_api_snapshot(snapshot_path)

    assert any("Public API snapshot drift detected" in failure for failure in failures)
    assert any("HonuaClient" in failure for failure in failures)


def test_server_matrix_is_valid() -> None:
    assert compatibility_gate.check_server_matrix(compatibility_gate.MATRIX_PATH) == []


def test_server_matrix_rejects_baseline_drift(tmp_path: Path) -> None:
    matrix = json.loads(compatibility_gate.MATRIX_PATH.read_text(encoding="utf-8"))
    matrix["baseline"]["minimumServerVersion"] = "1900.1.1"

    matrix_path = tmp_path / "server-matrix.json"
    matrix_path.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    failures = compatibility_gate.check_server_matrix(matrix_path)

    assert any("baseline does not match" in failure for failure in failures)
