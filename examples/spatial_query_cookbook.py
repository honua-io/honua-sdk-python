"""Async spatial query cookbook for Honua protocol surfaces."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from honua_sdk import AsyncHonuaClient

DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_SERVICE_ID = "test_service"
DEFAULT_LAYER_ID = 0
DEFAULT_BBOX = (-180.0, -90.0, 180.0, 90.0)


@dataclass(frozen=True, slots=True)
class CookbookConfig:
    service_id: str = DEFAULT_SERVICE_ID
    layer_id: int = DEFAULT_LAYER_ID
    collection_id: str = DEFAULT_SERVICE_ID
    map_service_id: str = DEFAULT_SERVICE_ID
    stac_collection_id: str | None = None
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX
    where: str = "1=1"
    limit: int = 10


@dataclass(frozen=True, slots=True)
class RecipeResult:
    name: str
    protocol: str
    response_shape: str
    row_count: int | None


async def run_spatial_query_cookbook(client: Any, config: CookbookConfig) -> list[RecipeResult]:
    results: list[RecipeResult] = []

    feature_bbox = await client.query_features(
        config.service_id,
        config.layer_id,
        where=config.where,
        out_fields=["*"],
        return_geometry=True,
        extra_params={
            "geometry": ",".join(str(value) for value in config.bbox),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "resultRecordCount": str(config.limit),
        },
    )
    results.append(_json_result("feature-server-bbox", "FeatureServer", feature_bbox, "features"))
    results.append(_geodataframe_result("feature-server-geodataframe", feature_bbox))

    feature_summary = await client.query_features(
        config.service_id,
        config.layer_id,
        where=config.where,
        out_fields=["objectid"],
        return_geometry=False,
        extra_params={"returnCountOnly": "true"},
    )
    results.append(_json_result("feature-server-filter-summary", "FeatureServer", feature_summary, "features"))

    ogc_items = await client.ogc_features().collection(config.collection_id).items(
        limit=config.limit,
        bbox=list(config.bbox),
    )
    results.append(_json_result("ogc-api-features-items", "OGC API Features", ogc_items, "features"))

    if config.stac_collection_id:
        stac_items = await client.stac().items(
            config.stac_collection_id,
            extra_params={"limit": config.limit},
        )
        results.append(_json_result("stac-items", "STAC", stac_items, "features"))

    wfs_xml = await client.wfs().get_feature(
        type_names=config.collection_id,
        extra_params={"count": config.limit, "bbox": ",".join(str(value) for value in config.bbox)},
    )
    results.append(RecipeResult("wfs-get-feature", "WFS", f"xml:{len(wfs_xml)}", None))

    wms_png = await client.wms(config.map_service_id).map(
        layers=config.collection_id,
        bbox=list(config.bbox),
        width=512,
        height=512,
    )
    results.append(RecipeResult("wms-map-export", "WMS", f"bytes:{len(wms_png)}", None))

    wmts_tile = await client.wmts(config.map_service_id).tile(
        layer=config.collection_id,
        tile_matrix_set="WebMercatorQuad",
        tile_matrix="0",
        tile_row=0,
        tile_col=0,
    )
    results.append(RecipeResult("wmts-tile", "WMTS", f"bytes:{len(wmts_tile)}", None))

    odata_rows = await client.odata().features(
        layer_id=config.layer_id,
        extra_params={"$top": str(config.limit)},
    )
    results.append(_json_result("odata-features", "OData", odata_rows, "value"))

    return results


def build_config_from_env() -> CookbookConfig:
    service_id = os.getenv("HONUA_SERVICE_ID", DEFAULT_SERVICE_ID)
    return CookbookConfig(
        service_id=service_id,
        layer_id=int(os.getenv("HONUA_LAYER_ID", str(DEFAULT_LAYER_ID))),
        collection_id=os.getenv("HONUA_COLLECTION_ID", service_id),
        map_service_id=os.getenv("HONUA_MAP_SERVICE_ID", service_id),
        stac_collection_id=os.getenv("HONUA_STAC_COLLECTION_ID"),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Honua spatial query cookbook.")
    parser.add_argument("--base-url", default=os.getenv("HONUA_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key", default=os.getenv("HONUA_API_KEY"))
    return parser


async def async_main() -> int:
    args = build_parser().parse_args()
    config = build_config_from_env()
    async with AsyncHonuaClient(args.base_url, api_key=args.api_key) as client:
        results = await run_spatial_query_cookbook(client, config)

    for result in results:
        count = "n/a" if result.row_count is None else str(result.row_count)
        print(f"{result.name}: {result.protocol}; {result.response_shape}; rows={count}")
    return 0


def main() -> int:
    return asyncio.run(async_main())


def _json_result(name: str, protocol: str, payload: dict[str, Any], rows_key: str) -> RecipeResult:
    rows = payload.get(rows_key)
    row_count = len(rows) if isinstance(rows, list) else None
    return RecipeResult(name=name, protocol=protocol, response_shape="json", row_count=row_count)


def _geodataframe_result(name: str, payload: dict[str, Any]) -> RecipeResult:
    try:
        from honua_sdk.geopandas import features_to_geodataframe
    except ImportError:
        return RecipeResult(name=name, protocol="GeoPandas", response_shape="geopandas-unavailable", row_count=None)

    gdf = features_to_geodataframe(payload)
    crs = "none" if gdf.crs is None else str(gdf.crs)
    return RecipeResult(name=name, protocol="GeoPandas", response_shape=f"GeoDataFrame:{crs}", row_count=len(gdf))


if __name__ == "__main__":
    raise SystemExit(main())
