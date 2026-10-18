"""honua-release#233: the runtime server floor is a declaration of the capability baseline.

`release/sdk-capability-baseline.json` is what the release lock reads; the constant the
client enforces, the server matrix the compatibility gate replays and the documented
baseline must say the same thing, so no two sources of the minimum server can disagree.
"""

from __future__ import annotations

import json
from pathlib import Path

from honua_admin import MINIMUM_SUPPORTED_SERVER_VERSION, AdminCompatibilityBaseline

ROOT = Path(__file__).resolve().parents[2]
# honua-release docs/SDK-SERVER-BASELINE-RULE.md "Runtime floor constants": a first-release
# baseline maps to the least SemVer identity of the first server release line.
FIRST_RELEASE_RUNTIME_FLOOR = "2026.1.0-0"


def _derived_floor() -> str:
    baseline = json.loads((ROOT / "release" / "sdk-capability-baseline.json").read_text(encoding="utf-8"))
    declared = baseline["minimumServerVersion"]
    return FIRST_RELEASE_RUNTIME_FLOOR if declared == "first-release" else declared


def test_runtime_floor_is_derived_from_the_capability_baseline() -> None:
    assert MINIMUM_SUPPORTED_SERVER_VERSION == _derived_floor()
    assert AdminCompatibilityBaseline().minimum_server_version == _derived_floor()


def test_server_matrix_replays_the_derived_floor() -> None:
    matrix = json.loads((ROOT / "compatibility" / "server-matrix.json").read_text(encoding="utf-8"))
    assert matrix["baseline"]["minimumServerVersion"] == _derived_floor()


def test_documented_baseline_is_the_derived_floor() -> None:
    policy = (ROOT / "docs" / "compatibility.md").read_text(encoding="utf-8")
    assert f"`serverVersion` parses to at least `{_derived_floor()}`." in policy
