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


# ---------------------------------------------------------------------------
# issue #107: auth parsing robustness
# ---------------------------------------------------------------------------


def test_coerce_token_preserves_zero_epoch_expiry() -> None:
    from honua_sdk.auth import _coerce_token

    # A legitimate ``0`` epoch expiry must NOT be dropped by falsy coercion.
    token = _coerce_token({"access_token": "abc", "expires_at": 0})
    assert token.access_token == "abc"
    assert token.expires_at is not None
    assert token.expires_at.timestamp() == 0.0


def test_coerce_token_absent_token_type_defaults_to_bearer() -> None:
    from honua_sdk.auth import _coerce_token

    # BearerToken forbids an empty token_type, so absent/empty both default.
    token = _coerce_token({"access_token": "abc"})
    assert token.token_type == "Bearer"


def test_parse_expires_at_unparseable_iso_returns_none() -> None:
    from honua_sdk.auth import _parse_expires_at

    # A malformed ISO timestamp must degrade to "no known expiry" rather than
    # raising ValueError and crashing token coercion (issue #107.1). On Python
    # 3.11 some valid RFC-3339 forms (e.g. >6-digit fractional seconds) also
    # hit this path.
    assert _parse_expires_at("2026-13-99T99:99:99Z") is None


def test_parse_expires_at_valid_iso_with_z() -> None:
    from honua_sdk.auth import _parse_expires_at

    parsed = _parse_expires_at("2026-01-01T00:00:00Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
