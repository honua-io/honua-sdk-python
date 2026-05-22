"""Honua arcpy compatibility shim.

Customers replace ``import arcpy`` with ``import honua_arcpy as arcpy`` and
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
    HonuaArcpyConfigurationError,
    HonuaArcpyResolveError,
    HonuaArcpyUnsupportedError,
)
from ._resolve import ResolvedSource, resolve
from ._session import HonuaSession, LayerAlias, get_session
from .env import env

# Re-export Describe at the package level to mirror ``arcpy.Describe``.
from .management import Describe, DescribeResult, FieldDescribe, Selection

try:
    from importlib.metadata import version as _meta_version

    __version__: str = _meta_version("honua-arcpy")
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
    "HonuaArcpyConfigurationError",
    "HonuaArcpyResolveError",
    "HonuaArcpyUnsupportedError",
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
]
