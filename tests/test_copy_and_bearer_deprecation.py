"""Tests for the ``copy()`` alias and the ``bearer_token=`` deprecation.

Both items are ergonomic polish from the A+ grading backlog (issue #67):

* ``copy()`` is a stripe-python-style alias for ``with_options()`` on all
  four public clients; it must return the same kind of clone with the same
  transport-sharing semantics.
* The ``bearer_token=`` constructor kwarg is deprecated in favour of the
  single ``auth_provider=`` parameter and must emit a ``DeprecationWarning``
  at construction time (but not on internal ``with_options`` clones).
"""

from __future__ import annotations

import warnings

import httpx
import pytest

from honua_admin import AsyncHonuaAdminClient, HonuaAdminClient
from honua_sdk import HonuaClient, StaticAuthProvider
from honua_sdk.async_client import AsyncHonuaClient

# ---------------------------------------------------------------------------
# copy() alias
# ---------------------------------------------------------------------------


def test_sync_copy_reuses_parent_transport_like_with_options() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"ok": True}))
    with HonuaClient("http://example.test", transport=transport, max_retries=0) as original:
        clone = original.copy(timeout=99.0)
        # Shared-transport clone: identical httpx.Client / connection pool.
        assert clone._client is original._client
        assert clone.readiness() == {"ok": True}


def test_sync_copy_with_base_url_builds_independent_client() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    with HonuaClient("http://example.test", transport=transport, max_retries=0) as original:
        clone = original.copy(base_url="http://other.test")
        try:
            # Independent clone owns its own client (not the parent's).
            assert clone._client is not original._client
            assert clone._base_url == httpx.URL("http://other.test/")
        finally:
            clone.close()


def test_sync_admin_copy_matches_with_options() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    with HonuaAdminClient("http://example.test", transport=transport, max_retries=0) as original:
        clone = original.copy(timeout=99.0)
        assert clone._client is original._client


def test_async_clients_expose_copy() -> None:
    # ``copy`` is a thin synchronous wrapper around ``with_options`` on the
    # async clients too; assert it is present and callable without awaiting
    # network I/O.
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    async_client = AsyncHonuaClient("http://example.test", transport=transport, max_retries=0)
    clone = async_client.copy(timeout=99.0)
    assert clone._client is async_client._client

    admin = AsyncHonuaAdminClient("http://example.test", transport=transport, max_retries=0)
    admin_clone = admin.copy(timeout=99.0)
    assert admin_clone._client is admin._client


# ---------------------------------------------------------------------------
# bearer_token= deprecation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory",
    [
        lambda: HonuaClient("http://example.test", bearer_token="t", max_retries=0),
        lambda: AsyncHonuaClient("http://example.test", bearer_token="t", max_retries=0),
        lambda: HonuaAdminClient("http://example.test", bearer_token="t", max_retries=0),
        lambda: AsyncHonuaAdminClient("http://example.test", bearer_token="t", max_retries=0),
    ],
)
def test_bearer_token_emits_deprecation_warning(factory) -> None:  # type: ignore[no-untyped-def]
    with pytest.warns(DeprecationWarning, match="bearer_token"):
        client = factory()
    # The message must steer callers to the supported replacement.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        factory()
    assert any("auth_provider" in str(w.message) for w in caught)
    del client


def test_auth_provider_does_not_warn() -> None:
    provider = StaticAuthProvider({"Authorization": "Bearer t"})
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        client = HonuaClient("http://example.test", auth_provider=provider, max_retries=0)
        client.close()


def test_with_options_clone_does_not_refire_bearer_warning() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        original = HonuaClient("http://example.test", bearer_token="t", max_retries=0)
        # One warning so far (original construction).
        baseline = sum(1 for w in caught if issubclass(w.category, DeprecationWarning))
        # Internal clone re-forwards bearer_token but must NOT re-warn.
        clone = original.with_options(base_url="http://other.test")
        after = sum(1 for w in caught if issubclass(w.category, DeprecationWarning))
    assert baseline == 1
    assert after == baseline
    clone.close()
    original.close()
