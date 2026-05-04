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
    class FeatureServerClient:
        async def query_features(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"features": [{"attributes": {"objectid": 1}}]}

    class OgcCollection:
        async def items(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"features": [{"id": "ogc-1"}]}

    class OgcFeatures:
        def collection(self, collection_id: str) -> OgcCollection:
            assert collection_id == "test_service"
            return OgcCollection()

    class Stac:
        async def items(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"features": [{"id": "scene-1"}]}

    class Wfs:
        async def get_feature(self, *args: Any, **kwargs: Any) -> str:
            return "<wfs />"

    class Wms:
        async def map(self, *args: Any, **kwargs: Any) -> bytes:
            return b"png"

    class Wmts:
        async def tile(self, *args: Any, **kwargs: Any) -> bytes:
            return b"tile"

    class OData:
        async def features(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"value": [{"ObjectId": 1}]}

    class FakeClient(FeatureServerClient):
        def ogc_features(self) -> OgcFeatures:
            return OgcFeatures()

        def stac(self) -> Stac:
            return Stac()

        def wfs(self) -> Wfs:
            return Wfs()

        def wms(self, service_id: str) -> Wms:
            assert service_id == "test_service"
            return Wms()

        def wmts(self, service_id: str) -> Wmts:
            assert service_id == "test_service"
            return Wmts()

        def odata(self) -> OData:
            return OData()

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
    seen: dict[str, Any] = {}

    class FakeClient:
        async def query_features(self, service_id: str, layer_id: int, **kwargs: Any) -> dict[str, Any]:
            seen["service_id"] = service_id
            seen["layer_id"] = layer_id
            seen.update(kwargs)
            return {
                "features": [
                    {"attributes": {"status": "active"}},
                    {"attributes": {"status": "active"}},
                    {"attributes": {"status": "needs review"}},
                ]
            }

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
    assert seen["extra_params"]["geometry"] == "-158.0,21.0,-157.0,22.0"
    assert seen["extra_params"]["resultRecordCount"] == "25"
    assert fastapi_spatial_service.summarize_feature_response(response) == {
        "feature_count": 3,
        "status_counts": {"active": 2, "needs review": 1},
    }


def test_fastapi_bbox_parser_validates_shape() -> None:
    assert fastapi_spatial_service._parse_bbox("-158,21,-157,22") == (-158.0, 21.0, -157.0, 22.0)
    with pytest.raises(ValueError, match="four comma-separated"):
        fastapi_spatial_service._parse_bbox("-158,21,-157")
