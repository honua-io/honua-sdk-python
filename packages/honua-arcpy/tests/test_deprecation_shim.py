"""Tests for the deprecated ``honua_arcpy`` backward-compatibility shim."""

from __future__ import annotations

import importlib
import sys
import warnings
from pathlib import Path

# Ensure the sibling honua-gp / honua-sdk / honua-admin packages and this shim
# are importable without an editable install (mirrors the workspace conftest).
_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
for _relative in (
    "packages/honua-sdk",
    "packages/honua-admin",
    "packages/honua-gp",
    "packages/honua-arcpy",
):
    _candidate = str(_WORKSPACE_ROOT / _relative)
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)


def test_importing_honua_arcpy_emits_deprecation_warning() -> None:
    sys.modules.pop("honua_arcpy", None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module("honua_arcpy")
    messages = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
    assert any("honua_gp" in message for message in messages)


def test_shim_reexports_honua_gp_public_api() -> None:
    import honua_arcpy
    import honua_gp

    assert honua_arcpy.__all__ == honua_gp.__all__
    # A representative sample of the re-exported public surface resolves.
    assert honua_arcpy.configure is honua_gp.configure
    assert honua_arcpy.analysis is honua_gp.analysis
    assert honua_arcpy.management is honua_gp.management
    assert honua_arcpy.da is honua_gp.da


def test_submodule_import_paths_resolve() -> None:
    from honua_arcpy import analysis as shim_analysis
    from honua_arcpy.da import __name__ as da_name  # noqa: F401

    import honua_gp

    assert shim_analysis is honua_gp.analysis
