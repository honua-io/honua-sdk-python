"""Pure response-parse and header helpers shared by the admin clients.

The admin sync (:class:`HonuaAdminClient`) and async
(:class:`AsyncHonuaAdminClient`) clients duplicate the
``ApiResponse``-unwrap logic and the ``Idempotency-Key`` header policy
character-for-character. Both modules pull those pieces from this
module so the only differences left are the unavoidable ``await``
keywords and the sync/async ``def`` declarations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from honua_sdk.http import build_idempotency_headers


def unwrap_envelope(response: httpx.Response) -> Any:
    """Strip the ``{"success": true, "data": ...}`` envelope, if present.

    * Empty bodies return ``None``.
    * Bodies that are not JSON return ``response.text`` as a fallback.
    * JSON objects with a ``data`` key return the inner value.
    * Anything else returns the parsed payload verbatim.
    """
    if not response.content:
        return None
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, Mapping) and "data" in payload:
        return payload["data"]
    return payload


__all__ = [
    "build_idempotency_headers",
    "unwrap_envelope",
]
