from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest

from scripts import _smoke_harness as smoke


NOW = datetime(2026, 8, 9, 3, 30, tzinfo=timezone.utc)
SERVER_COMMIT = "e" * 40
SERVER_IMAGE = f"ghcr.io/honua-io/honua-server@sha256:{'f' * 64}"
DESCRIPTOR_URL = (
    f"https://raw.githubusercontent.com/honua-io/honua-demo-infra/{'a' * 40}"
    "/manifest/client-compat.v1.json"
)


def descriptor_bytes() -> bytes:
    return (json.dumps(
        {
            "format": "honua.demo.client-compat.v1",
            "schemaVersion": "1.0.0",
            "baseUrl": "https://demo.honua.io",
            "service": {"name": "test_service", "layerId": 68823},
            "access": {"allowAnonymous": False},
            "fixture": {"profile": "client-compat"},
        },
        indent=2,
    ) + "\n").encode()


def binding(*, expires_at: str = "2026-08-16T03:30:00Z") -> dict[str, object]:
    descriptor = descriptor_bytes()
    return {
        "format": "honua.demo.client-compat-deployment.v1",
        "schemaVersion": "1.0.0",
        "generatedAt": "2026-08-09T03:30:00Z",
        "expiresAt": expires_at,
        "owner": {
            "repository": "honua-io/honua-demo-infra",
            "issue": "https://github.com/honua-io/honua-demo-infra/issues/28",
        },
        "descriptor": {
            "format": "honua.demo.client-compat.v1",
            "schemaVersion": "1.0.0",
            "url": DESCRIPTOR_URL,
            "sha256": sha256(descriptor).hexdigest(),
        },
        "target": {
            "baseUrl": "https://demo.honua.io",
            "serviceName": "test_service",
            "layerId": 68823,
            "seedProfile": "client-compat",
            "server": {"commit": SERVER_COMMIT, "image": SERVER_IMAGE},
        },
        "access": {
            "allowAnonymous": False,
            "apiKeyHeader": "X-API-Key",
            "credentialRecorded": False,
        },
        "source": {
            "repository": "honua-io/honua-demo-infra",
            "commit": "a" * 40,
            "workflowRunUrl": "https://github.com/honua-io/honua-demo-infra/actions/runs/1",
        },
    }


def validate(payload: dict[str, object]) -> dict[str, object]:
    return smoke.validate_client_compat_binding(
        json.dumps(payload),
        base_url="https://demo.honua.io",
        service_id="test_service",
        layer_id=68823,
        server_commit=SERVER_COMMIT,
        server_image=SERVER_IMAGE,
        seed_profile="client-compat",
        fetch_descriptor=lambda _url: descriptor_bytes(),
        now=NOW,
    )


def test_valid_binding_records_descriptor_and_canonical_evidence_digest() -> None:
    payload = binding()
    actual = validate(payload)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"

    assert actual["descriptor_url"] == DESCRIPTOR_URL
    assert actual["descriptor_sha256"] == sha256(descriptor_bytes()).hexdigest()
    assert actual["deployment_evidence_sha256"] == sha256(canonical).hexdigest()
    assert actual["expires_at"] == "2026-08-16T03:30:00Z"


def test_binding_fails_closed_when_expired() -> None:
    with pytest.raises(smoke.SmokeConfigError, match="stale"):
        validate(binding(expires_at="2026-08-09T03:29:59Z"))


def test_binding_fails_closed_on_descriptor_digest_mismatch() -> None:
    payload = binding()
    payload["descriptor"]["sha256"] = "0" * 64  # type: ignore[index]
    with pytest.raises(smoke.SmokeConfigError, match="digest mismatch"):
        validate(payload)


def test_binding_fails_closed_on_staging_target_mismatch() -> None:
    payload = binding()
    payload["target"]["layerId"] = 0  # type: ignore[index]
    with pytest.raises(smoke.SmokeConfigError, match="disagrees with staging variables"):
        validate(payload)


def test_remote_config_requires_atomic_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_BASE_URL", "https://demo.honua.io")
    monkeypatch.setenv("HONUA_LOCAL_STACK", "false")
    monkeypatch.delenv("HONUA_CLIENT_COMPAT_BINDING_JSON", raising=False)

    with pytest.raises(smoke.SmokeConfigError, match="is required"):
        smoke.load_smoke_config_from_env()


def test_receipt_target_records_explicit_remote_mode_and_binding() -> None:
    governed = validate(binding())
    config = smoke.SmokeConfig(
        base_url="https://demo.honua.io",
        service_id="test_service",
        layer_id=68823,
        server_commit=SERVER_COMMIT,
        server_image=SERVER_IMAGE,
        seed_profile="client-compat",
        local_stack=False,
        governed_binding=governed,
    )

    target = config.target_dict()
    assert target["local_stack"] is False
    assert target["governed_binding"]["descriptor_url"] == DESCRIPTOR_URL
    assert target["governed_binding"]["deployment_evidence_sha256"]
