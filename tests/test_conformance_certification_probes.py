from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from honua_sdk.errors import HonuaHttpError
from scripts._conformance import (
    ConformanceTarget,
    FixtureBundle,
    _run_feature_query,
    _run_feature_query_jsonb_projection,
    _run_feature_query_unsupported_capability,
    _run_ogc_features_items,
    _run_temporal_query,
)


class _Ogc:
    def __init__(self, pages: dict[int, dict[str, Any]]) -> None:
        self._pages = pages
        self.followed_hrefs: list[str] = []

    def collections(self) -> dict[str, Any]:
        return {"collections": [{"id": "0"}]}

    def items(self, collection_id: str, *, limit: int, offset: int) -> dict[str, Any]:
        assert collection_id == "0"
        assert limit == 1
        return self._pages[offset]

    def items_pages(self, collection_id: str, *, page_size: int, limit: int, max_pages: int):
        assert collection_id == "0"
        assert (page_size, limit, max_pages) == (1, 2, 2)
        first = self._pages[0]
        yield first
        links = first.get("links", [])
        next_href = next(link["href"] for link in links if link.get("rel") == "next")
        self.followed_hrefs.append(next_href)
        yield self._pages[1]


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


class _PagedQueryClient:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def query_features(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.pages[len(self.calls) - 1]


class _TemporalClient:
    def _request_json(
        self,
        _method: str,
        _path: str,
        *,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        time_window = params.get("time")
        if time_window == "0,1":
            return {"features": []}
        if time_window is not None:
            return {"features": []}
        return {"features": [{"attributes": {"OBJECTID": 1}}]}


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
    client = _OgcClient({0: _page("a", next_link=True), 1: _page("b", next_link=False)})
    opaque_href = "https://example.test/other/collections/0/items?cursor=opaque&limit=1&vendor=x"
    client._ogc._pages[0]["links"][-1]["href"] = opaque_href
    result = _run_ogc_features_items(client, TARGET, BUNDLE)

    assert result["number_matched"] == 2
    assert result["second_page_feature_id"] == "b"
    assert client._ogc.followed_hrefs == [opaque_href]


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


def test_ogc_items_probe_rejects_repeated_continuation_page() -> None:
    first_page = _page("a", next_link=True)
    first_page["links"][-1]["href"] = "https://example.test/items?limit=1&offset=0"

    with pytest.raises(AssertionError, match="repeated the first page"):
        _run_ogc_features_items(_OgcClient({0: first_page, 1: first_page}), TARGET, BUNDLE)


def test_ogc_items_probe_rejects_cross_authority_continuation() -> None:
    first_page = _page("a", next_link=True)
    first_page["links"][-1]["href"] = "https://attacker.example/items?offset=1"

    with pytest.raises(AssertionError, match="deployment authority"):
        _run_ogc_features_items(
            _OgcClient({0: first_page, 1: _page("b", next_link=False)}),
            TARGET,
            BUNDLE,
        )


def test_temporal_probe_rejects_empty_seeded_window() -> None:
    with pytest.raises(AssertionError, match="seeded in-range"):
        _run_temporal_query(_TemporalClient(), TARGET, BUNDLE)


def test_json_field_probe_rejects_stringified_arrays() -> None:
    response = {
        "features": [{
            "attributes": {"feature_count": 1, "tags": '["red","blue"]', "numbers": "[0,1,2]"},
            "geometry": {"x": 0, "y": 0},
        }],
        "exceededTransferLimit": False,
    }

    with pytest.raises(AssertionError, match="tags value/type drift"):
        _run_feature_query_jsonb_projection(_QueryClient(response=response), TARGET, BUNDLE)


def test_json_field_probe_rejects_boolean_numbers() -> None:
    response = {
        "features": [{
            "attributes": {"feature_count": 1, "tags": ["red", "blue"], "numbers": [False, True, 2]},
            "geometry": {"x": 0, "y": 0},
        }],
        "exceededTransferLimit": False,
    }

    with pytest.raises(AssertionError, match="array of integers"):
        _run_feature_query_jsonb_projection(_QueryClient(response=response), TARGET, BUNDLE)


def test_invalid_query_probe_accepts_structured_client_error() -> None:
    error = HonuaHttpError(
        400,
        "invalid query",
        body={"error": {"code": 400, "message": "Invalid where clause"}},
    )

    result = _run_feature_query_unsupported_capability(_QueryClient(error=error), TARGET, BUNDLE)

    assert result["error_code"] == 400


def test_feature_query_probe_proves_two_bounded_ordered_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        FixtureBundle,
        "response",
        lambda self, name: {"features": [], "exceededTransferLimit": False},
    )

    def page(start: int, count: int, *, more: bool) -> dict[str, Any]:
        return {
            "features": [
                {"attributes": {"OBJECTID": object_id}, "geometry": {"x": 0, "y": 0}}
                for object_id in range(start, start + count)
            ],
            "exceededTransferLimit": more,
        }

    client = _PagedQueryClient([page(1, 5, more=True), page(6, 3, more=False)])

    result = _run_feature_query(client, TARGET, BUNDLE)

    assert [call["extra_params"]["resultOffset"] for call in client.calls] == [0, 5]
    assert result["first_page_object_ids"] == [1, 2, 3, 4, 5]
    assert result["second_page_object_ids"] == [6, 7, 8]


def test_feature_query_probe_rejects_repeated_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        FixtureBundle,
        "response",
        lambda self, name: {"features": [], "exceededTransferLimit": False},
    )

    repeated = {
        "features": [
            {"attributes": {"objectid": object_id}, "geometry": {"x": 0, "y": 0}}
            for object_id in range(1, 6)
        ],
        "exceededTransferLimit": True,
    }

    with pytest.raises(AssertionError, match="non-overlapping"):
        _run_feature_query(_PagedQueryClient([repeated, repeated]), TARGET, BUNDLE)


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
