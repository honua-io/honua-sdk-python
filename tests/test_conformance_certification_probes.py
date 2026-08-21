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
    _run_feature_query_layer_fields,
    _run_catalog_lists_service,
    _run_feature_query_unsupported_capability,
    _run_analysis_process_surface,
    _run_ogc_features_items,
    _run_replica_surface,
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


class _LayerFeatureServer:
    def __init__(self, metadata: dict[str, Any]) -> None:
        self._metadata = metadata

    def layer_metadata(self, _layer_id: int) -> dict[str, Any]:
        return self._metadata


class _LayerClient:
    def __init__(self, metadata: dict[str, Any]) -> None:
        self._feature_server = _LayerFeatureServer(metadata)

    def feature_server(self, _service_id: str) -> _LayerFeatureServer:
        return self._feature_server


class _ProcessesFacade:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

    def processes(self) -> dict[str, Any]:
        return self._response


class _ProcessesClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self._processes = _ProcessesFacade(response)

    def ogc_processes(self) -> _ProcessesFacade:
        return self._processes


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


class _TemporalLeakClient:
    def _request_json(
        self,
        _method: str,
        _path: str,
        *,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        time_window = params.get("time")
        if time_window == "0,1":
            return {"features": [{"attributes": {"OBJECTID": 1}}]}
        if time_window is not None:
            return {"features": [{"attributes": {"OBJECTID": 2}}]}
        return {
            "features": [
                {"attributes": {"OBJECTID": 1}},
                {"attributes": {"OBJECTID": 2}},
            ]
        }


class _ReplicaFeatureServer:
    def __init__(self, metadata: dict[str, Any]) -> None:
        self._metadata = metadata

    def metadata(self) -> dict[str, Any]:
        return self._metadata


class _ReplicaClient:
    def __init__(self, metadata: dict[str, Any]) -> None:
        self._feature_server = _ReplicaFeatureServer(metadata)

    def feature_server(self, _service_id: str) -> _ReplicaFeatureServer:
        return self._feature_server


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


@pytest.mark.parametrize(
    "second_page",
    [
        {"features": [{"id": "b", "properties": {"name": "b"}}]},
        {"type": "FeatureCollection", "features": [{"id": "b"}]},
    ],
)
def test_ogc_items_probe_rejects_malformed_continuation(second_page: dict[str, Any]) -> None:
    with pytest.raises(AssertionError):
        _run_ogc_features_items(
            _OgcClient({0: _page("a", next_link=True), 1: second_page}),
            TARGET,
            BUNDLE,
        )


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


def test_temporal_probe_rejects_disjoint_window_leakage() -> None:
    with pytest.raises(AssertionError, match="disjoint pre-seed"):
        _run_temporal_query(_TemporalLeakClient(), TARGET, BUNDLE)


@pytest.mark.parametrize(
    "metadata",
    [
        {"syncEnabled": "false", "capabilities": "Query"},
        {"syncEnabled": False, "capabilities": "Query,NotCreateReplica"},
    ],
)
def test_replica_probe_rejects_untyped_or_partial_sync_signals(metadata: dict[str, Any]) -> None:
    with pytest.raises(AssertionError, match="does not advertise"):
        _run_replica_surface(_ReplicaClient(metadata), TARGET, BUNDLE)


def test_json_field_probe_accepts_seed_without_synthetic_feature_count() -> None:
    response = {
        "features": [{
            "attributes": {"tags": ["red", "blue"], "numbers": [0, 1, 2]},
            "geometry": {"x": 0, "y": 0},
        }],
        "exceededTransferLimit": False,
    }

    result = _run_feature_query_jsonb_projection(_QueryClient(response=response), TARGET, BUNDLE)

    assert result["jsonb_fields_projected"] == ["numbers", "tags"]


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


def test_feature_query_probe_validates_every_first_page_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        FixtureBundle,
        "response",
        lambda self, name: {"features": [], "exceededTransferLimit": False},
    )
    first_page = {
        "features": [
            {"attributes": {"OBJECTID": object_id}, "geometry": {"x": 0, "y": 0}}
            for object_id in range(1, 6)
        ],
        "exceededTransferLimit": True,
    }
    first_page["features"][1].pop("geometry")
    second_page = {
        "features": [{"attributes": {"OBJECTID": 6}, "geometry": {"x": 0, "y": 0}}],
        "exceededTransferLimit": False,
    }

    with pytest.raises(AssertionError, match="feature has no geometry"):
        _run_feature_query(_PagedQueryClient([first_page, second_page]), TARGET, BUNDLE)


@pytest.mark.parametrize(
    "second_page",
    [
        {"features": [{"attributes": {"OBJECTID": 6}, "geometry": {"x": 0, "y": 0}}]},
        {"features": [{"attributes": {"OBJECTID": 6}}], "exceededTransferLimit": False},
    ],
)
def test_feature_query_probe_rejects_malformed_continuation(
    monkeypatch: pytest.MonkeyPatch, second_page: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        FixtureBundle,
        "response",
        lambda self, name: {"features": [], "exceededTransferLimit": False},
    )
    first_page = {
        "features": [
            {"attributes": {"OBJECTID": object_id}, "geometry": {"x": 0, "y": 0}}
            for object_id in range(1, 6)
        ],
        "exceededTransferLimit": True,
    }
    with pytest.raises(AssertionError):
        _run_feature_query(_PagedQueryClient([first_page, second_page]), TARGET, BUNDLE)


