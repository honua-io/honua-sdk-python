"""ExecuteError-shaped exception hierarchy for the honua-arcpy shim.

Customer scripts that catch ``arcpy.ExecuteError`` continue to work; the
top-level ``honua_arcpy.ExecuteError`` aliases this class so the legacy
``except arcpy.ExecuteError:`` idiom catches every shim failure.
"""

from __future__ import annotations

from typing import Any


class ExecuteError(Exception):
    """Top-level shim error, shaped like ``arcpy.ExecuteError``.

    Carries the original ``honua_sdk`` / ``honua_admin`` cause where one
    exists so callers can drill into the underlying transport or capability
    failure without re-raising.
    """

    def __init__(
        self,
        message: str,
        *,
        function: str | None = None,
        error_kind: str | None = None,
        compat_anchor: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.function = function
        self.error_kind = error_kind or "execute_error"
        self.compat_anchor = compat_anchor
        if cause is not None:
            self.__cause__ = cause

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "function": self.function,
            "errorKind": self.error_kind,
            "compatAnchor": self.compat_anchor,
        }


class ExecuteWarning(UserWarning):
    """Soft-warning variant for shim deviations that did not abort the call."""


class HonuaArcpyUnsupportedError(ExecuteError):
    """Raised when a shim function is intentionally stubbed.

    Stubs carry an anchor link to the compatibility matrix entry and, when
    available, the recommended honua-sdk-python replacement call.
    """

    def __init__(
        self,
        function: str,
        *,
        compat_anchor: str,
        replacement_hint: str | None = None,
        tracking: str | None = None,
    ) -> None:
        suffix_parts: list[str] = []
        if replacement_hint:
            suffix_parts.append(f"Suggested replacement: {replacement_hint}")
        if tracking:
            suffix_parts.append(f"Tracking: {tracking}")
        suffix = (" " + " ".join(suffix_parts)) if suffix_parts else ""
        super().__init__(
            f"{function} is not implemented by honua-arcpy. See {compat_anchor}.{suffix}",
            function=function,
            error_kind="unsupported",
            compat_anchor=compat_anchor,
        )
        self.replacement_hint = replacement_hint
        self.tracking = tracking


class HonuaArcpyConfigurationError(ExecuteError):
    """Raised when the shim is invoked without a configured Honua client."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_kind="configuration")


class HonuaArcpyResolveError(ExecuteError):
    """Raised when an arcpy path cannot be resolved to a Honua source."""

    def __init__(self, path: str, *, hint: str | None = None) -> None:
        message = f"Could not resolve arcpy path {path!r} to a Honua source."
        if hint:
            message = f"{message} {hint}"
        super().__init__(message, error_kind="resolve")
        self.path = path


__all__ = [
    "ExecuteError",
    "ExecuteWarning",
    "HonuaArcpyUnsupportedError",
    "HonuaArcpyConfigurationError",
    "HonuaArcpyResolveError",
]
