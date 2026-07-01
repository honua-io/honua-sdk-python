"""Guard that the intra-file sync/async twins stay in lockstep.

AUD-160/161 (issue #129): ``scripts/gen_sync.py`` fully generates the async→sync
*file-pair* mirrors, but the protocol / source / ogc / workflow / geoprocessing
facades keep a hand-written sync class next to its ``Async`` twin *inside a
single module*. Those twins are not whole-file generated (a few methods diverge
in their bodies beyond the mechanical transform), so they can silently drift in
their public surface — a method or parameter added to one twin but not the
other.

``gen_sync.check_twins()`` verifies the twin pairs expose the same method
surface; these tests wire it into the pytest gate and additionally fail CI if a
new ``Async*`` twin class is added to a covered module without being registered
in ``gen_sync.TWIN_TARGETS`` (so it cannot escape the parity guard).
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN_SYNC_PATH = ROOT / "scripts" / "gen_sync.py"

SPEC = importlib.util.spec_from_file_location("gen_sync", GEN_SYNC_PATH)
assert SPEC is not None
assert SPEC.loader is not None
gen_sync = importlib.util.module_from_spec(SPEC)
sys.modules["gen_sync"] = gen_sync
SPEC.loader.exec_module(gen_sync)

SDK_ROOT = ROOT / "packages" / "honua-sdk" / "honua_sdk"

# Modules where every ``Async*`` twin class must be registered in TWIN_TARGETS.
# The protocol package is the main extension point for new protocol clients;
# the four facades below each host a sync/async twin pair as well.
_SCANNED_FILES = [
    *sorted((SDK_ROOT / "protocols").glob("*.py")),
    SDK_ROOT / "source.py",
    SDK_ROOT / "ogc.py",
    SDK_ROOT / "workflow.py",
    SDK_ROOT / "geoprocessing.py",
]


def _async_twin_classes(path: Path) -> set[str]:
    """Top-level classes whose name starts with ``Async`` / ``_Async``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and (node.name.startswith("Async") or node.name.startswith("_Async"))
    }


def test_twins_are_in_lockstep() -> None:
    problems = gen_sync.check_twins()
    assert not problems, "sync/async twin drift:\n" + "\n".join(problems)


def test_every_async_twin_is_registered() -> None:
    registered: set[str] = {
        async_name for twin in gen_sync.TWIN_TARGETS for async_name, _ in twin.pairs
    }
    missing: dict[str, set[str]] = {}
    for path in _SCANNED_FILES:
        if not path.exists():
            continue
        unregistered = _async_twin_classes(path) - registered
        if unregistered:
            missing[str(path.relative_to(ROOT))] = unregistered
    assert not missing, (
        "async twin class(es) not registered in scripts/gen_sync.py TWIN_TARGETS "
        "(they would escape the twin parity guard): "
        f"{ {k: sorted(v) for k, v in missing.items()} }"
    )


def test_all_twin_targets_point_at_existing_files() -> None:
    for twin in gen_sync.TWIN_TARGETS:
        assert twin.source.exists(), f"missing twin source: {twin.source_rel}"