def test_layer_metadata_probe_rejects_field_or_object_id_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        FixtureBundle,
        "response",
        lambda self, name: {
            "objectIdFieldName": "OBJECTID",
            "fields": [
                {"name": "OBJECTID", "fieldType": "FIELD_TYPE_BIG_INTEGER"},
                {"name": "NAME", "fieldType": "FIELD_TYPE_STRING"},
            ],
        },
    )
    metadata = {
        "objectIdField": "wrong_id",
        "fields": [
            {"name": "OBJECTID", "type": "esriFieldTypeOID"},
            {"name": "NAME", "type": "esriFieldTypeDouble"},
        ],
    }
    with pytest.raises(AssertionError):
        _run_feature_query_layer_fields(_LayerClient(metadata), TARGET, BUNDLE)


def test_layer_metadata_probe_requires_complete_client_compat_seed_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        FixtureBundle,
        "response",
        lambda self, name: {
            "objectIdFieldName": "OBJECTID",
            "fields": [
                {"name": "OBJECTID", "fieldType": "FIELD_TYPE_BIG_INTEGER"},
                {"name": "NAME", "fieldType": "FIELD_TYPE_STRING"},
                {"name": "AREA", "fieldType": "FIELD_TYPE_DOUBLE"},
            ],
        },
    )
    result = _run_feature_query_layer_fields(
        _LayerClient(
            {
                "objectIdField": "objectid",
                "fields": [
                    {"name": "objectid", "type": "esriFieldTypeOID"},
                    {"name": "name", "type": "esriFieldTypeString"},
                    {"name": "description", "type": "esriFieldTypeString"},
                    {"name": "shape", "type": "esriFieldTypeGeometry"},
                    {"name": "status", "type": "esriFieldTypeString"},
                    {"name": "count", "type": "esriFieldTypeInteger"},
                    {"name": "ratio", "type": "esriFieldTypeDouble"},
                    {"name": "active", "type": "esriFieldTypeSmallInteger"},
                    {"name": "created_at", "type": "esriFieldTypeDate"},
                    {"name": "event_date", "type": "esriFieldTypeDate"},
                    {"name": "event_time", "type": "esriFieldTypeString"},
                    {"name": "uid", "type": "esriFieldTypeGUID"},
                    {"name": "tags", "type": "esriFieldTypeString"},
                    {"name": "numbers", "type": "esriFieldTypeString"},
                    {"name": "eo:cloud_cover", "type": "esriFieldTypeDouble"},
                ],
            }
        ),
        TARGET,
        BUNDLE,
    )

    assert result["matched_fields"] == ["name", "objectid"]
    assert result["fixture_only_fields"] == ["area"]


def test_catalog_probe_requires_feature_server_descriptor() -> None:
    class CatalogClient:
        def list_services(self) -> dict[str, Any]:
            return {"services": [{"name": "test", "type": "MapServer"}]}

    with pytest.raises(AssertionError, match="FeatureServer"):
        _run_catalog_lists_service(CatalogClient(), TARGET, BUNDLE)


@pytest.mark.parametrize(
    "response",
    [
        {"processes": [None]},
        {"processes": [{"id": "unrelated"}]},
    ],
)
def test_process_probe_rejects_malformed_or_unrelated_catalog(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        FixtureBundle,
        "request",
        lambda self, name: {"plan": {"steps": [{"kind": "aggregate"}]}},
    )
    with pytest.raises(AssertionError):
        _run_analysis_process_surface(_ProcessesClient(response), TARGET, BUNDLE)


def test_process_probe_maps_execute_plan_to_canonical_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        FixtureBundle,
        "request",
        lambda self, name: {
            "plan": {
                "steps": [
                    {"kind": "query_features"},
                    {"kind": "aggregate"},
                ]
            }
        },
    )
    result = _run_analysis_process_surface(
        _ProcessesClient(
            {
                "processes": [
                    {"id": "honua-geoprocessing"},
                ]
            }
        ),
        TARGET,
        BUNDLE,
    )

    assert result["fixture_kinds"] == ["aggregate", "query-features"]
    assert result["matched_fixture_processes"] == ["honua-geoprocessing"]


@pytest.mark.parametrize("process_id", ["other:honua-geoprocessing", "honua_geoprocessing"])
def test_process_probe_rejects_noncanonical_wrapper_id(
    monkeypatch: pytest.MonkeyPatch,
    process_id: str,
) -> None:
    monkeypatch.setattr(
        FixtureBundle,
        "request",
        lambda self, name: {"plan": {"steps": [{"kind": "aggregate"}]}},
    )

    with pytest.raises(AssertionError, match="missing canonical process"):
        _run_analysis_process_surface(
            _ProcessesClient({"processes": [{"id": process_id}]}),
            TARGET,
            BUNDLE,
        )


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
