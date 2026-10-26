"""Credentials are refused over non-loopback plain HTTP unless the caller opts in.

Mirrors the .NET SDK: ``https`` is always fine, ``http`` to ``localhost`` or a
loopback address is fine, and ``http`` to any other host with an API key,
bearer token or auth provider raises unless ``allow_insecure_http=True`` or
``HONUA_ALLOW_INSECURE_HTTP=1``. Anonymous clients are never affected.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from honua_admin import AsyncHonuaAdminClient, HonuaAdminClient

from honua_sdk import AsyncHonuaClient, HonuaClient
from honua_sdk.async_geocoding import AsyncHonuaGeocodingClient
from honua_sdk.auth import StaticAuthProvider
from honua_sdk.geocoding import HonuaGeocodingClient
from honua_sdk.http import INSECURE_HTTP_OPT_IN_ENV, ensure_secure_credential_transport

_SYNC_FACTORIES: list[Callable[..., Any]] = [HonuaClient, HonuaAdminClient, HonuaGeocodingClient]
_ASYNC_FACTORIES: list[Callable[..., Any]] = [AsyncHonuaClient, AsyncHonuaAdminClient, AsyncHonuaGeocodingClient]
_ALL_FACTORIES = _SYNC_FACTORIES + _ASYNC_FACTORIES

_CREDENTIALS: list[dict[str, Any]] = [
    {"api_key": "secret-key"},
    {"bearer_token": "secret-token"},
    {"auth_provider": StaticAuthProvider({"Authorization": "Bearer secret-token"})},
]


@pytest.fixture(autouse=True)
def _no_env_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(INSECURE_HTTP_OPT_IN_ENV, raising=False)


def _build(factory: Callable[..., Any], base_url: str, **kwargs: Any) -> Any:
    transport_cls = httpx.MockTransport
    handler = lambda _request: httpx.Response(200, json={})  # noqa: E731
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return factory(base_url, transport=transport_cls(handler), **kwargs)


def _ids(value: Any) -> str:
    if isinstance(value, dict):
        return next(iter(value))
    return getattr(value, "__name__", str(value))


@pytest.mark.parametrize("factory", _ALL_FACTORIES, ids=_ids)
@pytest.mark.parametrize("credentials", _CREDENTIALS, ids=_ids)
def test_https_with_credentials_is_accepted(factory: Callable[..., Any], credentials: dict[str, Any]) -> None:
    assert _build(factory, "https://api.example.test", **credentials) is not None


@pytest.mark.parametrize("factory", _ALL_FACTORIES, ids=_ids)
@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8080",
        "http://LOCALHOST",
        "http://127.0.0.1:5000",
        "http://127.10.20.30",
        "http://[::1]:8080",
    ],
)
def test_http_loopback_with_credentials_is_accepted(factory: Callable[..., Any], base_url: str) -> None:
    assert _build(factory, base_url, api_key="secret-key") is not None


@pytest.mark.parametrize("factory", _ALL_FACTORIES, ids=_ids)
@pytest.mark.parametrize("credentials", _CREDENTIALS, ids=_ids)
@pytest.mark.parametrize(
    "base_url",
    ["http://api.example.test", "http://10.0.0.5:8080", "http://localhost.example.test", "http://[2001:db8::1]"],
)
def test_http_non_loopback_with_credentials_raises(
    factory: Callable[..., Any], credentials: dict[str, Any], base_url: str
) -> None:
    with pytest.raises(ValueError, match="Refusing to send credentials over plain HTTP") as excinfo:
        _build(factory, base_url, **credentials)
    message = str(excinfo.value)
    assert "allow_insecure_http=True" in message
    assert INSECURE_HTTP_OPT_IN_ENV in message
    assert "secret" not in message


@pytest.mark.parametrize("factory", _ALL_FACTORIES, ids=_ids)
def test_allow_insecure_http_kwarg_opts_in(factory: Callable[..., Any]) -> None:
    assert _build(factory, "http://api.example.test", api_key="secret-key", allow_insecure_http=True) is not None


@pytest.mark.parametrize("factory", _ALL_FACTORIES, ids=_ids)
@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_env_opt_in_allows(factory: Callable[..., Any], value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(INSECURE_HTTP_OPT_IN_ENV, value)
    assert _build(factory, "http://api.example.test", api_key="secret-key") is not None


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_env_opt_in_requires_truthy_value(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(INSECURE_HTTP_OPT_IN_ENV, value)
    with pytest.raises(ValueError, match="plain HTTP"):
        _build(HonuaClient, "http://api.example.test", api_key="secret-key")


@pytest.mark.parametrize("factory", _ALL_FACTORIES, ids=_ids)
def test_http_without_credentials_is_accepted(factory: Callable[..., Any]) -> None:
    assert _build(factory, "http://api.example.test") is not None
    assert _build(factory, "http://api.example.test", api_key="") is not None


def test_loopback_http_still_attaches_credentials() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    with HonuaClient("http://127.0.0.1:8080", api_key="secret-key", transport=httpx.MockTransport(handler)) as client:
        client._client.get("/healthz/ready")
    assert seen[0].headers["X-API-Key"] == "secret-key"


def test_with_options_base_url_rechecks_and_keeps_opt_in() -> None:
    client = _build(HonuaClient, "https://api.example.test", api_key="secret-key")
    with pytest.raises(ValueError, match="plain HTTP"):
        client.with_options(base_url="http://other.example.test")

    opted_in = _build(HonuaClient, "https://api.example.test", api_key="secret-key", allow_insecure_http=True)
    assert opted_in.with_options(base_url="http://other.example.test") is not None


@pytest.mark.anyio
async def test_async_with_options_keeps_opt_in() -> None:
    client = _build(AsyncHonuaClient, "https://api.example.test", api_key="secret-key", allow_insecure_http=True)
    clone = client.with_options(base_url="http://other.example.test")
    await clone.close()
    await client.close()


def test_admin_with_options_rechecks() -> None:
    client = _build(HonuaAdminClient, "https://api.example.test", api_key="secret-key")
    with pytest.raises(ValueError, match="plain HTTP"):
        client.with_options(base_url="http://other.example.test")


def test_helper_accepts_url_objects() -> None:
    ensure_secure_credential_transport(httpx.URL("http://localhost/"), has_credentials=True)
    with pytest.raises(ValueError, match="plain HTTP"):
        ensure_secure_credential_transport(httpx.URL("http://api.example.test/"), has_credentials=True)
