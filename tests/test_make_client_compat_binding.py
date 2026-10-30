from __future__ import annotations

import json
from hashlib import sha256

import pytest

from scripts import _smoke_harness as smoke
from scripts import make_client_compat_binding as maker

COMMIT = "a" * 40
DESCRIPTOR_URL = (
    f"https://raw.githubusercontent.com/honua-io/honua-demo-infra/{'c' * 40}"
    "/manifest/client-compat.v1.json"
)
BASE_URL = "https://staging.example.test"
IMAGE = f"ghcr.io/honua-io/honua-server@sha256:{'b' * 64}"


def descriptor(profile: str | None = "demo") -> bytes:
    return json.dumps({
        "format": smoke.CLIENT_COMPAT_DESCRIPTOR_FORMAT,
        "schemaVersion": "1.0.0",
        "baseUrl": BASE_URL,
        "service": {"name": "svc", "layerId": 0},
        "fixture": {"profile": profile},
        "access": {"allowAnonymous": False},
    }).encode("utf-8")


@pytest.fixture
def staging_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_BASE_URL", BASE_URL)
    monkeypatch.setenv("HONUA_SERVICE_ID", "svc")
    monkeypatch.setenv("HONUA_LAYER_ID", "0")
    monkeypatch.setenv("HONUA_SERVER_COMMIT", COMMIT)
    monkeypatch.setenv("HONUA_SERVER_IMAGE", IMAGE)
    monkeypatch.setenv("HONUA_SEED_PROFILE", "demo")


def test_generated_binding_passes_the_suites_own_validator(staging_env: None) -> None:
    """The point of the generator: it cannot emit something smoke will reject."""
    binding = maker.build(DESCRIPTOR_URL, sha256(descriptor()).hexdigest(), 30)
    summary = smoke.validate_client_compat_binding(
        json.dumps(binding, sort_keys=True, separators=(",", ":")),
        base_url=BASE_URL,
        service_id="svc",
        layer_id=0,
        server_commit=COMMIT,
        server_image=IMAGE,
        seed_profile="demo",
        fetch_descriptor=lambda _url: descriptor(),
    )
    assert summary["descriptor_url"] == DESCRIPTOR_URL
    assert summary["expires_at"] > summary["generated_at"]


def test_window_never_exceeds_the_validators_cap(staging_env: None) -> None:
    """31 days is rejected by the harness, so the default must not reach it."""
    assert maker.MAX_WINDOW_DAYS == 30
    binding = maker.build(DESCRIPTOR_URL, sha256(descriptor()).hexdigest(), 31)
    with pytest.raises(smoke.SmokeConfigError, match="at most 30 days"):
        smoke.validate_client_compat_binding(
            json.dumps(binding),
            base_url=BASE_URL, service_id="svc", layer_id=0,
            server_commit=COMMIT, server_image=IMAGE, seed_profile="demo",
            fetch_descriptor=lambda _url: descriptor(),
        )


def test_binding_target_is_taken_from_the_staging_variables(staging_env: None,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """A binding that disagrees with the variables is the failure being prevented."""
    monkeypatch.setenv("HONUA_SERVICE_ID", "other")
    binding = maker.build(DESCRIPTOR_URL, sha256(descriptor()).hexdigest(), 30)
    assert binding["target"]["serviceName"] == "other"
    with pytest.raises(smoke.SmokeConfigError, match="descriptor target disagrees"):
        smoke.validate_client_compat_binding(
            json.dumps(binding),
            base_url=BASE_URL, service_id="other", layer_id=0,
            server_commit=COMMIT, server_image=IMAGE, seed_profile="demo",
            fetch_descriptor=lambda _url: descriptor(),
        )


def test_missing_staging_variable_is_a_clear_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HONUA_BASE_URL", raising=False)
    with pytest.raises(SystemExit, match="HONUA_BASE_URL is not set"):
        maker.required_env("HONUA_BASE_URL")


def _expired(binding: dict) -> str:
    binding["generatedAt"] = "2020-01-01T00:00:00Z"
    binding["expiresAt"] = "2020-01-31T00:00:00Z"
    return json.dumps(binding)


def test_renew_replaces_an_expired_binding_from_the_current_staging_variables(
    staging_env: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale clock must not keep the suite red, and stale target fields must not survive."""
    stale_binding = maker.build(DESCRIPTOR_URL, sha256(descriptor()).hexdigest(), 30)
    stale_binding["target"]["serviceName"] = "stale-service"
    stale_binding["target"]["server"]["image"] = f"ghcr.io/honua-io/honua-server@sha256:{'d' * 64}"
    stale = _expired(stale_binding)
    with pytest.raises(smoke.SmokeConfigError, match="expiresAt has passed"):
        smoke.validate_client_compat_binding(
            stale,
            base_url=BASE_URL, service_id="svc", layer_id=0,
            server_commit=COMMIT, server_image=IMAGE, seed_profile="demo",
            fetch_descriptor=lambda _url: descriptor(),
        )

    current_image = f"ghcr.io/honua-io/honua-server@sha256:{'e' * 64}"
    monkeypatch.setenv("HONUA_SERVER_IMAGE", current_image)
    renewed = maker.renew(stale, fetch_descriptor=lambda _url: descriptor())
    parsed = json.loads(renewed)
    assert parsed["descriptor"]["url"] == DESCRIPTOR_URL
    assert parsed["target"]["serviceName"] == "svc"
    assert parsed["target"]["server"]["image"] == current_image
    assert parsed["target"]["server"]["commit"] == COMMIT
    summary = smoke.validate_client_compat_binding(
        renewed,
        base_url=BASE_URL, service_id="svc", layer_id=0,
        server_commit=COMMIT, server_image=current_image, seed_profile="demo",
        fetch_descriptor=lambda _url: descriptor(),
    )
    assert summary["expires_at"] > summary["generated_at"]


def test_renew_rejects_a_descriptor_that_disagrees_with_staging(staging_env: None) -> None:
    """Renewal must not extend a window whose descriptor no longer matches the target."""
    stale = _expired(maker.build(DESCRIPTOR_URL, sha256(descriptor()).hexdigest(), 30))
    disagreed = descriptor(profile="demo")
    payload = json.loads(disagreed)
    payload["service"]["name"] = "other"
    disagreed = json.dumps(payload).encode("utf-8")
    with pytest.raises(smoke.SmokeConfigError, match="descriptor target disagrees"):
        maker.renew(stale, fetch_descriptor=lambda _url: disagreed)
