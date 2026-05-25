"""Per-call ``extra_headers`` / ``timeout`` / ``idempotency_key`` plumbing tests.

These tests pin the Stripe / OpenAI-SDK shaped overrides on a representative
mix of sync, async, admin, and geocoding public methods. The forwarding
pattern is identical everywhere, so a small representative sample is
sufficient — the underlying ``_request`` already has dedicated coverage.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from honua_admin import AsyncHonuaAdminClient, HonuaAdminClient
from honua_admin._models import ManifestApplyRequest
from honua_sdk import HonuaClient
from honua_sdk.async_client import AsyncHonuaClient
from honua_sdk.async_geocoding import AsyncHonuaGeocodingClient
from honua_sdk.geocoding import HonuaGeocodingClient


def _ok_envelope(payload: object) -> dict[str, object]:
    return {
        "success": True,
        "data": payload,
        "message": "ok",
        "timestamp": "1970-01-01T00:00:00Z",
    }


def _record(seen: list[httpx.Request], body: object = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body if body is not None else {})

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# HonuaClient — extra_headers + timeout
# ---------------------------------------------------------------------------


def test_sync_list_services_forwards_extra_headers() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"services": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.list_services(extra_headers={"X-Test": "1"})
    assert seen[0].headers.get("X-Test") == "1"


def test_sync_list_services_forwards_timeout() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"services": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.list_services(timeout=0.5)
    # httpx exposes the per-request timeout on the Request via extensions.
    timeout_ext = seen[0].extensions.get("timeout")
    assert timeout_ext is not None
    # MockTransport propagates the merged Timeout into request.extensions.
    assert all(v == 0.5 for v in timeout_ext.values())


def test_sync_apply_edits_idempotency_key_overrides_auto() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"addResults": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.apply_edits(
            "svc",
            0,
            adds=[{"attributes": {"OBJECTID": 1}}],
            idempotency_key="explicit-key",
        )
    assert seen[0].headers.get("Idempotency-Key") == "explicit-key"


def test_sync_query_features_forwards_extra_headers() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.query_features("svc", 0, extra_headers={"X-Trace": "abc"})
    assert seen[0].headers.get("X-Trace") == "abc"


# ---------------------------------------------------------------------------
# AsyncHonuaClient — async equivalents
# ---------------------------------------------------------------------------


def test_async_list_services_forwards_extra_headers() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"services": []})

    transport = httpx.MockTransport(handler)

    async def run() -> None:
        async with AsyncHonuaClient(
            "http://example.test", transport=transport, max_retries=0
        ) as client:
            await client.list_services(extra_headers={"X-Test": "async"})

    asyncio.run(run())
    assert seen[0].headers.get("X-Test") == "async"


def test_async_apply_edits_idempotency_key_overrides_auto() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"addResults": []})

    transport = httpx.MockTransport(handler)

    async def run() -> None:
        async with AsyncHonuaClient(
            "http://example.test", transport=transport, max_retries=0
        ) as client:
            await client.apply_edits(
                "svc",
                0,
                adds=[{"attributes": {"OBJECTID": 1}}],
                idempotency_key="explicit-async",
            )

    asyncio.run(run())
    assert seen[0].headers.get("Idempotency-Key") == "explicit-async"


# ---------------------------------------------------------------------------
# Admin client — sync/async parity
# ---------------------------------------------------------------------------


def test_admin_list_services_forwards_extra_headers() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body=_ok_envelope([]))
    with HonuaAdminClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.list_services(extra_headers={"X-Admin": "1"})
    assert seen[0].headers.get("X-Admin") == "1"


def test_admin_apply_manifest_idempotency_key_overrides_auto() -> None:
    seen: list[httpx.Request] = []
    body = _ok_envelope(
        {
            "dryRun": True,
            "summary": {
                "created": 0,
                "updated": 0,
                "deleted": 0,
                "skipped": 0,
            },
            "entries": [],
        }
    )
    transport = _record(seen, body=body)
    with HonuaAdminClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.apply_manifest(
            ManifestApplyRequest(resources=[]),
            idempotency_key="manifest-key",
        )
    assert seen[0].headers.get("Idempotency-Key") == "manifest-key"


def test_async_admin_list_services_forwards_extra_headers() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_ok_envelope([]))

    transport = httpx.MockTransport(handler)

    async def run() -> None:
        async with AsyncHonuaAdminClient(
            "http://example.test", transport=transport, max_retries=0
        ) as client:
            await client.list_services(extra_headers={"X-Admin-Async": "1"})

    asyncio.run(run())
    assert seen[0].headers.get("X-Admin-Async") == "1"


# ---------------------------------------------------------------------------
# Geocoding clients
# ---------------------------------------------------------------------------


def test_geocoding_forward_geocode_forwards_extra_headers() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"candidates": []})
    with HonuaGeocodingClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.forward_geocode("1 Foo St", extra_headers={"X-Geo": "1"})
    assert seen[0].headers.get("X-Geo") == "1"


def test_async_geocoding_forward_geocode_forwards_extra_headers() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"candidates": []})

    transport = httpx.MockTransport(handler)

    async def run() -> None:
        async with AsyncHonuaGeocodingClient(
            "http://example.test", transport=transport, max_retries=0
        ) as client:
            await client.forward_geocode("1 Bar St", extra_headers={"X-Geo": "async"})

    asyncio.run(run())
    assert seen[0].headers.get("X-Geo") == "async"


# ---------------------------------------------------------------------------
# Sanity: timeout=0 raises ConnectTimeout via httpx — we only need to ensure
# the kwarg is wired through the chain without errors when set to a real value.
# ---------------------------------------------------------------------------


def test_sync_apply_edits_timeout_is_propagated() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"addResults": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.apply_edits("svc", 0, adds=[{"attributes": {"OBJECTID": 1}}], timeout=2.5)
    timeout_ext = seen[0].extensions.get("timeout")
    assert timeout_ext is not None
    assert all(v == 2.5 for v in timeout_ext.values())


# ---------------------------------------------------------------------------
# Protocol wrappers — extra_headers / timeout / idempotency_key plumbing
# ---------------------------------------------------------------------------


def test_protocol_feature_server_query_forwards_extra_headers() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        fs = client.feature_server("svc")
        fs.query(0, extra_headers={"X-Probe": "fs"})
    assert seen[0].headers.get("X-Probe") == "fs"


def test_protocol_feature_server_apply_edits_idempotency_key() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"addResults": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        fs = client.feature_server("svc")
        fs.apply_edits(
            0,
            adds=[{"attributes": {"OBJECTID": 1}}],
            idempotency_key="proto-key",
        )
    assert seen[0].headers.get("Idempotency-Key") == "proto-key"


def test_protocol_stac_search_forwards_timeout() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.stac().search(params={"limit": 1}, timeout=1.25)
    timeout_ext = seen[0].extensions.get("timeout")
    assert timeout_ext is not None
    assert all(v == 1.25 for v in timeout_ext.values())


def test_protocol_odata_features_forwards_extra_headers() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"value": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.odata().features(layer_id=1, top=10, extra_headers={"X-OData": "1"})
    assert seen[0].headers.get("X-OData") == "1"


def test_protocol_odata_features_pages_forwards_per_call_options() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"value": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        list(
            client.odata().features_pages(
                layer_id=1,
                limit=1,
                page_size=1,
                extra_headers={"X-OData-Pages": "1"},
                timeout=2.5,
            )
        )
    assert seen, "features_pages should have issued at least one request"
    assert seen[0].headers.get("X-OData-Pages") == "1"
    timeout_ext = seen[0].extensions.get("timeout")
    assert timeout_ext is not None
    assert all(v == 2.5 for v in timeout_ext.values())


def test_protocol_odata_iter_features_forwards_per_call_options() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"value": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        list(
            client.odata().iter_features(
                layer_id=1,
                limit=1,
                page_size=1,
                extra_headers={"X-OData-Iter": "1"},
            )
        )
    assert seen and seen[0].headers.get("X-OData-Iter") == "1"


def test_protocol_odata_layer_pages_forwards_extra_headers() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"value": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        list(
            client.odata().layer_pages(
                limit=1,
                page_size=1,
                extra_headers={"X-OData-Layers": "1"},
            )
        )
    assert seen and seen[0].headers.get("X-OData-Layers") == "1"


def test_sync_query_odata_forwards_per_call_options() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"value": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.query(
            "Features",
            protocol="odata",
            limit=1,
            extra_headers={"X-Dispatch-OData": "1"},
            timeout=4.0,
        )
    assert seen, "OData dispatcher should have issued at least one request"
    assert seen[0].headers.get("X-Dispatch-OData") == "1"
    timeout_ext = seen[0].extensions.get("timeout")
    assert timeout_ext is not None
    assert all(v == 4.0 for v in timeout_ext.values())


def test_sync_iter_query_odata_forwards_extra_headers() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"value": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        for _ in client.iter_query(
            "Features",
            protocol="odata",
            limit=1,
            extra_headers={"X-Dispatch-OData-Iter": "1"},
        ):
            pass
    assert seen and seen[0].headers.get("X-Dispatch-OData-Iter") == "1"


def test_protocol_ogc_create_item_forwards_per_call_options() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"id": "f-1"})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.ogc_features().collection("coll").create_item(
            {"type": "Feature", "geometry": None, "properties": {}},
            extra_headers={"X-Create": "1"},
            idempotency_key="ogc-create-1",
            timeout=2.0,
        )
    assert seen and seen[0].headers.get("X-Create") == "1"
    assert seen[0].headers.get("Idempotency-Key") == "ogc-create-1"
    timeout_ext = seen[0].extensions.get("timeout")
    assert timeout_ext is not None
    assert all(v == 2.0 for v in timeout_ext.values())


def test_protocol_ogc_patch_item_forwards_per_call_options() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"id": "f-1"})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.ogc_features().collection("coll").patch_item(
            "f-1",
            {"properties": {"name": "x"}},
            extra_headers={"X-Patch": "1"},
            idempotency_key="ogc-patch-1",
        )
    assert seen and seen[0].headers.get("X-Patch") == "1"
    assert seen[0].headers.get("Idempotency-Key") == "ogc-patch-1"


def test_protocol_ogc_delete_item_forwards_per_call_options() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen)
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.ogc_features().collection("coll").delete_item(
            "f-1",
            extra_headers={"X-Delete": "1"},
            idempotency_key="ogc-del-1",
        )
    assert seen and seen[0].headers.get("X-Delete") == "1"
    assert seen[0].headers.get("Idempotency-Key") == "ogc-del-1"


# ---------------------------------------------------------------------------
# Dispatcher: client.query / client.iter_query forwarding to underlying pages
# ---------------------------------------------------------------------------


def test_sync_query_forwards_extra_headers_to_feature_server_pages() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.query(
            "svc",
            protocol="feature-server",
            limit=1,
            extra_headers={"X-Dispatch": "fs"},
        )
    assert seen and seen[0].headers.get("X-Dispatch") == "fs"


def test_sync_iter_query_forwards_timeout_to_feature_server_pages() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        for _ in client.iter_query(
            "svc",
            protocol="feature-server",
            limit=1,
            timeout=3.5,
        ):
            pass
    timeout_ext = seen[0].extensions.get("timeout")
    assert timeout_ext is not None
    assert all(v == 3.5 for v in timeout_ext.values())


def test_async_query_forwards_extra_headers_to_feature_server_pages() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"features": []})

    transport = httpx.MockTransport(handler)

    async def run() -> None:
        async with AsyncHonuaClient(
            "http://example.test", transport=transport, max_retries=0
        ) as client:
            await client.query(
                "svc",
                protocol="feature-server",
                limit=1,
                extra_headers={"X-Dispatch-Async": "1"},
            )

    asyncio.run(run())
    assert seen and seen[0].headers.get("X-Dispatch-Async") == "1"


# ---------------------------------------------------------------------------
# Source.query / Source.stream / Source.apply_edits forward per-call options
# ---------------------------------------------------------------------------


def test_source_query_forwards_extra_headers() -> None:
    from honua_sdk import SourceDescriptor, SourceLocator

    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        source = client.source(
            SourceDescriptor(
                id="svc",
                protocol="geoservices-feature-service",
                locator=SourceLocator(service_id="svc", layer_id=0),
            )
        )
        source.query(limit=1, extra_headers={"X-Source": "1"})
    assert seen and seen[0].headers.get("X-Source") == "1"


def test_source_stream_forwards_timeout() -> None:
    from honua_sdk import SourceDescriptor, SourceLocator

    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        source = client.source(
            SourceDescriptor(
                id="svc",
                protocol="geoservices-feature-service",
                locator=SourceLocator(service_id="svc", layer_id=0),
            )
        )
        for _ in source.stream(limit=1, timeout=1.75):
            pass
    timeout_ext = seen[0].extensions.get("timeout")
    assert timeout_ext is not None
    assert all(v == 1.75 for v in timeout_ext.values())


def test_source_apply_edits_forwards_idempotency_key() -> None:
    from honua_sdk import SourceDescriptor, SourceLocator

    seen: list[httpx.Request] = []
    transport = _record(seen, body={"addResults": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        source = client.source(
            SourceDescriptor(
                id="svc",
                protocol="geoservices-feature-service",
                locator=SourceLocator(service_id="svc", layer_id=0),
            )
        )
        source.apply_edits(
            adds=[{"attributes": {"OBJECTID": 1}}],
            idempotency_key="source-key",
        )
    assert seen and seen[0].headers.get("Idempotency-Key") == "source-key"


# ---------------------------------------------------------------------------
# OGC Features pagination plumbing — items_pages / iter_items accept and
# forward per-call timeout / extra_headers (and the dispatcher does too).
# ---------------------------------------------------------------------------


def test_ogc_items_pages_forwards_extra_headers() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        list(
            client.ogc_features()
            .collection("places")
            .items_pages(limit=1, extra_headers={"X-OGC": "1"})
        )
    assert seen and seen[0].headers.get("X-OGC") == "1"


def test_ogc_iter_items_forwards_timeout() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        for _ in (
            client.ogc_features().collection("places").iter_items(limit=1, timeout=1.5)
        ):
            pass
    timeout_ext = seen[0].extensions.get("timeout")
    assert timeout_ext is not None
    assert all(v == 1.5 for v in timeout_ext.values())


def test_sync_query_dispatcher_forwards_extra_headers_to_ogc_pages() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.query(
            "places",
            protocol="ogc-features",
            limit=1,
            extra_headers={"X-OGC-Dispatch": "1"},
        )
    assert seen and seen[0].headers.get("X-OGC-Dispatch") == "1"


def test_sync_iter_query_dispatcher_forwards_timeout_to_ogc_pages() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        for _ in client.iter_query(
            "places",
            protocol="ogc-features",
            limit=1,
            timeout=2.25,
        ):
            pass
    timeout_ext = seen[0].extensions.get("timeout")
    assert timeout_ext is not None
    assert all(v == 2.25 for v in timeout_ext.values())


# ---------------------------------------------------------------------------
# Dispatcher: idempotency_key is folded into extra_headers on the way to the
# pagination wrappers (sync + async).
# ---------------------------------------------------------------------------


def test_sync_query_forwards_idempotency_key_to_feature_server_pages() -> None:
    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        client.query(
            "svc",
            protocol="feature-server",
            limit=1,
            idempotency_key="dispatch-key",
        )
    assert seen and seen[0].headers.get("Idempotency-Key") == "dispatch-key"


def test_async_iter_query_forwards_idempotency_key_to_ogc_pages() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"features": []})

    transport = httpx.MockTransport(handler)

    async def run() -> None:
        async with AsyncHonuaClient(
            "http://example.test", transport=transport, max_retries=0
        ) as client:
            async for _ in client.iter_query(
                "places",
                protocol="ogc-features",
                limit=1,
                idempotency_key="async-ogc-key",
            ):
                pass

    asyncio.run(run())
    assert seen and seen[0].headers.get("Idempotency-Key") == "async-ogc-key"


# ---------------------------------------------------------------------------
# Source.query / Source.stream now accept idempotency_key.
# ---------------------------------------------------------------------------


def test_source_query_forwards_idempotency_key() -> None:
    from honua_sdk import SourceDescriptor, SourceLocator

    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        source = client.source(
            SourceDescriptor(
                id="svc",
                protocol="geoservices-feature-service",
                locator=SourceLocator(service_id="svc", layer_id=0),
            )
        )
        source.query(limit=1, idempotency_key="src-query-key")
    assert seen and seen[0].headers.get("Idempotency-Key") == "src-query-key"


def test_source_stream_forwards_idempotency_key() -> None:
    from honua_sdk import SourceDescriptor, SourceLocator

    seen: list[httpx.Request] = []
    transport = _record(seen, body={"features": []})
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as client:
        source = client.source(
            SourceDescriptor(
                id="svc",
                protocol="geoservices-feature-service",
                locator=SourceLocator(service_id="svc", layer_id=0),
            )
        )
        for _ in source.stream(limit=1, idempotency_key="src-stream-key"):
            pass
    assert seen and seen[0].headers.get("Idempotency-Key") == "src-stream-key"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
