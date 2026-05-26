"""Async spatial query cookbook for Honua protocol surfaces.

Each recipe uses the canonical ``client.source(...).query(...)`` facade so the
same call shape works across FeatureServer, OGC Features, STAC, OData, and the
raw-bytes protocols (WFS/WMS/WMTS). Protocol-specific knobs that are not
modeled on :class:`Query` fall through via ``extra_params`` and are flagged
with a comment.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Any

from honua_sdk import AsyncHonuaClient, Query, SourceDescriptor, SourceLocator

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

    # Recipe 1: FeatureServer bbox query via the canonical source facade.
    feature_source = client.source(
        SourceDescriptor(
            id=config.service_id,
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id=config.service_id, layer_id=config.layer_id),
        )
    )
    feature_bbox_result = await feature_source.query(
        Query(
            where=config.where,
            out_fields=["*"],
            return_geometry=True,
            bbox=list(config.bbox),
        ),
        limit=config.limit,
    )
    results.append(
        RecipeResult(
            name="feature-server-bbox",
            protocol="FeatureServer",
            response_shape="features",
            row_count=len(feature_bbox_result.features),
        )
    )

    # Recipe 2: FeatureServer count-only summary. ``returnCountOnly`` is a
    # GeoServices-specific knob that is not modeled on Query, so we pass it
    # through extra_params. The response is a count envelope, not features.
    feature_summary_result = await feature_source.query(
        Query(
            where=config.where,
            out_fields=["objectid"],
            return_geometry=False,
            extra_params={"returnCountOnly": "true"},  # Raw GeoServices knob; not modeled in Query.
        )
    )
    results.append(
        RecipeResult(
            name="feature-server-filter-summary",
            protocol="FeatureServer",
            response_shape="features",
            row_count=len(feature_summary_result.features),
        )
    )

    # Recipe 3: OGC API Features collection items via the canonical facade.
    ogc_source = client.source(
        SourceDescriptor(
            id=config.collection_id,
            protocol="ogc-features",
            locator=SourceLocator(collection_id=config.collection_id),
        )
    )
    ogc_items_result = await ogc_source.query(
        Query(bbox=list(config.bbox)),
        limit=config.limit,
    )
    results.append(
        RecipeResult(
            name="ogc-api-features-items",
            protocol="OGC API Features",
            response_shape="features",
            row_count=len(ogc_items_result.features),
        )
    )

    # Recipe 4: STAC items via the canonical facade (optional).
    if config.stac_collection_id:
        stac_source = client.source(
            SourceDescriptor(
                id=config.stac_collection_id,
                protocol="stac",
                locator=SourceLocator(collection_id=config.stac_collection_id),
            )
        )
        stac_items_result = await stac_source.query(Query(), limit=config.limit)
        results.append(
            RecipeResult(
                name="stac-items",
                protocol="STAC",
                response_shape="features",
                row_count=len(stac_items_result.features),
            )
        )

    # Recipe 5: WFS GetFeature returns raw XML bytes; not a queryable Source.
    # Use the protocol escape hatch.
    wfs_xml = await client.wfs().get_feature(
        type_names=config.collection_id,
        extra_params={"count": config.limit, "bbox": ",".join(str(value) for value in config.bbox)},
    )
    results.append(RecipeResult("wfs-get-feature", "WFS", f"xml:{len(wfs_xml)}", None))

    # Recipe 6: WMS map export returns raw PNG bytes; not a queryable Source.
    wms_png = await client.wms(config.map_service_id).map(
        layers=config.collection_id,
        bbox=list(config.bbox),
        width=512,
        height=512,
    )
    results.append(RecipeResult("wms-map-export", "WMS", f"bytes:{len(wms_png)}", None))

    # Recipe 7: WMTS tile fetch returns raw tile bytes; not a queryable Source.
    wmts_tile = await client.wmts(config.map_service_id).tile(
        layer=config.collection_id,
        tile_matrix_set="WebMercatorQuad",
        tile_matrix="0",
        tile_row=0,
        tile_col=0,
    )
    results.append(RecipeResult("wmts-tile", "WMTS", f"bytes:{len(wmts_tile)}", None))

    # Recipe 8: OData features via the canonical facade.
    odata_source = client.source(
        SourceDescriptor(
            id=f"odata-layer-{config.layer_id}",
            protocol="odata",
            locator=SourceLocator(layer_id=config.layer_id),
        )
    )
    odata_result = await odata_source.query(Query(), limit=config.limit)
    results.append(
        RecipeResult(
            name="odata-features",
            protocol="OData",
            response_shape="features",
            row_count=len(odata_result.features),
        )
    )

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


if __name__ == "__main__":
    raise SystemExit(main())
