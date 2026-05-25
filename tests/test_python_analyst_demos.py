"""Tests for Python analyst demo scaffolds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("geopandas")

from examples import data_quality_report, fastapi_spatial_service, spatial_query_cookbook

EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples"
DEMO_CSV = EXAMPLE_DIR / "geospatial_etl" / "data" / "demo_sites.csv"


def test_data_quality_report_writes_deterministic_artifacts(tmp_path: Path) -> None:
    report = data_quality_report.build_data_quality_report(
        input_path=DEMO_CSV,
        output_dir=tmp_path,
    )

    assert report.summary["source_row_count"] == 9
    assert report.summary["valid_row_count"] == 6
    assert report.summary["rejected_row_count"] == 3
    assert report.summary["reason_counts"] == {
        "duplicate_uid": 1,
        "missing_coordinates": 1,
        "missing_required_field:name": 1,
    }
    assert report.json_path.exists()
    assert report.html_path.exists()
    assert "Honua Data Quality Report" in report.html_path.read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_spatial_query_cookbook_exercises_protocol_patterns() -> None:
    """Cookbook drives the canonical ``client.source().query()`` facade.

    The fake mirrors the public shape: ``client.source(SourceDescriptor)`` returns
    an awaitable source whose ``.query(Query, limit=...)`` resolves to a
    ``Result``-shaped object with a ``features`` list. The raw-bytes protocol
    factories (``wfs()``/``wms()``/``wmts()``) are exercised directly per the
    cookbook's "not a queryable Source" escape hatch.
    """

    class FakeFeature:
        def __init__(self, attributes: dict[str, Any]) -> None:
            self.attributes = attributes
            self.geometry: dict[str, Any] | None = None

    class FakeResult:
        def __init__(self, features: list[FakeFeature]) -> None:
            self.features = features

    class FakeAsyncSource:
        def __init__(self, features: list[FakeFeature]) -> None:
            self._features = features

        async def query(self, _query: Any, **_kwargs: Any) -> FakeResult:
            return FakeResult(self._features)

    class Wfs:
        async def get_feature(self, *args: Any, **kwargs: Any) -> str:
            return "<wfs />"

    class Wms:
        async def map(self, *args: Any, **kwargs: Any) -> bytes:
            return b"png"

    class Wmts:
        async def tile(self, *args: Any, **kwargs: Any) -> bytes:
            return b"tile"

    class FakeClient:
        def source(self, descriptor: Any) -> FakeAsyncSource:
            protocol_to_attrs = {
                "geoservices-feature-service": [{"objectid": 1}],
                "ogc-features": [{"id": "ogc-1"}],
                "stac": [{"id": "scene-1"}],
                "odata": [{"ObjectId": 1}],
            }
            attrs_list = protocol_to_attrs.get(descriptor.protocol, [])
            return FakeAsyncSource([FakeFeature(attrs) for attrs in attrs_list])

        def wfs(self) -> Wfs:
            return Wfs()

        def wms(self, service_id: str) -> Wms:
            assert service_id == "test_service"
            return Wms()

        def wmts(self, service_id: str) -> Wmts:
            assert service_id == "test_service"
            return Wmts()

    results = await spatial_query_cookbook.run_spatial_query_cookbook(
        FakeClient(),
        spatial_query_cookbook.CookbookConfig(stac_collection_id="imagery"),
    )

    assert [result.name for result in results] == [
        "feature-server-bbox",
        "feature-server-filter-summary",
        "ogc-api-features-items",
        "stac-items",
        "wfs-get-feature",
        "wms-map-export",
        "wmts-tile",
        "odata-features",
    ]
    assert results[0].row_count == 1
    assert results[5].response_shape == "bytes:3"


@pytest.mark.anyio
async def test_fastapi_service_helpers_build_query_and_summary() -> None:
    """FastAPI helpers drive ``client.source().query(Query)`` and return a Result."""
    seen: dict[str, Any] = {}

    class FakeFeature:
        def __init__(self, status: str) -> None:
            self.properties = {"status": status}
            self.geometry: dict[str, Any] | None = None

    class FakeResult:
        def __init__(self, features: list[FakeFeature]) -> None:
            self.features = features

    class FakeAsyncSource:
        async def query(self, query: Any, **kwargs: Any) -> FakeResult:
            seen["where"] = query.where
            seen["bbox"] = query.bbox
            seen["limit"] = kwargs.get("limit")
            return FakeResult(
                [FakeFeature("active"), FakeFeature("active"), FakeFeature("needs review")]
            )

    class FakeClient:
        def source(self, descriptor: Any) -> FakeAsyncSource:
            seen["descriptor_id"] = descriptor.id
            seen["service_id"] = descriptor.locator.service_id
            seen["layer_id"] = descriptor.locator.layer_id
            return FakeAsyncSource()

    settings = fastapi_spatial_service.ServiceSettings(service_id="incidents", layer_id=2)
    response = await fastapi_spatial_service.fetch_features(
        FakeClient(),
        settings,
        bbox=(-158.0, 21.0, -157.0, 22.0),
        where="status <> 'closed'",
        limit=25,
    )

    assert seen["service_id"] == "incidents"
    assert seen["layer_id"] == 2
    assert seen["where"] == "status <> 'closed'"
    assert seen["bbox"] == [-158.0, 21.0, -157.0, 22.0]
    assert seen["limit"] == 25
    assert fastapi_spatial_service.summarize_feature_response(response) == {
        "feature_count": 3,
        "status_counts": {"active": 2, "needs review": 1},
    }


def test_fastapi_bbox_parser_validates_shape() -> None:
    assert fastapi_spatial_service._parse_bbox("-158,21,-157,22") == (-158.0, 21.0, -157.0, 22.0)
    with pytest.raises(ValueError, match="four comma-separated"):
        fastapi_spatial_service._parse_bbox("-158,21,-157")
