from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from honua_sdk import (
    BearerToken,
    CallableAuthProvider,
    InMemoryTokenStore,
    RefreshableBearerTokenProvider,
)


def test_refreshable_bearer_provider_refreshes_expiring_token() -> None:
    refreshed = BearerToken.from_expires_in("fresh-token", 3600)
    calls = 0

    def refresh() -> BearerToken:
        nonlocal calls
        calls += 1
        return refreshed

    provider = RefreshableBearerTokenProvider(
        refresh,
        initial_token=BearerToken(
            "old-token",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=10),
        ),
        refresh_window_seconds=60,
    )

    assert provider.auth_headers() == {"Authorization": "Bearer fresh-token"}
    assert provider.auth_headers() == {"Authorization": "Bearer fresh-token"}
    assert calls == 1


def test_refreshable_bearer_provider_reuses_non_expiring_token() -> None:
    def refresh() -> BearerToken:
        raise AssertionError("refresh should not be called for a non-expiring cached token")

    provider = RefreshableBearerTokenProvider(
        refresh,
        initial_token=BearerToken("cached-token"),
    )

    assert provider.auth_headers() == {"Authorization": "Bearer cached-token"}


def test_refreshable_bearer_provider_revokes_and_clears_cached_token() -> None:
    revoked: list[str] = []
    token_store = InMemoryTokenStore(BearerToken("cached-token"))

    provider = RefreshableBearerTokenProvider(
        lambda: {"access_token": "new-token", "expires_in": 3600},
        token_store=token_store,
        revoke=lambda token: revoked.append(token.access_token),
    )

    provider.revoke()

    assert revoked == ["cached-token"]
    assert token_store.get() is None
    assert provider.auth_headers() == {"Authorization": "Bearer new-token"}


def test_callable_auth_provider_rejects_non_auth_headers() -> None:
    provider = CallableAuthProvider(lambda: {"X-Not-Auth": "value"})

    with pytest.raises(ValueError, match="Unsupported auth header"):
        provider.auth_headers()


def test_bearer_token_accepts_epoch_and_iso_expiration_metadata() -> None:
    epoch_token = RefreshableBearerTokenProvider(
        lambda: {"access_token": "epoch", "expires_at": 2_000_000_000}
    ).get_token()
    iso_token = RefreshableBearerTokenProvider(
        lambda: {"accessToken": "iso", "expiresAt": "2033-05-18T03:33:20Z"}
    ).get_token()

    assert epoch_token.expires_at == datetime.fromtimestamp(2_000_000_000, tz=timezone.utc)
    assert iso_token.access_token == "iso"
    assert iso_token.expires_at is not None
    assert iso_token.expires_at.tzinfo is not None


def test_bearer_token_preserves_falsy_expiration_metadata() -> None:
    token = RefreshableBearerTokenProvider(lambda: {"access_token": "epoch", "expiresAt": 0}).get_token()

    assert token.expires_at == datetime.fromtimestamp(0, tz=timezone.utc)


def test_bearer_token_degrades_unexpected_iso_expiration_to_none() -> None:
    token = RefreshableBearerTokenProvider(
        lambda: {"access_token": "odd-iso", "expiresAt": "2033-05-18T03:33:20+00:00[UTC]"}
    ).get_token()

    assert token.expires_at is None


def test_bearer_token_does_not_replace_explicit_empty_token_type() -> None:
    provider = RefreshableBearerTokenProvider(lambda: {"access_token": "token", "token_type": ""})

    with pytest.raises(ValueError, match="token_type must be non-empty"):
        provider.get_token()
