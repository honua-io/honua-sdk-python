"""HonuaSession configure() behavior, including cache invalidation."""

from __future__ import annotations

from typing import Any

import honua_gp
from honua_gp._session import get_session


def test_configure_invalidates_lazy_client_cache_on_base_url_change() -> None:
    """Changing ``base_url`` must drop any previously cached client so the
    next ``client()`` call rebuilds against the new endpoint. Without this,
    code that runs after a reconfigure keeps sending traffic to the old
    deployment.
    """

    session = get_session()
    first = object()
    honua_gp.configure(base_url="https://a.example.com", api_key="k1", client=first)
    assert session._client is first  # noqa: SLF001 -- intentional white-box check
    assert session._admin is None  # noqa: SLF001
    assert session._processes is None  # noqa: SLF001

    honua_gp.configure(base_url="https://b.example.com")
    assert session._client is None, "Base URL changed; cached client must be dropped"  # noqa: SLF001
    assert session._admin is None  # noqa: SLF001
    assert session._processes is None  # noqa: SLF001


def test_configure_invalidates_lazy_admin_on_api_key_change() -> None:
    """Updating ``api_key`` must invalidate the cached admin client too --
    not just the data client -- because the admin client also reads
    ``api_key`` when it's lazily built.
    """

    session = get_session()
    sentinel_admin = object()
    honua_gp.configure(
        base_url="https://a.example.com",
        api_key="initial",
        admin_client=sentinel_admin,
    )
    assert session._admin is sentinel_admin  # noqa: SLF001

    honua_gp.configure(api_key="rotated")
    assert session._admin is None, "api_key changed; cached admin must be dropped"  # noqa: SLF001


def test_configure_invalidates_lazy_processes_on_bearer_token_change() -> None:
    """Bearer-token rotations must invalidate the cached OGC Processes
    client. The processes client is derived from the data client, which is
    constructed with the bearer token; a stale processes cache would keep
    using the old credential.
    """

    session = get_session()
    sentinel_processes = object()
    honua_gp.configure(
        base_url="https://a.example.com",
        bearer_token="initial-bearer",
        processes_client=sentinel_processes,
    )
    assert session._processes is sentinel_processes  # noqa: SLF001

    honua_gp.configure(bearer_token="rotated-bearer")
    assert session._processes is None  # noqa: SLF001


def test_configure_invalidates_on_extra_client_options_change() -> None:
    """Extra client kwargs forwarded via ``**client_kwargs`` are part of the
    connection settings, so changes to them must also drop the cached
    clients."""

    session = get_session()
    first = object()
    honua_gp.configure(base_url="https://a.example.com", client=first)
    assert session._client is first  # noqa: SLF001

    honua_gp.configure(timeout=30.0)
    assert session._client is None, "extra client kwargs changed; cached client must be dropped"  # noqa: SLF001


def test_configure_explicit_client_wins_after_invalidation() -> None:
    """If a caller passes both a connection-setting change *and* an explicit
    ``client=``, the explicit client must survive (it is applied after the
    cache invalidation in the same lock-held call).
    """

    session = get_session()
    first = object()
    honua_gp.configure(base_url="https://a.example.com", client=first)
    assert session._client is first  # noqa: SLF001

    second = object()
    honua_gp.configure(base_url="https://b.example.com", client=second)
    assert session._client is second, "Explicit client= must win in the same call"  # noqa: SLF001


def test_configure_forwards_extra_client_options_to_admin_client(monkeypatch) -> None:
    """``configure(..., timeout=..., transport=...)`` documents that the extra
    kwargs reach the underlying SDK constructors. Before the fix,
    ``_build_admin_client`` started with an empty kwargs dict, so options
    such as ``transport``, ``timeout``, ``auth_provider``, ``follow_redirects``,
    and ``max_retries`` were silently dropped for the admin client even
    though the data client honoured them.
    """

    captured: dict[str, Any] = {}

    class _StubAdminClient:
        def __init__(self, base_url: str, **kwargs: Any) -> None:
            captured["base_url"] = base_url
            captured["kwargs"] = dict(kwargs)

    # ``_build_admin_client`` does a late import; patch the module the import
    # resolves to.
    import honua_admin

    monkeypatch.setattr(honua_admin, "HonuaAdminClient", _StubAdminClient)

    sentinel_transport = object()
    honua_gp.configure(
        base_url="https://example.com",
        api_key="k",
        timeout=42.0,
        transport=sentinel_transport,
        max_retries=7,
    )

    session = get_session()
    # Force the lazy admin build.
    built = session.admin_client()
    assert isinstance(built, _StubAdminClient)

    assert captured["base_url"] == "https://example.com"
    assert captured["kwargs"]["api_key"] == "k"
    assert captured["kwargs"]["timeout"] == 42.0
    assert captured["kwargs"]["transport"] is sentinel_transport
    assert captured["kwargs"]["max_retries"] == 7


def test_configure_idempotent_does_not_invalidate_cache() -> None:
    """Re-passing the same connection settings is a no-op and must not
    invalidate cached clients. Without this guard a benign double-configure
    (e.g. ``configure_from_env`` followed by a redundant manual configure)
    would silently drop pre-built test clients.
    """

    session = get_session()
    sentinel = object()
    honua_gp.configure(
        base_url="https://a.example.com",
        api_key="k",
        bearer_token="b",
        client=sentinel,
    )
    assert session._client is sentinel  # noqa: SLF001

    honua_gp.configure(base_url="https://a.example.com", api_key="k", bearer_token="b")
    assert session._client is sentinel, "Idempotent configure must not invalidate cache"  # noqa: SLF001


def test_configure_idempotent_client_kwargs_do_not_invalidate_cache() -> None:
    session = get_session()
    sentinel = object()
    honua_gp.configure(base_url="https://a.example.com", timeout=30.0, client=sentinel)
    assert session._client is sentinel  # noqa: SLF001

    honua_gp.configure(timeout=30.0)
    assert session._client is sentinel  # noqa: SLF001
    assert session.extra_client_options == {"timeout": 30.0}
