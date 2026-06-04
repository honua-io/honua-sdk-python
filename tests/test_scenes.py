"""Tests for the 3D scene, elevation, and offline-package clients.

Fixture JSON shapes mirror the .NET SDK
``Honua.Sdk.Scenes.Tests/Fixtures/Scenes`` reference fixtures so the wire
contract stays aligned across SDKs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from honua_sdk import HonuaClient
from honua_sdk.protocols import (
    CURRENT_PACKAGE_SCHEMA_VERSION,
    HonuaSceneAccessModes,
    HonuaSceneCapabilities,
    HonuaSceneError,
    HonuaScenePackageAssetTypes,
    HonuaScenePackageError,
    HonuaScenePackageState,
    HonuaScenePackageValidationCodes,
    enumerate_tileset_contents,
    parse_scene_package_manifest,
)

# ---------------------------------------------------------------------------
# Fixtures (mirroring the .NET reference fixtures)
# ---------------------------------------------------------------------------

SCENE_METADATA = {
    "id": "downtown-honolulu",
    "name": "Downtown Honolulu",
    "description": "Photogrammetry and terrain sample for Honolulu urban planning.",
    "center": {"latitude": 21.3069, "longitude": -157.8583, "height": 1200},
    "bounds": {
        "west": -157.875,
        "south": 21.290,
        "east": -157.835,
        "north": 21.325,
        "minHeight": 0.0,
        "maxHeight": 1500.0,
    },
    "tileset": {
        "url": "https://api.honua.test/api/scenes/downtown-honolulu/tileset.json",
        "format": "3d-tiles",
        "mediaType": "application/json",
        "requiresAuthentication": True,
    },
    "terrain": {
        "url": "https://api.honua.test/api/scenes/downtown-honolulu/terrain",
        "format": "quantized-mesh",
        "requiresAuthentication": True,
    },
    "capabilities": {"3d-tiles": True, "terrain": True},
    "links": [
        {
            "rel": "self",
            "href": "https://api.honua.test/api/scenes/downtown-honolulu",
            "type": "application/json",
            "title": "Scene metadata",
        }
    ],
}

LIST_SCENES = {
    "scenes": [
        {
            "id": "downtown-honolulu",
            "name": "Downtown Honolulu",
            "description": "Photogrammetry and terrain sample.",
            "tilesetUrl": "https://api.honua.test/api/scenes/downtown-honolulu/tileset.json",
            "terrainUrl": "https://api.honua.test/api/scenes/downtown-honolulu/terrain",
            "bbox": [-157.875, 21.290, -157.835, 21.325],
            "capabilities": ["3d-tiles", "terrain"],
            "attribution": ["City and County of Honolulu"],
            "auth": {
                "requiresAuthentication": True,
                "schemes": ["Bearer", "ApiKey"],
                "policy": "project-members",
            },
            "updatedAt": "2026-04-28T00:00:00Z",
        }
    ]
}

RESOLVE_SCENE = {
    "sceneId": "downtown-honolulu",
    "tilesetUrl": "https://api.honua.test/api/scenes/downtown-honolulu/tileset.json?sig=test",
    "terrainUrl": "https://api.honua.test/api/scenes/downtown-honolulu/terrain?sig=test",
    "capabilities": ["3d-tiles", "terrain"],
    "auth": {"requiresAuthentication": True, "schemes": ["Bearer", "ApiKey"]},
    "expiresAt": "2026-04-28T02:00:00Z",
    "endpoints": [
        {
            "kind": "3d-tiles",
            "url": "https://api.honua.test/api/scenes/downtown-honolulu/tileset.json?sig=test",
            "format": "3d-tiles",
            "mediaType": "application/json",
            "requiresAuthentication": True,
            "headers": {"X-Honua-Scene": "downtown-honolulu"},
        },
        {
            "kind": "terrain",
            "url": "https://api.honua.test/api/scenes/downtown-honolulu/terrain?sig=test",
            "format": "quantized-mesh",
            "requiresAuthentication": True,
        },
    ],
}

RESOLVE_ACCESS_SCENE = {
    "sceneId": "protected-downtown",
    "tilesetUrl": "https://cdn.honua.test/scenes/protected-downtown/tileset.json?sig=render",
    "capabilities": ["3d-tiles", "terrain"],
    "auth": {"requiresAuthentication": True, "schemes": ["SignedUrl"]},
    "expiresAt": "2026-04-28T18:30:00Z",
    "access": {
        "mode": "signed-url",
        "refreshAfterUtc": "2026-04-28T18:20:00Z",
        "expiresAtUtc": "2026-04-28T18:30:00Z",
        "corsMode": "registered-origins",
        "cache": {"public": False, "maxAgeSeconds": 300, "staleWhileRevalidateSeconds": 60},
        "customHeadersAllowed": False,
        "revocationKey": "scene-rev-42",
    },
}

ELEVATION_VALUE = {
    "datasetId": "honolulu-dem",
    "layerId": 0,
    "elevation": 12.5,
    "noData": False,
    "outOfBounds": False,
    "x": -157.8583,
    "y": 21.3069,
    "querySrid": 4326,
    "mosaicRule": "first",
    "source": {
        "rasterIds": [101, 102],
        "rasterCount": 2,
        "sourceSrid": 4326,
        "pixelType": "F32",
        "noDataValue": -9999.0,
        "verticalUnit": "meter",
        "verticalDatum": "EGM2008",
        "band": 1,
    },
}

ELEVATION_PROFILE = {
    "datasetId": "honolulu-dem",
    "layerId": 0,
    "sampleCount": 3,
    "lineLengthMeters": 250.0,
    "lineSrid": 4326,
    "mosaicRule": "first",
    "isAllNoData": False,
    "samples": [
        {"distanceMeters": 0.0, "elevation": 10.0, "noData": False},
        {"distanceMeters": 125.0, "elevation": 22.5, "noData": False},
        {"distanceMeters": 250.0, "elevation": None, "noData": True},
    ],
    "source": {"rasterIds": [101], "rasterCount": 1, "verticalUnit": "meter"},
}


def _valid_manifest_dict() -> dict[str, Any]:
    return {
        "schemaVersion": CURRENT_PACKAGE_SCHEMA_VERSION,
        "packageId": "pkg_downtown_honolulu_2026_04",
        "sceneId": "downtown-honolulu",
        "displayName": "Downtown Honolulu 3D",
        "editionGate": "pro",
        "serverRevision": "scene-rev-42",
        "createdAtUtc": "2026-04-28T00:00:00Z",
        "staleAfterUtc": "2026-05-28T00:00:00Z",
        "offlineUseExpiresAtUtc": "2026-06-27T00:00:00Z",
        "authExpiresAtUtc": "2026-04-29T00:00:00Z",
        "extent": {
            "minLongitude": -157.872,
            "minLatitude": 21.293,
            "maxLongitude": -157.841,
            "maxLatitude": 21.319,
        },
        "lod": {"minZoom": 12, "maxZoom": 17, "maxGeometricErrorMeters": 4.0},
        "byteBudget": {"maxPackageBytes": 2147483648, "declaredBytes": 1000000},
        "attribution": ["Honua", "City and County source data"],
        "assets": [
            {
                "key": "scene-metadata",
                "type": "scene-metadata",
                "role": "metadata",
                "path": "metadata/scene.json",
                "contentType": "application/json",
                "bytes": 4832,
                "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "etag": '"scene-42"',
                "required": True,
            },
            {
                "key": "buildings-tileset",
                "type": "3d-tileset",
                "role": "primary-tileset",
                "path": "tilesets/buildings/tileset.json",
                "contentType": "application/json",
                "bytes": 10455,
                "sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
                "required": True,
            },
            {
                "key": "terrain-12-742-1619",
                "type": "terrain-tile",
                "role": "terrain",
                "path": "terrain/12/742/1619.terrain",
                "contentType": "application/vnd.quantized-mesh",
                "bytes": 32984,
                "sha256": "1111111111111111111111111111111111111111111111111111111111111111",
                "required": False,
            },
        ],
    }


_NOW = datetime(2026, 5, 1, tzinfo=UTC)  # before stale (2026-05-28) and expiry


def _make_client(handler: Any, seen: list[dict[str, Any]]) -> HonuaClient:
    transport = httpx.MockTransport(handler)
    return HonuaClient("http://example.test", transport=transport)


# ---------------------------------------------------------------------------
# Scene metadata + capability + 3D extent parse
# ---------------------------------------------------------------------------


def test_get_scene_parses_metadata_extent_and_capabilities() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"raw_path": request.url.raw_path.decode("ascii").split("?")[0], "query": dict(request.url.params.multi_items())})
        return httpx.Response(200, json=SCENE_METADATA)

    with _make_client(handler, seen) as client:
        scene = client.scenes().get_scene("downtown-honolulu")

    assert seen[0]["raw_path"] == "/api/scenes/downtown-honolulu"
    assert seen[0]["query"] == {"f": "json"}
    assert scene.id == "downtown-honolulu"
    assert scene.name == "Downtown Honolulu"
    # tileset + terrain endpoints
    assert scene.tileset is not None
    assert scene.tileset.url.endswith("/tileset.json")
    assert scene.tileset.format == "3d-tiles"
    assert scene.tileset.requires_authentication is True
    assert scene.terrain is not None
    assert scene.terrain.format == "quantized-mesh"
    # suggested camera center
    assert scene.center is not None
    assert scene.center.latitude == pytest.approx(21.3069)
    assert scene.center.height == pytest.approx(1200)
    # 3D extent incl. min/max height
    assert scene.bounds is not None
    assert scene.bounds.min_longitude == pytest.approx(-157.875)
    assert scene.bounds.max_latitude == pytest.approx(21.325)
    assert scene.bounds.min_height == pytest.approx(0.0)
    assert scene.bounds.max_height == pytest.approx(1500.0)
    # capabilities object form -> sorted list incl. endpoint-derived kinds
    assert HonuaSceneCapabilities.THREE_D_TILES in scene.capabilities
    assert HonuaSceneCapabilities.TERRAIN in scene.capabilities
    # links
    assert scene.links[0].rel == "self"
    assert scene.auth.requires_authentication is False  # metadata auth not declared at root


def test_list_scenes_parses_bbox_attribution_and_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=LIST_SCENES)

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        scenes = client.scenes().list_scenes(capabilities=["3d-tiles"])

    assert len(scenes) == 1
    summary = scenes[0]
    assert summary.id == "downtown-honolulu"
    assert summary.bounds is not None
    assert summary.bounds.min_longitude == pytest.approx(-157.875)
    assert summary.attribution == ("City and County of Honolulu",)
    assert summary.auth.requires_authentication is True
    assert summary.auth.schemes == ("Bearer", "ApiKey")
    assert summary.auth.policy == "project-members"
    assert summary.updated_at == datetime(2026, 4, 28, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Scene resolution: tileset/terrain URLs, capabilities, access envelope
# ---------------------------------------------------------------------------


def test_resolve_scene_resolves_urls_endpoints_and_expiry() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"raw_path": request.url.raw_path.decode("ascii").split("?")[0], "query": dict(request.url.params.multi_items())})
        return httpx.Response(200, json=RESOLVE_SCENE)

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        resolution = client.scenes().resolve_scene(
            "downtown-honolulu", required_capabilities=["3d-tiles", "terrain"]
        )

    assert seen[0]["raw_path"] == "/api/scenes/downtown-honolulu/resolve"
    assert seen[0]["query"]["capabilities"] == "3d-tiles,terrain"
    assert seen[0]["query"]["includeTerrain"] == "true"
    assert resolution.scene_id == "downtown-honolulu"
    assert resolution.tileset_url is not None and "sig=test" in resolution.tileset_url
    assert resolution.terrain_url is not None and "sig=test" in resolution.terrain_url
    assert len(resolution.endpoints) == 2
    tileset_endpoint = next(e for e in resolution.endpoints if e.kind == "3d-tiles")
    assert tileset_endpoint.headers["X-Honua-Scene"] == "downtown-honolulu"
    assert resolution.expires_at == datetime(2026, 4, 28, 2, 0, 0, tzinfo=UTC)
    assert resolution.auth.requires_authentication is True


def test_resolve_scene_raises_when_required_capability_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=RESOLVE_SCENE)

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(HonuaSceneError, match="i3s"):
            client.scenes().resolve_scene("downtown-honolulu", required_capabilities=["i3s"])


def test_resolve_scene_parses_signed_url_access_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=RESOLVE_ACCESS_SCENE)

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        resolution = client.scenes().resolve_scene("protected-downtown")

    access = resolution.access
    assert access is not None
    assert access.mode == HonuaSceneAccessModes.SIGNED_URL
    assert access.is_supported_mode is True
    assert access.is_browser_safe is True
    assert access.cors_mode == "registered-origins"
    assert access.cache.max_age_seconds == 300
    assert access.revocation_key == "scene-rev-42"
    assert access.is_expired(datetime(2026, 4, 28, 19, 0, 0, tzinfo=UTC)) is True
    assert access.is_expired(datetime(2026, 4, 28, 18, 0, 0, tzinfo=UTC)) is False
    assert access.should_refresh(datetime(2026, 4, 28, 18, 25, 0, tzinfo=UTC)) is True


def test_resolve_scene_propagates_access_only_expiry_to_top_level() -> None:
    # When the server advertises expiry only inside the nested ``access``
    # object (no top-level ``expiresAt``), the resolution's ``expires_at``
    # should still surface it so callers driving refresh/expiration timing
    # off the top-level field do not silently miss it.
    access_only_expiry = {
        "sceneId": "protected-downtown",
        "tilesetUrl": "https://cdn.honua.test/scenes/protected-downtown/tileset.json?sig=render",
        "capabilities": ["3d-tiles"],
        "auth": {"requiresAuthentication": True, "schemes": ["SignedUrl"]},
        "access": {
            "mode": "signed-url",
            "expiresAtUtc": "2026-04-28T18:30:00Z",
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=access_only_expiry)

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        resolution = client.scenes().resolve_scene("protected-downtown")

    assert resolution.access is not None
    assert resolution.access.expires_at == datetime(2026, 4, 28, 18, 30, 0, tzinfo=UTC)
    assert resolution.expires_at == datetime(2026, 4, 28, 18, 30, 0, tzinfo=UTC)


def test_malformed_scene_metadata_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "missing-id"})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(HonuaSceneError):
            client.scenes().get_scene("nope")


# ---------------------------------------------------------------------------
# Elevation value + profile request/response
# ---------------------------------------------------------------------------


def test_elevation_value_request_and_parse() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"raw_path": request.url.raw_path.decode("ascii").split("?")[0], "query": dict(request.url.params.multi_items())})
        return httpx.Response(200, json=ELEVATION_VALUE)

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        value = client.elevation().value("honolulu-dem", x=-157.8583, y=21.3069, srid=4326)

    assert seen[0]["raw_path"] == "/elevation/honolulu-dem/value"
    assert seen[0]["query"]["x"] == "-157.8583"
    assert seen[0]["query"]["y"] == "21.3069"
    assert seen[0]["query"]["srid"] == "4326"
    assert value.dataset_id == "honolulu-dem"
    assert value.elevation == pytest.approx(12.5)
    assert value.no_data is False
    assert value.out_of_bounds is False
    assert value.mosaic_rule == "first"
    assert value.source.raster_ids == (101, 102)
    assert value.source.raster_count == 2
    assert value.source.vertical_unit == "meter"
    assert value.source.vertical_datum == "EGM2008"


def test_elevation_profile_request_and_parse() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"raw_path": request.url.raw_path.decode("ascii").split("?")[0], "query": dict(request.url.params.multi_items())})
        return httpx.Response(200, json=ELEVATION_PROFILE)

    line = "LINESTRING(-157.86 21.30, -157.85 21.31)"
    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        profile = client.elevation().profile("honolulu-dem", line=line, sample_count=3)

    assert seen[0]["raw_path"] == "/elevation/honolulu-dem/profile"
    assert seen[0]["query"]["line"] == line
    assert seen[0]["query"]["sampleCount"] == "3"
    assert profile.sample_count == 3
    assert profile.line_length_meters == pytest.approx(250.0)
    assert profile.line_srid == 4326
    assert profile.is_all_no_data is False
    assert len(profile.samples) == 3
    assert profile.samples[0].distance_meters == pytest.approx(0.0)
    assert profile.samples[1].elevation == pytest.approx(22.5)
    assert profile.samples[2].elevation is None
    assert profile.samples[2].no_data is True
    assert profile.source.raster_ids == (101,)


# ---------------------------------------------------------------------------
# Offline scene-package manifest parse + SHA256 validation
# ---------------------------------------------------------------------------


def test_parse_package_manifest_typed_fields() -> None:
    manifest = parse_scene_package_manifest(_valid_manifest_dict())
    assert manifest.schema_version == CURRENT_PACKAGE_SCHEMA_VERSION
    assert manifest.package_id == "pkg_downtown_honolulu_2026_04"
    assert manifest.scene_id == "downtown-honolulu"
    assert manifest.edition_gate == "pro"
    assert manifest.created_at_utc == datetime(2026, 4, 28, tzinfo=UTC)
    assert manifest.extent is not None
    assert manifest.extent.min_longitude == pytest.approx(-157.872)
    assert manifest.lod is not None and manifest.lod.min_zoom == 12
    assert manifest.byte_budget is not None
    assert manifest.byte_budget.max_package_bytes == 2147483648
    assert manifest.attribution == ("Honua", "City and County source data")
    assert len(manifest.assets) == 3
    assert manifest.assets[0].type == "scene-metadata"
    assert manifest.assets[0].required is True


def test_parse_package_manifest_accepts_json_text_and_bytes() -> None:
    import json

    text = json.dumps(_valid_manifest_dict())
    assert parse_scene_package_manifest(text).scene_id == "downtown-honolulu"
    assert parse_scene_package_manifest(text.encode("utf-8")).scene_id == "downtown-honolulu"


def test_parse_package_manifest_rejects_blank_and_malformed() -> None:
    with pytest.raises(HonuaScenePackageError):
        parse_scene_package_manifest("")
    with pytest.raises(HonuaScenePackageError):
        parse_scene_package_manifest("{not json")
    with pytest.raises(HonuaScenePackageError):
        parse_scene_package_manifest("[1, 2, 3]")


def test_validate_package_manifest_passes_for_valid_manifest() -> None:
    data = _valid_manifest_dict()
    # Keep auth credentials valid so the only finding (if any) is structural.
    data["authExpiresAtUtc"] = "2026-12-31T00:00:00Z"
    manifest = parse_scene_package_manifest(data)
    result = manifest.validate(_NOW)
    assert result.is_valid is True
    assert result.state == HonuaScenePackageState.READY
    assert result.has_warnings is False


def test_validate_package_manifest_auth_expired_warning_keeps_ready() -> None:
    # Fixture authExpiresAtUtc (2026-04-29) is before _NOW (2026-05-01): a
    # non-blocking warning that does not change the READY state.
    manifest = parse_scene_package_manifest(_valid_manifest_dict())
    result = manifest.validate(_NOW)
    assert result.state == HonuaScenePackageState.READY
    assert result.is_valid is True
    assert result.has_warnings is True
    codes = {issue.code for issue in result.issues}
    assert HonuaScenePackageValidationCodes.AUTH_EXPIRED in codes


def test_validate_package_manifest_detects_invalid_sha256() -> None:
    data = _valid_manifest_dict()
    # not 64 hex chars, not valid base64-of-32-bytes
    data["assets"][0]["sha256"] = "not-a-valid-digest"
    manifest = parse_scene_package_manifest(data)
    result = manifest.validate(_NOW)
    assert result.is_valid is False
    assert result.state == HonuaScenePackageState.INVALID
    codes = {issue.code for issue in result.issues}
    assert HonuaScenePackageValidationCodes.INVALID_ASSET_HASH in codes
    hash_issue = next(i for i in result.issues if i.code == HonuaScenePackageValidationCodes.INVALID_ASSET_HASH)
    assert hash_issue.asset_key == "scene-metadata"


def test_validate_package_manifest_accepts_base64_sha256() -> None:
    import base64

    data = _valid_manifest_dict()
    data["assets"][0]["sha256"] = base64.b64encode(b"\x00" * 32).decode("ascii")
    manifest = parse_scene_package_manifest(data)
    result = manifest.validate(_NOW)
    assert result.is_valid is True


def test_validate_package_manifest_flags_unsupported_schema_and_edition() -> None:
    data = _valid_manifest_dict()
    data["schemaVersion"] = "honua.scene-package.v0"
    data["editionGate"] = "ultimate"
    result = parse_scene_package_manifest(data).validate(_NOW)
    codes = {issue.code for issue in result.issues}
    assert HonuaScenePackageValidationCodes.UNSUPPORTED_SCHEMA_VERSION in codes
    assert HonuaScenePackageValidationCodes.UNSUPPORTED_EDITION_GATE in codes
    assert result.state == HonuaScenePackageState.INVALID


def test_validate_package_manifest_expired_offline_use() -> None:
    manifest = parse_scene_package_manifest(_valid_manifest_dict())
    after_expiry = datetime(2026, 7, 1, tzinfo=UTC)
    result = manifest.validate(after_expiry)
    assert result.state == HonuaScenePackageState.EXPIRED
    codes = {issue.code for issue in result.issues}
    assert HonuaScenePackageValidationCodes.OFFLINE_USE_EXPIRED in codes


def test_validate_package_manifest_stale_warning() -> None:
    manifest = parse_scene_package_manifest(_valid_manifest_dict())
    stale_time = datetime(2026, 6, 1, tzinfo=UTC)  # after stale, before offline-use expiry
    result = manifest.validate(stale_time)
    assert result.state == HonuaScenePackageState.STALE
    assert result.has_warnings is True
    assert result.is_valid is True


def test_validate_package_manifest_partial_when_required_asset_missing() -> None:
    manifest = parse_scene_package_manifest(_valid_manifest_dict())
    # Only the tileset present locally; required scene-metadata asset missing.
    result = manifest.validate(_NOW, available_asset_keys=["buildings-tileset"])
    assert result.state == HonuaScenePackageState.PARTIAL
    codes = {issue.code for issue in result.issues}
    assert HonuaScenePackageValidationCodes.MISSING_REQUIRED_ASSET in codes


def test_validate_package_manifest_requires_scene_metadata_asset() -> None:
    data = _valid_manifest_dict()
    # Drop the required scene-metadata asset.
    data["assets"] = [a for a in data["assets"] if a["type"] != "scene-metadata"]
    result = parse_scene_package_manifest(data).validate(_NOW)
    codes = {issue.code for issue in result.issues}
    assert HonuaScenePackageValidationCodes.MISSING_REQUIRED_SCENE_METADATA in codes
    assert result.state == HonuaScenePackageState.INVALID


def test_validate_package_manifest_rejects_unsafe_asset_path() -> None:
    data = _valid_manifest_dict()
    data["assets"][1]["path"] = "../escape/tileset.json"
    result = parse_scene_package_manifest(data).validate(_NOW)
    codes = {issue.code for issue in result.issues}
    assert HonuaScenePackageValidationCodes.INVALID_ASSET_PATH in codes


def test_validate_package_manifest_over_byte_budget() -> None:
    data = _valid_manifest_dict()
    data["byteBudget"]["maxPackageBytes"] = 5000
    data["byteBudget"]["declaredBytes"] = 100000
    result = parse_scene_package_manifest(data).validate(_NOW)
    codes = {issue.code for issue in result.issues}
    assert HonuaScenePackageValidationCodes.OVER_BYTE_BUDGET in codes


def test_async_scene_and_elevation_factories_exist() -> None:
    from honua_sdk import AsyncHonuaClient
    from honua_sdk.protocols import AsyncElevationClient, AsyncSceneClient

    client = AsyncHonuaClient("http://example.test")
    assert isinstance(client.scenes(), AsyncSceneClient)
    assert isinstance(client.elevation(), AsyncElevationClient)


@pytest.mark.anyio
async def test_async_resolve_scene_round_trips() -> None:
    from honua_sdk import AsyncHonuaClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=RESOLVE_SCENE)

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        resolution = await client.scenes().resolve_scene("downtown-honolulu")

    assert resolution.scene_id == "downtown-honolulu"
    assert resolution.tileset_url is not None


# ---------------------------------------------------------------------------
# 3D Tiles tileset traversal + tile fetch + offline package build
# ---------------------------------------------------------------------------

# A small 3D Tiles 1.1 tileset: root content + two children, one of which is a
# nested external tileset that itself references another tile.
ROOT_TILESET = {
    "asset": {"version": "1.1"},
    "geometricError": 500.0,
    "root": {
        "geometricError": 100.0,
        "content": {"uri": "tiles/0.b3dm"},
        "children": [
            {"geometricError": 50.0, "content": {"uri": "tiles/1.b3dm"}},
            {"geometricError": 50.0, "content": {"uri": "sub/tileset.json"}},
        ],
    },
}

SUB_TILESET = {
    "asset": {"version": "1.1"},
    "root": {"geometricError": 10.0, "content": {"uri": "2.b3dm"}},
}

# Per-path binary/JSON payloads served by the package-build mock transport.
SCENE_ASSET_BODIES: dict[str, bytes] = {
    "/scenes/downtown-honolulu/tileset.json": json.dumps(ROOT_TILESET).encode("utf-8"),
    "/scenes/downtown-honolulu/tiles/0.b3dm": b"b3dm-root-tile-bytes",
    "/scenes/downtown-honolulu/tiles/1.b3dm": b"b3dm-child-tile-bytes",
    "/scenes/downtown-honolulu/sub/tileset.json": json.dumps(SUB_TILESET).encode("utf-8"),
    "/scenes/downtown-honolulu/sub/2.b3dm": b"b3dm-nested-tile-bytes",
}


def _scene_asset_handler(seen: list[str]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append(path)
        if path == "/api/scenes/downtown-honolulu":
            return httpx.Response(200, json=SCENE_METADATA)
        body = SCENE_ASSET_BODIES.get(path)
        if body is None:
            return httpx.Response(404, json={"error": "not found"})
        media = "application/json" if path.endswith(".json") else "application/octet-stream"
        return httpx.Response(200, content=body, headers={"content-type": media, "etag": f'"{len(body)}"'})

    return handler


def test_enumerate_tileset_contents_walks_root_and_children() -> None:
    contents = enumerate_tileset_contents(ROOT_TILESET)
    paths = [c.resolved_path for c in contents]
    assert paths == ["tiles/0.b3dm", "tiles/1.b3dm", "sub/tileset.json"]
    nested = next(c for c in contents if c.resolved_path == "sub/tileset.json")
    assert nested.is_tileset is True
    assert contents[0].is_tileset is False


def test_enumerate_tileset_contents_resolves_relative_to_base_path() -> None:
    contents = enumerate_tileset_contents(SUB_TILESET, base_path="sub/tileset.json")
    assert [c.resolved_path for c in contents] == ["sub/2.b3dm"]


def test_enumerate_tileset_contents_supports_multiple_contents_array() -> None:
    tileset = {
        "root": {
            "contents": [
                {"uri": "a.b3dm"},
                {"uri": "b.glb"},
            ]
        }
    }
    assert [c.resolved_path for c in enumerate_tileset_contents(tileset)] == ["a.b3dm", "b.glb"]


def test_enumerate_tileset_contents_empty_without_root() -> None:
    assert enumerate_tileset_contents({"asset": {"version": "1.1"}}) == ()


def test_get_tileset_fetches_document() -> None:
    seen: list[str] = []
    with HonuaClient("http://example.test", transport=httpx.MockTransport(_scene_asset_handler(seen))) as client:
        tileset = client.scenes().get_tileset("downtown-honolulu")
    assert seen == ["/scenes/downtown-honolulu/tileset.json"]
    assert tileset["asset"]["version"] == "1.1"
    assert tileset["root"]["content"]["uri"] == "tiles/0.b3dm"


def test_fetch_tile_returns_binary_with_metadata() -> None:
    seen: list[str] = []
    with HonuaClient("http://example.test", transport=httpx.MockTransport(_scene_asset_handler(seen))) as client:
        response = client.scenes().fetch_tile("downtown-honolulu", "tiles/0.b3dm")
    assert seen == ["/scenes/downtown-honolulu/tiles/0.b3dm"]
    assert response.content == b"b3dm-root-tile-bytes"
    assert response.content_type == "application/octet-stream"
    assert response.etag == '"20"'


def test_build_offline_package_bundles_tileset_and_tiles() -> None:
    seen: list[str] = []
    now = datetime(2026, 6, 1, tzinfo=UTC)
    with HonuaClient("http://example.test", transport=httpx.MockTransport(_scene_asset_handler(seen))) as client:
        result = client.scenes().build_offline_package(
            "downtown-honolulu",
            edition_gate="pro",
            created_at_utc=now,
        )

    manifest = result.manifest
    assert manifest.schema_version == CURRENT_PACKAGE_SCHEMA_VERSION
    assert manifest.scene_id == "downtown-honolulu"
    assert manifest.edition_gate == "pro"
    # extent carried over from the scene metadata bounds
    assert manifest.extent is not None
    assert manifest.extent.min_longitude == pytest.approx(-157.875)

    keys = {asset.key for asset in manifest.assets}
    # scene-metadata + root tileset + 2 root-level b3dm + nested tileset + nested b3dm
    assert "scene-metadata" in keys
    assert "tileset" in keys
    assert "tiles/0.b3dm" in keys
    assert "tiles/1.b3dm" in keys
    assert "sub/tileset.json" in keys
    assert "sub/2.b3dm" in keys

    # nested tileset was fetched and recursed into
    assert "/scenes/downtown-honolulu/sub/2.b3dm" in seen

    # every asset carries a real SHA-256 + byte count
    nested_tile = result.asset_for("sub/2.b3dm")
    assert nested_tile is not None
    assert nested_tile.content == b"b3dm-nested-tile-bytes"
    assert nested_tile.asset.bytes == len(b"b3dm-nested-tile-bytes")
    assert nested_tile.asset.type == HonuaScenePackageAssetTypes.THREE_D_TILE_CONTENT
    assert len(nested_tile.asset.sha256 or "") == 64

    tileset_asset = result.asset_for("tileset")
    assert tileset_asset is not None
    assert tileset_asset.asset.type == HonuaScenePackageAssetTypes.THREE_D_TILESET

    assert result.total_bytes == sum(a.bytes or 0 for a in manifest.assets)

    # the produced manifest is self-consistent and validates as READY when all
    # asset keys are present locally.
    validation = manifest.validate(now, available_asset_keys=[a.key or "" for a in manifest.assets])
    assert validation.is_valid is True
    assert validation.state == HonuaScenePackageState.READY


def test_build_offline_package_deduplicates_shared_tile_content() -> None:
    # Two children referencing the same content URI must be downloaded once.
    shared_tileset = {
        "asset": {"version": "1.1"},
        "root": {
            "content": {"uri": "tiles/0.b3dm"},
            "children": [
                {"content": {"uri": "tiles/shared.b3dm"}},
                {"content": {"uri": "tiles/shared.b3dm"}},
            ],
        },
    }
    bodies = {
        "/api/scenes/downtown-honolulu": None,
        "/scenes/downtown-honolulu/tileset.json": json.dumps(shared_tileset).encode("utf-8"),
        "/scenes/downtown-honolulu/tiles/0.b3dm": b"root",
        "/scenes/downtown-honolulu/tiles/shared.b3dm": b"shared",
    }
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append(path)
        if path == "/api/scenes/downtown-honolulu":
            return httpx.Response(200, json=SCENE_METADATA)
        body = bodies[path]
        assert body is not None
        media = "application/json" if path.endswith(".json") else "application/octet-stream"
        return httpx.Response(200, content=body, headers={"content-type": media})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        result = client.scenes().build_offline_package(
            "downtown-honolulu", edition_gate="community", created_at_utc=datetime(2026, 6, 1, tzinfo=UTC)
        )

    assert seen.count("/scenes/downtown-honolulu/tiles/shared.b3dm") == 1
    keys = [a.key for a in result.manifest.assets]
    assert keys.count("tiles/shared.b3dm") == 1


def test_build_offline_package_raises_on_malformed_tileset() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii").split("?")[0]
        if path == "/api/scenes/downtown-honolulu":
            return httpx.Response(200, json=SCENE_METADATA)
        return httpx.Response(200, content=b"{ not json", headers={"content-type": "application/json"})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(HonuaSceneError, match="tileset.json"):
            client.scenes().build_offline_package(
                "downtown-honolulu", edition_gate="community", created_at_utc=datetime(2026, 6, 1, tzinfo=UTC)
            )


def test_build_offline_package_rejects_unsupported_edition_gate() -> None:
    with HonuaClient("http://example.test", transport=httpx.MockTransport(_scene_asset_handler([]))) as client:
        with pytest.raises(ValueError, match="edition gate"):
            client.scenes().build_offline_package("downtown-honolulu", edition_gate="ultimate")


def test_build_offline_package_respects_max_tilesets() -> None:
    seen: list[str] = []
    with HonuaClient("http://example.test", transport=httpx.MockTransport(_scene_asset_handler(seen))) as client:
        result = client.scenes().build_offline_package(
            "downtown-honolulu",
            edition_gate="community",
            created_at_utc=datetime(2026, 6, 1, tzinfo=UTC),
            max_tilesets=1,
        )
    keys = {asset.key for asset in result.manifest.assets}
    # The nested tileset reference is still downloaded as an asset, but with
    # max_tilesets=1 we do not recurse into it, so its child tile is absent.
    assert "sub/tileset.json" in keys
    assert "sub/2.b3dm" not in keys
    assert "/scenes/downtown-honolulu/sub/2.b3dm" not in seen


@pytest.mark.anyio
async def test_async_build_offline_package_bundles_tileset_and_tiles() -> None:
    from honua_sdk import AsyncHonuaClient

    seen: list[str] = []
    async with AsyncHonuaClient(
        "http://example.test", transport=httpx.MockTransport(_scene_asset_handler(seen))
    ) as client:
        result = await client.scenes().build_offline_package(
            "downtown-honolulu",
            edition_gate="pro",
            created_at_utc=datetime(2026, 6, 1, tzinfo=UTC),
        )
    keys = {asset.key for asset in result.manifest.assets}
    assert {"scene-metadata", "tileset", "tiles/0.b3dm", "sub/2.b3dm"} <= keys


@pytest.mark.anyio
async def test_async_get_tileset_and_fetch_tile() -> None:
    from honua_sdk import AsyncHonuaClient

    seen: list[str] = []
    async with AsyncHonuaClient(
        "http://example.test", transport=httpx.MockTransport(_scene_asset_handler(seen))
    ) as client:
        tileset = await client.scenes().get_tileset("downtown-honolulu")
        response = await client.scenes().fetch_tile("downtown-honolulu", "tiles/1.b3dm")
    assert tileset["asset"]["version"] == "1.1"
    assert response.content == b"b3dm-child-tile-bytes"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
