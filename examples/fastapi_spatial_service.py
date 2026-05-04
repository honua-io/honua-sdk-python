"""FastAPI scaffold backed by AsyncHonuaClient spatial queries."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from honua_sdk import AsyncHonuaClient

DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_SERVICE_ID = "test_service"
DEFAULT_LAYER_ID = 0


@dataclass(frozen=True, slots=True)
class ServiceSettings:
    base_url: str = DEFAULT_BASE_URL
    service_id: str = DEFAULT_SERVICE_ID
    layer_id: int = DEFAULT_LAYER_ID
    api_key: str | None = None


async def fetch_features(
    client: Any,
    settings: ServiceSettings,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    where: str = "1=1",
    limit: int = 100,
) -> dict[str, Any]:
    extra_params: dict[str, Any] = {"resultRecordCount": str(limit)}
    if bbox is not None:
        extra_params.update(
            {
                "geometry": ",".join(str(value) for value in bbox),
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            }
        )
    return await client.query_features(
        settings.service_id,
        settings.layer_id,
        where=where,
        out_fields=["*"],
        return_geometry=True,
        extra_params=extra_params,
    )


def summarize_feature_response(response: dict[str, Any]) -> dict[str, Any]:
    features = response.get("features", [])
    statuses: dict[str, int] = {}
    if isinstance(features, list):
        for feature in features:
            attributes = feature.get("attributes", {}) if isinstance(feature, dict) else {}
            status = attributes.get("status")
            if status is not None:
                statuses[str(status)] = statuses.get(str(status), 0) + 1
    return {
        "feature_count": len(features) if isinstance(features, list) else 0,
        "status_counts": dict(sorted(statuses.items())),
    }


def settings_from_env() -> ServiceSettings:
    return ServiceSettings(
        base_url=os.getenv("HONUA_BASE_URL", DEFAULT_BASE_URL),
        service_id=os.getenv("HONUA_SERVICE_ID", DEFAULT_SERVICE_ID),
        layer_id=int(os.getenv("HONUA_LAYER_ID", str(DEFAULT_LAYER_ID))),
        api_key=os.getenv("HONUA_API_KEY"),
    )


def create_app(settings: ServiceSettings | None = None) -> Any:
    from fastapi import FastAPI, Query

    app_settings = settings or settings_from_env()
    app = FastAPI(title="Honua Spatial Service Demo")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/features")
    async def features(
        bbox: str | None = Query(default=None, description="minx,miny,maxx,maxy in EPSG:4326"),
        where: str = "1=1",
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        parsed_bbox = _parse_bbox(bbox) if bbox is not None else None
        async with AsyncHonuaClient(app_settings.base_url, api_key=app_settings.api_key) as client:
            return await fetch_features(
                client,
                app_settings,
                bbox=parsed_bbox,
                where=where,
                limit=limit,
            )

    @app.get("/summary")
    async def summary(
        bbox: str | None = Query(default=None, description="minx,miny,maxx,maxy in EPSG:4326"),
        where: str = "1=1",
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        parsed_bbox = _parse_bbox(bbox) if bbox is not None else None
        async with AsyncHonuaClient(app_settings.base_url, api_key=app_settings.api_key) as client:
            response = await fetch_features(
                client,
                app_settings,
                bbox=parsed_bbox,
                where=where,
                limit=limit,
            )
        return summarize_feature_response(response)

    return app


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must have four comma-separated numbers: minx,miny,maxx,maxy")
    minx, miny, maxx, maxy = parts
    if minx >= maxx or miny >= maxy:
        raise ValueError("bbox minimums must be less than maximums")
    return minx, miny, maxx, maxy
