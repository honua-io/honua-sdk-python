"""Pure response-parse and header helpers shared by the admin clients.

The admin sync (:class:`HonuaAdminClient`) and async
(:class:`AsyncHonuaAdminClient`) clients duplicate the
``ApiResponse``-unwrap logic and the ``Idempotency-Key`` header policy
character-for-character. Both modules pull those pieces from this
module so the only differences left are the unavoidable ``await``
keywords and the sync/async ``def`` declarations.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

import httpx


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


def build_idempotency_headers(
    idempotency_key: str | None,
    *,
    retry_methods: frozenset[str],
    extra: Mapping[str, str] | None = None,
) -> dict[str, str] | None:
    """Build the ``Idempotency-Key`` header dict, auto-generating if needed.

    When ``idempotency_key`` is ``None`` and ``retry_methods`` opts
    ``POST`` in, a fresh ``uuid4().hex`` is used. ``extra`` is merged in
    first (caller wins on collisions). Returns ``None`` when no header
    should be sent.
    """
    headers: dict[str, str] = {}
    if extra:
        headers.update(extra)
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    elif "POST" in retry_methods:
        headers["Idempotency-Key"] = uuid.uuid4().hex
    return headers or None


__all__ = [
    "build_idempotency_headers",
    "unwrap_envelope",
]
