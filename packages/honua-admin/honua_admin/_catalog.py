"""One page of the admin service list or the published-layer list."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._models import AdminServiceSummary, PublishedLayerSummary, _snake_keys


def _page_int(value: Any, default: int) -> int:
    if value is None:
        return default
    return int(value)


def _require_page(data: Any, kind: str) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{kind} data must be a page object.")
    return _snake_keys(data)


def _page_items(raw: Any, parse: Any, kind: str) -> list[Any]:
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise ValueError(f"{kind} items must be a list of objects.")
    return [parse(item) for item in raw]


@dataclass(frozen=True, slots=True)
class ServiceListQuery:
    """Selects one page of the admin service list."""

    page: int = 1
    page_size: int = 100
    name_query: str | None = None
    folder_id: str | None = None


@dataclass(frozen=True, slots=True)
class ServiceListPage:
    """One page of admin services and the count of every match."""

    items: list[AdminServiceSummary]
    page: int
    page_size: int
    total: int
    layer_total: int

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ServiceListPage:
        parsed = _require_page(data, "Service list")
        return cls(
            items=_page_items(parsed.get("items"), AdminServiceSummary.from_dict, "Service list"),
            page=_page_int(parsed.get("page"), 1),
            page_size=_page_int(parsed.get("page_size"), 100),
            total=_page_int(parsed.get("total"), 0),
            layer_total=_page_int(parsed.get("layer_total"), 0),
        )


@dataclass(frozen=True, slots=True)
class LayerListQuery:
    """Selects one page of layers published on a connection."""

    page: int = 1
    page_size: int = 100
    name_query: str | None = None
    service_name: str | None = None


@dataclass(frozen=True, slots=True)
class PublishedLayerPage:
    """One page of published layers and the count of every match."""

    items: list[PublishedLayerSummary]
    page: int
    page_size: int
    total: int

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PublishedLayerPage:
        parsed = _require_page(data, "Layer list")
        return cls(
            items=_page_items(parsed.get("items"), PublishedLayerSummary.from_dict, "Layer list"),
            page=_page_int(parsed.get("page"), 1),
            page_size=_page_int(parsed.get("page_size"), 100),
            total=_page_int(parsed.get("total"), 0),
        )
