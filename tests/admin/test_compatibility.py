"""Tests for admin compatibility helpers."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from honua_admin import (
    AdminCompatibilityBaseline,
    AdminCompatibilityMetadata,
    AsyncHonuaAdminClient,
    MINIMUM_SUPPORTED_CONTROL_PLANE_API_MAJOR,
    MINIMUM_SUPPORTED_CONTROL_PLANE_BASE_PATH,
    MINIMUM_SUPPORTED_SERVER_RELEASE_CHANNEL,
    MINIMUM_SUPPORTED_SERVER_VERSION,
    evaluate_admin_compatibility,
)

from .conftest import make_api_response

ROOT = Path(__file__).resolve().parents[2]
SERVER_MATRIX_PATH = ROOT / "compatibility" / "server-matrix.json"
REPORTED_SERVER_VERSION = "1.0.0+32809f114c36c951b00beb5fe07a3c7082867909"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("client_mode", ["sync", "async"])
@pytest.mark.parametrize(
    ("overrides", "expected_reasons"),
    [
        ({}, []),
        ({"server_version": "1.0.0"}, []),
        (
            {"major": 2},
            ["Server control-plane API major 2 does not match required 1."],
        ),
        (
            {"base_path": "/api/v2/admin"},
            ["Server control-plane base path '/api/v2/admin' does not match required '/api/v1/admin'."],
        ),
        (
            {"release_channel": "nightly"},
            ["Server release channel 'nightly' is below required 'preview'."],
        ),
    ],
    ids=["reported-build", "bare-ga", "wrong-major", "wrong-path", "nightly"],
)
async def test_reported_ga_server_contract_at_client_boundary(
    make_client, client_mode, overrides, expected_reasons
) -> None:
    """Issue #219: expectations follow the version/API policy, not evaluator output."""
    values = {"server_version": REPORTED_SERVER_VERSION, **overrides}
    payload = _make_capabilities_payload(**values)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/admin/capabilities"
        seen.append(request.url.path)
        return httpx.Response(200, json=make_api_response(payload))

    if client_mode == "sync":
        with make_client(handler) as client:
            result = client.check_compatibility()
    else:
        async with AsyncHonuaAdminClient(
            "http://test.honua.io", transport=httpx.MockTransport(handler)
        ) as async_client:
            result = await async_client.check_compatibility()

    assert seen == ["/api/v1/admin/capabilities"]
    assert result.supported is (not expected_reasons)
    assert result.reasons == expected_reasons
    assert result.warnings == []
    assert result.baseline.minimum_server_version == "1.0.0"
    assert result.compatibility is not None
    assert result.compatibility.server_version == values["server_version"]
    assert result.compatibility.release_channel == overrides.get("release_channel", "stable")
    assert result.compatibility.control_plane_api.major == overrides.get("major", 1)
    assert result.compatibility.control_plane_api.base_path == overrides.get("base_path", "/api/v1/admin")


# Expectations below are computed from the documented version policy, not from
# evaluator output: GA identities are SemVer and supported from 1.0.0; pre-GA
# identities are CalVer and supported from 2026.3.0. Both baselines are keyed off
# the leading component, so a CalVer build is never measured against 1.0.0.
VERSION_POLICY_CASES = [
    (REPORTED_SERVER_VERSION, True, "1.0.0"),
    ("1.0.0", True, "1.0.0"),
    ("1.4.2", True, "1.0.0"),
    ("2026.3.0", True, "2026.3.0"),
    ("2026.4.1-rc.2+ac30266f", True, "2026.3.0"),
    ("0.99.0", False, "1.0.0"),
    ("2026.2.28-preview.1", False, "2026.3.0"),
    ("2026.02.28", False, "2026.3.0"),
    ("2026-02-28", False, "2026.3.0"),
    ("2026.2.28.1", False, "2026.3.0"),
    ("2026.2.0.99+ac30266f", False, "2026.3.0"),
]


@pytest.mark.parametrize(
    ("server_version", "expected_supported", "applicable_minimum"),
    VERSION_POLICY_CASES,
    ids=[case[0] for case in VERSION_POLICY_CASES],
)
def test_version_baseline_follows_release_line_not_string_shape(
    make_client, server_version, expected_supported, applicable_minimum
) -> None:
    """A CalVer identity is held to the CalVer cutoff whatever its component count.

    ``2026.2.28.1`` is a pre-GA build below the 2026.3.0 cutoff. Detecting CalVer
    by string shape let it fall through to the GA 1.0.0 baseline, where its
    year-valued major compared greater and the build was wrongly reported
    supported.
    """
    def handler(_: httpx.Request) -> httpx.Response:
        payload = _make_capabilities_payload(server_version=server_version)
        return httpx.Response(200, json=make_api_response(payload))

    with make_client(handler) as client:
        result = client.check_compatibility()

    assert result.supported is expected_supported
    if expected_supported:
        assert result.reasons == []
    else:
        assert result.reasons == [
            f"Server version {server_version!r} is below required {applicable_minimum!r}."
        ]
    assert result.warnings == []
    assert result.compatibility is not None
    assert result.compatibility.server_version == server_version


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
                {"version": "metadata.honua.io/v2alpha1", "deprecated": False},
                {"version": "metadata.honua.io/v1", "deprecated": True},
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
                "metadataApiVersions": ["metadata.honua.io/v2alpha1", "metadata.honua.io/v1"],
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


def test_check_compatibility_accepts_ga_semver_server(make_client) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        payload = _make_capabilities_payload(server_version="1.0.0+ac30266f")
        return httpx.Response(200, json=make_api_response(payload))

    with make_client(handler) as client:
        result = client.check_compatibility()

    assert result.supported is True
    assert result.reasons == []


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


def test_check_compatibility_rejects_semver_below_baseline(make_client) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        payload = _make_capabilities_payload(server_version="0.99.0-preview.1")
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


def test_server_compatibility_matrix_matches_admin_evaluator() -> None:
    matrix = json.loads(SERVER_MATRIX_PATH.read_text(encoding="utf-8"))
    baseline = AdminCompatibilityBaseline()

    for case in matrix["cases"]:
        raw_compatibility = case["compatibility"]
        compatibility = (
            None
            if raw_compatibility is None
            else AdminCompatibilityMetadata.from_dict(raw_compatibility)
        )
        result = evaluate_admin_compatibility(compatibility, baseline)

        assert result.supported is case["expected"]["supported"], case["name"]
