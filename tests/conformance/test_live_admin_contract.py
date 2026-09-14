"""GA bug-hunt checks against a live trunk Honua Server.

These checks are opt-in so normal package tests do not require a deployment.
They remain intentionally failing while the published SDK/server contract
drifts are open in the hunt.
"""

from __future__ import annotations

import os

import pytest

from honua_admin import HonuaAdminClient


BASE_URL = os.environ.get("HONUA_CONTRACT_LIVE_URL")
API_KEY = os.environ.get("HONUA_CONTRACT_LIVE_API_KEY", "quickstart-admin-password")

pytestmark = [pytest.mark.integration, pytest.mark.conformance]


@pytest.mark.skipif(not BASE_URL, reason="HONUA_CONTRACT_LIVE_URL is not set")
def test_live_admin_server_is_supported_by_published_admin_sdk() -> None:
    with HonuaAdminClient(BASE_URL, api_key=API_KEY) as client:
        result = client.check_compatibility()

    # The trunk server advertises 1.0.0+<sha>; the published admin package
    # currently hard-codes a 2026.3.0 minimum and rejects this actual server.
    assert result.supported, "; ".join(result.reasons)


@pytest.mark.skipif(not BASE_URL, reason="HONUA_CONTRACT_LIVE_URL is not set")
def test_live_admin_api_key_auth_rejects_invalid_credentials() -> None:
    from honua_sdk.http import HonuaAuthError

    with HonuaAdminClient(BASE_URL, api_key="definitely-invalid") as client:
        with pytest.raises(HonuaAuthError) as exc_info:
            client.get_version()

    assert exc_info.value.status_code == 401


@pytest.mark.skipif(not BASE_URL, reason="HONUA_CONTRACT_LIVE_URL is not set")
def test_live_manifest_export_advertised_by_capabilities_is_reachable() -> None:
    with HonuaAdminClient(BASE_URL, api_key=API_KEY) as client:
        capabilities = client.get_capabilities()
        assert capabilities.compatibility is not None
        assert capabilities.compatibility.features.manifest_export is True

        # The server advertises export support, but trunk has removed this v1
        # route. This should return a typed manifest rather than HTTP 404.
        manifest = client.get_manifest()

    assert manifest is not None
