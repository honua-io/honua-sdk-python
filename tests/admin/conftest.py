"""Shared fixtures for admin client tests."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from honua_admin import HonuaAdminClient


def service_page(
    items: list[Any],
    *,
    total: int | None = None,
    layer_total: int = 0,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    """One admin service-list page."""
    return {
        "items": items,
        "page": page,
        "pageSize": page_size,
        "total": len(items) if total is None else total,
        "layerTotal": layer_total,
    }


def layer_page(
    items: list[Any],
    *,
    total: int | None = None,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    """One published-layer page."""
    return {
        "items": items,
        "page": page,
        "pageSize": page_size,
        "total": len(items) if total is None else total,
    }


def make_api_response(data: Any, message: str | None = None) -> dict[str, Any]:
    """Wrap data in the ApiResponse envelope."""
    return {
        "success": True,
        "data": data,
        "message": message,
        "timestamp": "2026-03-01T00:00:00Z",
    }


@pytest.fixture
def make_client():
    """Factory fixture that creates an admin client with a mock transport."""

    def _factory(handler):
        transport = httpx.MockTransport(handler)
        return HonuaAdminClient("http://test.honua.io", transport=transport)

    return _factory
