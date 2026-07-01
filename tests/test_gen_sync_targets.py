"""Guard that the async->sync codegen registry stays complete.

AUD-160 (issue #129): ``scripts/gen_sync.py`` is the anti-duplication
mechanism for the async/sync *file-pair* mirrors — but its drift guard
(``gen_sync.py --check``, run in CI) only protects the pairs listed in
``TARGETS``. A new ``async_*`` / ``_async_*`` source module added without a
matching ``Target`` would silently escape the guard and be free to diverge
from its generated sync sibling. This test fails CI in exactly that case, so
new mirror pairs cannot slip past ``--check``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN_SYNC_PATH = ROOT / "scripts" / "gen_sync.py"

SPEC = importlib.util.spec_from_file_location("gen_sync", GEN_SYNC_PATH)
assert SPEC is not None
assert SPEC.loader is not None
gen_sync = importlib.util.module_from_spec(SPEC)
# Register before exec so the module's dataclasses (Rule/Target) can resolve
# their own ``__module__`` during type introspection.
sys.modules["gen_sync"] = gen_sync
SPEC.loader.exec_module(gen_sync)


def _async_source_modules() -> set[Path]:
    """Every committed ``async_*`` / ``_async_*`` package module (codegen sources)."""
    package_roots = [
        ROOT / "packages" / "honua-sdk" / "honua_sdk",
        ROOT / "packages" / "honua-admin" / "honua_admin",
    ]
    found: set[Path] = set()
    for base in package_roots:
        for pattern in ("async_*.py", "_async_*.py"):
            for path in base.rglob(pattern):
                if "_generated" in path.parts:
                    continue
                found.add(path.resolve())
    return found


def test_every_async_source_is_registered_in_targets() -> None:
    registered = {target.source.resolve() for target in gen_sync.TARGETS}
    missing = _async_source_modules() - registered
    assert not missing, (
        "async source module(s) not registered in scripts/gen_sync.py TARGETS "
        "(they would escape the `gen_sync --check` drift guard): "
        f"{sorted(str(p.relative_to(ROOT)) for p in missing)}"
    )


def test_all_targets_point_at_existing_files() -> None:
    for target in gen_sync.TARGETS:
        assert target.source.exists(), f"missing async source: {target.source_rel}"
        assert target.dest.exists(), f"missing generated sync dest: {target.dest_rel}"
