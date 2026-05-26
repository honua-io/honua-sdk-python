"""FastAPI scaffold backed by AsyncHonuaClient spatial queries.

Each request handler opens a short-lived ``AsyncHonuaClient`` and runs the
query through the canonical ``client.source(...).query(...)`` facade so the
returned features are normalized typed objects rather than raw GeoServices
dicts.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from honua_sdk import AsyncHonuaClient, Query, Result, SourceDescriptor, SourceLocator

DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_SERVICE_ID = "test_service"
DEFAULT_LAYER_ID = 0


@dataclass(frozen=True, slots=True)
class ServiceSettings:
    base_url: str = DEFAULT_BASE_URL
    service_id: str = DEFAULT_SERVICE_ID
    layer_id: int = DEFAULT_LAYER_ID
    api_key: str | None = None


def _source_for(client: Any, settings: ServiceSettings) -> Any:
    return client.source(
        SourceDescriptor(
            id=settings.service_id,
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id=settings.service_id, layer_id=settings.layer_id),
        )
    )


async def fetch_features(
    client: Any,
    settings: ServiceSettings,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    where: str = "1=1",
    limit: int = 100,
) -> Result:
    source = _source_for(client, settings)
    return await source.query(
        Query(
            where=where,
            out_fields=["*"],
            return_geometry=True,
            bbox=list(bbox) if bbox is not None else None,
        ),
        limit=limit,
    )


def serialize_features(result: Result) -> dict[str, Any]:
    return {
        "feature_count": len(result.features),
        "features": [
            {"properties": dict(feature.properties), "geometry": feature.geometry}
            for feature in result.features
        ],
    }


def summarize_feature_response(result: Result) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    for feature in result.features:
        status = feature.properties.get("status") if feature.properties else None
        if status is not None:
            key = str(status)
            statuses[key] = statuses.get(key, 0) + 1
    return {
        "feature_count": len(result.features),
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
    from fastapi import FastAPI, Query as FastAPIQuery

    app_settings = settings or settings_from_env()
    app = FastAPI(title="Honua Spatial Service Demo")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/features")
    async def features(
        bbox: str | None = FastAPIQuery(default=None, description="minx,miny,maxx,maxy in EPSG:4326"),
        where: str = "1=1",
        limit: int = FastAPIQuery(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        parsed_bbox = _parse_bbox(bbox) if bbox is not None else None
        async with AsyncHonuaClient(app_settings.base_url, api_key=app_settings.api_key) as client:
            result = await fetch_features(
                client,
                app_settings,
                bbox=parsed_bbox,
                where=where,
                limit=limit,
            )
        return serialize_features(result)

    @app.get("/summary")
    async def summary(
        bbox: str | None = FastAPIQuery(default=None, description="minx,miny,maxx,maxy in EPSG:4326"),
        where: str = "1=1",
        limit: int = FastAPIQuery(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        parsed_bbox = _parse_bbox(bbox) if bbox is not None else None
        async with AsyncHonuaClient(app_settings.base_url, api_key=app_settings.api_key) as client:
            result = await fetch_features(
                client,
                app_settings,
                bbox=parsed_bbox,
                where=where,
                limit=limit,
            )
        return summarize_feature_response(result)

    return app


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must have four comma-separated numbers: minx,miny,maxx,maxy")
    minx, miny, maxx, maxy = parts
    if minx >= maxx or miny >= maxy:
        raise ValueError("bbox minimums must be less than maximums")
    return minx, miny, maxx, maxy
