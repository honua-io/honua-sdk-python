"""Compatibility manifest invariants."""

from __future__ import annotations

import honua_arcpy
from honua_arcpy._compat import COMPAT


def test_manifest_covers_45_functions_across_three_families() -> None:
    families = {"analysis": 0, "management": 0, "da": 0}
    for name in COMPAT:
        family = name.split(".", 1)[0]
        assert family in families, f"Unexpected family {family!r}"
        families[family] += 1
    assert families == {"analysis": 15, "management": 20, "da": 10}
    assert len(COMPAT) == 45


def test_every_manifest_entry_has_backend_and_status() -> None:
    valid_backends = {"process", "source", "admin", "session", "not_implemented"}
    valid_statuses = {"supported", "partial", "stub"}
    for name, entry in COMPAT.items():
        assert entry.backend in valid_backends, f"{name}: bad backend {entry.backend!r}"
        assert entry.status in valid_statuses, f"{name}: bad status {entry.status!r}"


def test_process_entries_carry_process_id() -> None:
    for name, entry in COMPAT.items():
        if entry.backend == "process":
            assert entry.process_id, f"{name}: process backend missing process_id"


def test_stub_entries_carry_replacement_hint_and_tracking() -> None:
    for name, entry in COMPAT.items():
        if entry.status == "stub":
            assert entry.replacement_hint, f"{name}: stub missing replacement_hint"
            assert entry.tracking, f"{name}: stub missing tracking"


def test_public_top_level_reexports_exist() -> None:
    expected = {
        "configure",
        "configure_from_env",
        "analysis",
        "management",
        "da",
        "env",
        "ExecuteError",
        "HonuaArcpyUnsupportedError",
        "HonuaArcpyConfigurationError",
        "Describe",
        "DescribeResult",
        "FieldDescribe",
        "Selection",
        "GetCount",
        "COMPAT",
    }
    missing = expected - set(dir(honua_arcpy))
    assert not missing, f"Missing top-level exports: {sorted(missing)}"
