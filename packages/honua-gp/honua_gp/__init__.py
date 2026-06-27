"""Honua arcpy compatibility shim.

Customers replace ``import arcpy`` with ``import honua_gp as arcpy`` and
point the shim at a Honua deployment via :func:`configure` or the
``HONUA_BASE_URL`` / ``HONUA_API_KEY`` environment variables. Every shim call
dispatches through ``honua_sdk`` / ``honua_admin`` / OGC API Processes and
writes an audit JSONL record.
"""

from __future__ import annotations

from typing import Any

from . import analysis as analysis  # re-export sub-package
from . import da as da
from . import management as management
from ._audit import AuditWriter, default_writer, set_audit_writer
from ._compat import COMPAT, FunctionEntry, anchor_for, entry_for
from ._errors import (
    ExecuteError,
    ExecuteWarning,
    HonuaGpConfigurationError,
    HonuaGpResolveError,
    HonuaGpUnsupportedError,
)
from ._resolve import ResolvedSource, resolve
from ._session import HonuaSession, LayerAlias, get_session
from .env import env

# Re-export Describe at the package level to mirror ``arcpy.Describe``.
from .management import Describe, DescribeResult, FieldDescribe, Selection

try:
    from importlib.metadata import version as _meta_version

    __version__: str = _meta_version("honua-gp")
except Exception:  # pragma: no cover -- editable / not-installed fallback
    __version__ = "0.0.0.dev0"


def configure(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    bearer_token: str | None = None,
    client: Any | None = None,
    admin_client: Any | None = None,
    processes_client: Any | None = None,
    **client_kwargs: Any,
) -> None:
    """Configure the global Honua session.

    ``base_url`` + (``api_key`` or ``bearer_token``) is the standard path.
    The remaining keywords (``client``, ``admin_client``, ``processes_client``)
    accept pre-built instances for testing or wire-once integration cases.
    """

    get_session().configure(
        base_url=base_url,
        api_key=api_key,
        bearer_token=bearer_token,
        client=client,
        admin_client=admin_client,
        processes_client=processes_client,
        **client_kwargs,
    )


def configure_from_env() -> None:
    """Configure the global session from ``HONUA_BASE_URL`` / ``HONUA_API_KEY``."""

    get_session().configure_from_env()


def reset() -> None:
    """Reset the global session (test-only helper)."""

    get_session().reset()


# Module-level shorthand mirroring real ``arcpy``:
#   arcpy.GetCount_management(...) -> management.GetCount(...)
GetCount = management.GetCount


# Legacy suffix-style aliases. Real arcpy exposes both ``arcpy.analysis.Buffer``
# and ``arcpy.Buffer_analysis``; many production scripts use the suffix form,
# so the shim re-exports the top-of-corpus entries that way too. Adding a
# new alias requires only listing it here and in ``__all__`` below.
_SUFFIX_ALIASES: dict[str, Any] = {
    # analysis.*
    "Buffer_analysis": analysis.Buffer,
    "Clip_analysis": analysis.Clip,
    "Erase_analysis": analysis.Erase,
    "Intersect_analysis": analysis.Intersect,
    "SpatialJoin_analysis": analysis.SpatialJoin,
    "Union_analysis": analysis.Union,
    # management.*
    "CalculateField_management": management.CalculateField,
    "Copy_management": management.Copy,
    "CopyFeatures_management": management.CopyFeatures,
    "Delete_management": management.Delete,
    "Dissolve_management": management.Dissolve,
    "GetCount_management": management.GetCount,
    "MakeFeatureLayer_management": management.MakeFeatureLayer,
    "MakeTableView_management": management.MakeTableView,
    "Project_management": management.Project,
    "SelectLayerByAttribute_management": management.SelectLayerByAttribute,
}

globals().update(_SUFFIX_ALIASES)


__all__ = [
    "__version__",
    "analysis",
    "da",
    "management",
    "env",
    "configure",
    "configure_from_env",
    "reset",
    "AuditWriter",
    "COMPAT",
    "ExecuteError",
    "ExecuteWarning",
    "FunctionEntry",
    "HonuaGpConfigurationError",
    "HonuaGpResolveError",
    "HonuaGpUnsupportedError",
    "HonuaSession",
    "LayerAlias",
    "ResolvedSource",
    "anchor_for",
    "default_writer",
    "entry_for",
    "get_session",
    "resolve",
    "set_audit_writer",
    # arcpy-compatible re-exports
    "Describe",
    "DescribeResult",
    "FieldDescribe",
    "GetCount",
    "Selection",
    # Legacy suffix-form aliases (real arcpy exposes both)
    *_SUFFIX_ALIASES.keys(),
]
