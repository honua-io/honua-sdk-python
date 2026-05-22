"""Pytest fixtures for the honua-arcpy test suite."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# Ensure the sibling honua-sdk / honua-admin / honua-arcpy packages are on sys.path
# without requiring an editable install. The CI workflow uses pip install -e, but
# pytest invocations directly from the workspace need this shim.
_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
for relative in ("packages/honua-sdk", "packages/honua-admin", "packages/honua-arcpy"):
    candidate = str(_WORKSPACE_ROOT / relative)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


@pytest.fixture(autouse=True)
def _isolated_audit_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Route audit JSONL into the test-temp directory."""

    audit_dir = tmp_path / "audit"
    monkeypatch.setenv("HONUA_ARCPY_AUDIT_DIR", str(audit_dir))
    yield audit_dir


@pytest.fixture(autouse=True)
def _reset_session() -> Iterator[None]:
    """Reset module-global state between tests."""

    import honua_arcpy

    honua_arcpy.reset()
    yield
    honua_arcpy.reset()


@pytest.fixture
def stub_clients() -> Any:
    """Install the eval stub clients and return them for assertions."""

    import honua_arcpy
    from eval._stub import StubHonuaClient, _StubAdminClient

    client = StubHonuaClient()
    admin = _StubAdminClient()
    honua_arcpy.configure(client=client, admin_client=admin)
    return client, admin
