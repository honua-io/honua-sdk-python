"""Error types for the Honua Python SDK."""

from __future__ import annotations

from typing import Any


class HonuaError(Exception):
    """Base exception for SDK failures."""


class HonuaCapabilityNotSupportedError(HonuaError):
    """Raised when a source protocol does not support a requested capability."""

    def __init__(
        self,
        capability: str,
        protocol: str,
        *,
        source_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        message = f"Capability {capability!r} is not supported for protocol {protocol!r}"
        if source_id is not None:
            message = f"{message} on source {source_id!r}"
        if reason:
            message = f"{message}: {reason}"
        super().__init__(message)
        self.capability = capability
        self.protocol = protocol
        self.source_id = source_id
        self.reason = reason


class HonuaHttpError(HonuaError):
    """Raised when an API request returns a non-success response."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        body: Any | None = None,
    ) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.body = body


class HonuaGrpcError(HonuaError):
    """Raised when a gRPC call fails."""

    def __init__(self, code: Any, message: str, details: Any = None) -> None:
        code_display = getattr(code, "name", code)
        super().__init__(f"gRPC {code_display}: {message}")
        self.code = code
        self.message = message
        self.details = details
