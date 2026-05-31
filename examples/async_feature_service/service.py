"""Async FastAPI service backed by :class:`AsyncHonuaClient`.

This demo exposes two read-only routes that an app developer would realistically
put in front of a Honua deployment:

* ``GET /services`` lists the GeoServices catalog as typed
  :class:`~honua_sdk.ServiceSummary` rows via
  :meth:`AsyncHonuaClient.list_service_summaries`.
* ``GET /features`` runs a feature query through the canonical
  ``client.source(...).query(...)`` facade so returned features are normalized
  typed objects rather than raw GeoServices dicts.

The app shares a single long-lived ``AsyncHonuaClient`` across requests via the
FastAPI lifespan, which is the pattern you want in a real service: the client
owns an ``httpx`` connection pool, so opening one per request would throw that
pooling away.

Run it locally with::

    uvicorn examples.async_feature_service.service:create_app --factory --reload

The helper functions (:func:`fetch_features`, :func:`list_services`,
:func:`serialize_features`, :func:`serialize_services`) are deliberately
framework-free so they can be unit-tested against a fake client without
standing up an ASGI server. See ``tests/test_async_feature_service_example.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
from typing import Any, cast

from honua_sdk import (
    AsyncHonuaClient,
    Query,
    Result,
    ServiceSummary,
    SourceDescriptor,
    SourceLocator,
)

DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_SERVICE_ID = "test_service"
DEFAULT_LAYER_ID = 0


@dataclass(frozen=True, slots=True)
class ServiceSettings:
    """Runtime configuration for the async feature service."""

    base_url: str = DEFAULT_BASE_URL
    service_id: str = DEFAULT_SERVICE_ID
    layer_id: int = DEFAULT_LAYER_ID
    api_key: str | None = None


def settings_from_env() -> ServiceSettings:
    """Build :class:`ServiceSettings` from the shared demo-suite env contract."""
    return ServiceSettings(
        base_url=os.getenv("HONUA_BASE_URL", DEFAULT_BASE_URL),
        service_id=os.getenv("HONUA_SERVICE_ID", DEFAULT_SERVICE_ID),
        layer_id=int(os.getenv("HONUA_LAYER_ID", str(DEFAULT_LAYER_ID))),
        api_key=os.getenv("HONUA_API_KEY"),
    )


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
) -> Result[Any]:
    """Query the configured layer through the typed source facade."""
    source = _source_for(client, settings)
    result = await source.query(
        Query(
            where=where,
            out_fields=["*"],
            return_geometry=True,
            bbox=list(bbox) if bbox is not None else None,
        ),
        limit=limit,
    )
    return cast("Result[Any]", result)


async def list_services(client: Any) -> list[ServiceSummary]:
    """Return the GeoServices catalog as typed summaries."""
    return cast("list[ServiceSummary]", await client.list_service_summaries())


def serialize_features(result: Result[Any]) -> dict[str, Any]:
    """Render a :class:`Result` as a JSON-safe payload."""
    return {
        "feature_count": len(result.features),
        "features": [
            {"properties": dict(feature.properties), "geometry": feature.geometry}
            for feature in result.features
        ],
    }


def serialize_services(services: list[ServiceSummary]) -> dict[str, Any]:
    """Render typed service summaries as a JSON-safe payload."""
    return {
        "service_count": len(services),
        "services": [
            {"name": service.name, "type": service.type, "url": service.url}
            for service in services
        ],
    }


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must have four comma-separated numbers: minx,miny,maxx,maxy")
    minx, miny, maxx, maxy = parts
    if minx >= maxx or miny >= maxy:
        raise ValueError("bbox minimums must be less than maximums")
    return minx, miny, maxx, maxy


def create_app(settings: ServiceSettings | None = None) -> Any:
    """Build the FastAPI app, sharing one ``AsyncHonuaClient`` via lifespan."""
    from fastapi import FastAPI, HTTPException
    from fastapi import Query as FastAPIQuery

    app_settings = settings or settings_from_env()

    @asynccontextmanager
    async def lifespan(app: "FastAPI") -> AsyncIterator[None]:
        async with AsyncHonuaClient(app_settings.base_url, api_key=app_settings.api_key) as client:
            app.state.honua_client = client
            yield

    app = FastAPI(title="Honua Async Feature Service Demo", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/services")
    async def services() -> dict[str, Any]:
        client = app.state.honua_client
        return serialize_services(await list_services(client))

    @app.get("/features")
    async def features(
        bbox: str | None = FastAPIQuery(default=None, description="minx,miny,maxx,maxy in EPSG:4326"),
        where: str = "1=1",
        limit: int = FastAPIQuery(default=100, ge=1, le=1000),
    ) -> dict[str, Any]:
        try:
            parsed_bbox = _parse_bbox(bbox) if bbox is not None else None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        client = app.state.honua_client
        result = await fetch_features(
            client,
            app_settings,
            bbox=parsed_bbox,
            where=where,
            limit=limit,
        )
        return serialize_features(result)

    return app
