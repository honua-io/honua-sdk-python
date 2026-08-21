from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from honua_sdk.errors import HonuaHttpError
from scripts._conformance import (
    ConformanceTarget,
    FixtureBundle,
    _run_feature_query_unsupported_capability,
    _run_ogc_features_items,
)


class _Ogc:
    def __init__(self, pages: dict[int, dict[str, Any]]) -> None:
        self._pages = pages

    def collections(self) -> dict[str, Any]:
        return {"collections": [{"id": "0"}]}

    def items(self, collection_id: str, *, limit: int, offset: int) -> dict[str, Any]:
        assert collection_id == "0"
        assert limit == 1
        return self._pages[offset]


class _OgcClient:
    def __init__(self, pages: dict[int, dict[str, Any]]) -> None:
        self._ogc = _Ogc(pages)

    def ogc_features(self) -> _Ogc:
        return self._ogc


class _QueryClient:
    def __init__(self, response: Any = None, error: HonuaHttpError | None = None) -> None:
        self.response = response
        self.error = error

    def query_features(self, *args: Any, **kwargs: Any) -> Any:
        if self.error is not None:
            raise self.error
        return self.response


TARGET = ConformanceTarget(base_url="https://example.test", service_id="test", layer_id=0)
BUNDLE = FixtureBundle(Path("."), "fixture-v1")


def _page(feature_id: str, *, next_link: bool) -> dict[str, Any]:
    links = [{"rel": "self", "href": "https://example.test/items"}]
    if next_link:
        links.append({"rel": "next", "href": "https://example.test/items?limit=1&offset=1"})
    return {
        "type": "FeatureCollection",
        "numberMatched": 2,
        "features": [{"type": "Feature", "id": feature_id, "properties": {"name": feature_id}}],
        "links": links,
    }


def test_ogc_items_probe_proves_page_boundary_and_continuation() -> None:
    result = _run_ogc_features_items(_OgcClient({0: _page("a", next_link=True), 1: _page("b", next_link=False)}), TARGET, BUNDLE)

    assert result["number_matched"] == 2
    assert result["second_page_feature_id"] == "b"


@pytest.mark.parametrize(
    "first_page",
    [
        {**_page("a", next_link=True), "features": _page("a", next_link=True)["features"] * 2},
        _page("a", next_link=False),
    ],
)
def test_ogc_items_probe_rejects_unproven_pagination(first_page: dict[str, Any]) -> None:
    with pytest.raises(AssertionError):
        _run_ogc_features_items(_OgcClient({0: first_page, 1: _page("b", next_link=False)}), TARGET, BUNDLE)


def test_invalid_query_probe_accepts_structured_client_error() -> None:
    error = HonuaHttpError(
        400,
        "invalid query",
        body={"error": {"code": 400, "message": "Invalid where clause"}},
    )

    result = _run_feature_query_unsupported_capability(_QueryClient(error=error), TARGET, BUNDLE)

    assert result["error_code"] == 400


@pytest.mark.parametrize(
    "error",
    [
        HonuaHttpError(500, "internal", body={"error": {"code": 500, "message": "Internal"}}),
        HonuaHttpError(400, "invalid", body="plain text"),
        HonuaHttpError(400, "invalid", body={"error": {"code": 400}}),
    ],
)
def test_invalid_query_probe_rejects_server_or_unstructured_errors(error: HonuaHttpError) -> None:
    with pytest.raises(AssertionError):
        _run_feature_query_unsupported_capability(_QueryClient(error=error), TARGET, BUNDLE)
