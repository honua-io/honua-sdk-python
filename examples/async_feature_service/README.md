# Async Feature Service Demo

A minimal FastAPI service backed by `AsyncHonuaClient`. It shows the async
pattern an app developer would use to put a thin HTTP API in front of a Honua
deployment:

- `GET /services` — lists the GeoServices catalog as typed `ServiceSummary`
  rows via `AsyncHonuaClient.list_service_summaries()`.
- `GET /features` — runs a feature query through the canonical
  `client.source(...).query(...)` facade, returning normalized typed features.
- `GET /healthz` — liveness check.

The app shares **one** long-lived `AsyncHonuaClient` across requests through the
FastAPI lifespan. The client owns an `httpx` connection pool, so opening a client
per request would discard that pooling. This is the difference from the simpler
`examples/fastapi_spatial_service.py` scaffold, which opens a short-lived client
per request for illustrative purposes.

See [../README.md](../README.md) for the shared demo-suite cloud environment
contract, and [../../docs/troubleshooting.md](../../docs/troubleshooting.md) for
staging base URL, auth, and seeded-service guidance.

## Prerequisites

- Python 3.11+
- A running Honua server (defaults to `http://localhost:8080`)

## Install

From the repo root:

```bash
pip install -e "packages/honua-sdk" fastapi uvicorn
```

## Run

```bash
uvicorn examples.async_feature_service.service:create_app --factory --reload
```

The service reads the shared demo environment contract:

- base URL: `HONUA_BASE_URL` (default `http://localhost:8080`)
- service id: `HONUA_SERVICE_ID` (default `test_service`)
- layer id: `HONUA_LAYER_ID` (default `0`)
- optional API key: `HONUA_API_KEY`

## Try the routes

```bash
# List catalog services
curl 'http://localhost:8000/services'

# Query features (optionally filtered by attribute and/or bbox)
curl 'http://localhost:8000/features?where=1%3D1&limit=10'
curl 'http://localhost:8000/features?bbox=-158,21,-157,22'
```

`bbox` is `minx,miny,maxx,maxy` in EPSG:4326. An invalid bbox returns HTTP 422.

## What this demonstrates

- `AsyncHonuaClient` used as an async context manager over a service lifespan
- `client.list_service_summaries()` returning typed `ServiceSummary` rows
- `client.source(...).query(Query(...))` returning a typed `Result`
- framework-free helpers (`fetch_features`, `list_services`,
  `serialize_features`, `serialize_services`) that are unit-testable against a
  fake client without standing up an ASGI server

## Validation

The helpers and the ASGI routes are covered by:

```bash
pytest tests/test_async_feature_service_example.py
```

The route test uses `httpx.ASGITransport` with a stubbed client injected into
`app.state`, so it runs without a live Honua server. It is skipped automatically
when `fastapi` is not installed.
