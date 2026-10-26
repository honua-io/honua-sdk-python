"""The session refuses credentials over non-loopback plain HTTP unless opted in."""

from __future__ import annotations

import pytest

import honua_gp
from honua_gp._session import get_session


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HONUA_BASE_URL", "HONUA_API_KEY", "HONUA_BEARER_TOKEN", "HONUA_ALLOW_INSECURE_HTTP"):
        monkeypatch.delenv(name, raising=False)


def _build_both() -> None:
    session = get_session()
    session.client()
    session.admin_client()


@pytest.mark.parametrize("base_url", ["https://gp.example.test", "http://localhost:8080", "http://127.0.0.1"])
def test_secure_or_loopback_urls_build_clients(base_url: str) -> None:
    honua_gp.configure(base_url=base_url, api_key="secret-key")
    _build_both()


@pytest.mark.parametrize("accessor", ["client", "admin_client"])
@pytest.mark.parametrize("credential", [{"api_key": "secret-key"}, {"bearer_token": "secret-token"}])
def test_http_non_loopback_with_credentials_raises_configuration_error(
    accessor: str, credential: dict[str, str]
) -> None:
    honua_gp.configure(base_url="http://gp.example.test", **credential)
    with pytest.raises(honua_gp.HonuaGpConfigurationError, match="plain HTTP") as excinfo:
        getattr(get_session(), accessor)()
    assert "secret" not in str(excinfo.value)


def test_environment_configuration_is_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_BASE_URL", "http://gp.example.test")
    monkeypatch.setenv("HONUA_API_KEY", "secret-key")
    with pytest.raises(honua_gp.HonuaGpConfigurationError, match="HONUA_ALLOW_INSECURE_HTTP"):
        get_session().client()


def test_configure_kwarg_opts_in() -> None:
    honua_gp.configure(base_url="http://gp.example.test", api_key="secret-key", allow_insecure_http=True)
    _build_both()


def test_environment_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_BASE_URL", "http://gp.example.test")
    monkeypatch.setenv("HONUA_API_KEY", "secret-key")
    monkeypatch.setenv("HONUA_ALLOW_INSECURE_HTTP", "1")
    _build_both()


def test_http_without_credentials_is_allowed() -> None:
    honua_gp.configure(base_url="http://gp.example.test")
    _build_both()
