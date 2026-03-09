"""Tests for admin compatibility helpers."""

from __future__ import annotations

import httpx

from honua_sdk.admin import (
    MINIMUM_SUPPORTED_CONTROL_PLANE_API_MAJOR,
    MINIMUM_SUPPORTED_CONTROL_PLANE_BASE_PATH,
    MINIMUM_SUPPORTED_SERVER_RELEASE_CHANNEL,
    MINIMUM_SUPPORTED_SERVER_VERSION,
)

from .conftest import make_api_response


def _make_capabilities_payload(
    *,
    server_version: str = "2026.3.9-preview.1",
    major: int = MINIMUM_SUPPORTED_CONTROL_PLANE_API_MAJOR,
    base_path: str = MINIMUM_SUPPORTED_CONTROL_PLANE_BASE_PATH,
    release_channel: str = "stable",
    deprecated: bool = False,
    metadata_resources: bool = True,
    manifest_export: bool = True,
    manifest_apply: bool = True,
    manifest_dry_run: bool = True,
    manifest_prune: bool = True,
    include_legacy_fields: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "compatibility": {
            "serverVersion": server_version,
            "releaseChannel": release_channel,
            "controlPlaneApi": {
                "major": major,
                "basePath": base_path,
                "deprecated": deprecated,
            },
            "metadataSchemas": [
                {"version": "v1", "deprecated": False},
                {"version": "v1beta1", "deprecated": True},
            ],
            "features": {
                "metadataResources": metadata_resources,
                "manifestExport": manifest_export,
                "manifestApply": manifest_apply,
                "manifestDryRun": manifest_dry_run,
                "manifestPrune": manifest_prune,
            },
        },
    }
    if include_legacy_fields:
        payload.update(
            {
                "metadataApiVersions": ["v1", "v1beta1"],
                "resourceKinds": ["Layer", "Service"],
                "manifestSupported": True,
                "manifestDryRunSupported": True,
                "manifestPruneSupported": True,
            }
        )
    return payload


def test_get_capabilities_parses_nested_compatibility_block(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/admin/capabilities"
        return httpx.Response(
            200,
            json=make_api_response(_make_capabilities_payload(include_legacy_fields=False)),
        )

    with make_client(handler) as client:
        response = client.get_capabilities()

    assert response.compatibility is not None
    assert response.metadata_api_versions == []
    assert response.resource_kinds == []
    assert response.compatibility.control_plane_api.major == 1
    assert response.compatibility.metadata_schemas[1].deprecated is True
    assert response.compatibility.features.manifest_prune is True


def test_check_compatibility_accepts_supported_server(make_client) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_api_response(_make_capabilities_payload()))

    with make_client(handler) as client:
        result = client.check_compatibility()

    assert result.supported is True
    assert result.reasons == []
    assert result.warnings == []
    assert result.baseline.minimum_server_version == MINIMUM_SUPPORTED_SERVER_VERSION
    assert result.baseline.minimum_release_channel == MINIMUM_SUPPORTED_SERVER_RELEASE_CHANNEL


def test_check_compatibility_rejects_major_mismatch(make_client) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        payload = _make_capabilities_payload(major=2)
        return httpx.Response(200, json=make_api_response(payload))

    with make_client(handler) as client:
        result = client.check_compatibility()

    assert result.supported is False
    assert any("major" in reason for reason in result.reasons)


def test_check_compatibility_rejects_server_version_below_baseline(make_client) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        payload = _make_capabilities_payload(server_version="2026.2.28-preview.1")
        return httpx.Response(200, json=make_api_response(payload))

    with make_client(handler) as client:
        result = client.check_compatibility()

    assert result.supported is False
    assert any("below required" in reason for reason in result.reasons)


def test_check_compatibility_rejects_release_channel_below_baseline(make_client) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        payload = _make_capabilities_payload(release_channel="alpha")
        return httpx.Response(200, json=make_api_response(payload))

    with make_client(handler) as client:
        result = client.check_compatibility()

    assert result.supported is False
    assert any("release channel" in reason for reason in result.reasons)


def test_check_compatibility_warns_when_control_plane_api_is_deprecated(make_client) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        payload = _make_capabilities_payload(deprecated=True)
        return httpx.Response(200, json=make_api_response(payload))

    with make_client(handler) as client:
        result = client.check_compatibility()

    assert result.supported is True
    assert any("deprecated" in warning for warning in result.warnings)


def test_get_capability_flags_returns_coarse_feature_support(make_client) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        payload = _make_capabilities_payload(
            metadata_resources=True,
            manifest_export=True,
            manifest_apply=False,
            manifest_dry_run=False,
            manifest_prune=False,
        )
        return httpx.Response(200, json=make_api_response(payload))

    with make_client(handler) as client:
        features = client.get_capability_flags()

    assert features.metadata_resources is True
    assert features.manifest_export is True
    assert features.manifest_apply is False
    assert features.manifest_dry_run is False
    assert features.manifest_prune is False
