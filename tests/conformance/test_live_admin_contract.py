"""Live admin compatibility contract against a running Honua Server (issue #219).

Opt-in: set ``HONUA_CONTRACT_LIVE_URL`` (and an admin ``HONUA_CONTRACT_LIVE_API_KEY``)
and pass ``--run-integration``. The expected verdict is derived from the raw
``/api/v1/admin/capabilities`` payload, read without the SDK, and the server's
versioning contract, then compared with what both admin clients report.
"""

from __future__ import annotations

import os
import re

import httpx
import pytest

# The conformance lane certifies an isolated honua-sdk wheel; skip there rather
# than fail collection when honua-admin is not installed.
honua_admin = pytest.importorskip("honua_admin")

BASE_URL = os.environ.get("HONUA_CONTRACT_LIVE_URL")
API_KEY = os.environ.get("HONUA_CONTRACT_LIVE_API_KEY", "")
# Optional pin, e.g. "2026.1.1", when the target image is known.
EXPECTED_SERVER_VERSION = os.environ.get("HONUA_CONTRACT_LIVE_EXPECTED_SERVER_VERSION")

# honua-server stamps <year>.<release>.<patch>[-prerelease][+build]; older builds 1.0.0+<sha>.
_SERVER_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
_SUPPORTED_CHANNELS = {"preview", "beta", "rc", "stable", "lts"}

pytestmark = [
    pytest.mark.integration,
    pytest.mark.conformance,
    pytest.mark.skipif(not BASE_URL, reason="HONUA_CONTRACT_LIVE_URL is not set"),
]


@pytest.fixture(scope="module")
def raw_compatibility() -> dict[str, object]:
    assert BASE_URL is not None
    response = httpx.get(
        f"{BASE_URL.rstrip('/')}/api/v1/admin/capabilities",
        headers={"X-API-Key": API_KEY},
        timeout=30.0,
    )
    assert response.status_code == 200, response.text
    compatibility = response.json()["data"]["compatibility"]
    assert isinstance(compatibility, dict)
    return compatibility


def test_live_server_identity_matches_versioning_contract(raw_compatibility: dict[str, object]) -> None:
    version = str(raw_compatibility["serverVersion"])
    match = _SERVER_VERSION.fullmatch(version)
    assert match is not None, version
    assert tuple(int(part) for part in match.group(1, 2, 3)) >= (1, 0, 0)
    if EXPECTED_SERVER_VERSION:
        assert version == EXPECTED_SERVER_VERSION
    assert raw_compatibility["releaseChannel"] in _SUPPORTED_CHANNELS
    assert raw_compatibility["controlPlaneApi"] == {"major": 1, "basePath": "/api/v1/admin", "deprecated": False}


def test_live_admin_server_is_supported_by_admin_sdk(raw_compatibility: dict[str, object]) -> None:
    assert BASE_URL is not None
    with honua_admin.HonuaAdminClient(BASE_URL, api_key=API_KEY) as client:
        result = client.check_compatibility()

    assert result.reasons == []
    assert result.supported is True
    assert result.warnings == []
    assert result.compatibility is not None
    assert result.compatibility.server_version == raw_compatibility["serverVersion"]
    assert result.compatibility.release_channel == raw_compatibility["releaseChannel"]
    assert result.compatibility.control_plane_api.major == 1


@pytest.mark.anyio
async def test_live_admin_server_is_supported_by_async_admin_sdk(raw_compatibility: dict[str, object]) -> None:
    assert BASE_URL is not None
    async with honua_admin.AsyncHonuaAdminClient(BASE_URL, api_key=API_KEY) as client:
        result = await client.check_compatibility()

    assert result.reasons == []
    assert result.supported is True
    assert result.compatibility is not None
    assert result.compatibility.server_version == raw_compatibility["serverVersion"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
