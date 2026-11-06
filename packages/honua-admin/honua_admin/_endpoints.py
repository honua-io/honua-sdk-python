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

IMPORT_UPLOAD_PATH = "/api/v1/admin/import/upload"
SERVICE_ACCESS_POLICY_PATH = "/api/v1/admin/services/{name}/access-policy"


DEFAULT_CATALOG_PAGE = 1
DEFAULT_CATALOG_PAGE_SIZE = 100
MAX_CATALOG_PAGE_SIZE = 100
MAX_CATALOG_NAME_QUERY_LENGTH = 200


def admin_catalog_params(
    *,
    page: int = DEFAULT_CATALOG_PAGE,
    page_size: int = DEFAULT_CATALOG_PAGE_SIZE,
    name_query: str | None = None,
    extra: tuple[tuple[str, str | None], ...] = (),
) -> dict[str, str]:
    """Query string for one page of an admin catalog list."""
    if page < 1:
        raise ValueError("page must be at least 1.")
    if page_size < 1 or page_size > MAX_CATALOG_PAGE_SIZE:
        raise ValueError("page_size must be from 1 to 100.")
    name = _blank_to_none(name_query)
    if name is not None and len(name) > MAX_CATALOG_NAME_QUERY_LENGTH:
        raise ValueError("name query is longer than 200 characters.")
    params = {"page": str(page), "pageSize": str(page_size)}
    if name is not None:
        params["q"] = name
    for key, value in extra:
        trimmed = _blank_to_none(value)
        if trimmed is not None:
            params[key] = trimmed
    return params


def is_last_catalog_page(item_count: int, page_size: int, total: int, collected: int) -> bool:
    """A short page, an empty page, or a full total ends the walk."""
    return item_count == 0 or collected >= total or item_count < page_size


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


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
    "DEFAULT_CATALOG_PAGE",
    "DEFAULT_CATALOG_PAGE_SIZE",
    "MAX_CATALOG_NAME_QUERY_LENGTH",
    "MAX_CATALOG_PAGE_SIZE",
    "admin_catalog_params",
    "build_idempotency_headers",
    "is_last_catalog_page",
    "unwrap_envelope",
]
