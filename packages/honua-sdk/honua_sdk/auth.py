"""Authentication helpers for refreshable Honua SDK credentials."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any, Protocol, runtime_checkable

SENSITIVE_AUTH_HEADER_NAMES = frozenset({"authorization", "x-api-key"})


@runtime_checkable
class AuthProvider(Protocol):
    """Provider interface used by SDK clients to resolve auth headers per request."""

    def auth_headers(self) -> Mapping[str, str]:
        """Return sensitive auth headers for the next request."""


@runtime_checkable
class AsyncAuthProvider(Protocol):
    """Awaitable provider interface for non-blocking auth on the async client.

    The async client prefers this over the synchronous :class:`AuthProvider`
    when a provider exposes :meth:`auth_headers_async`, so a token refresh that
    performs network I/O can be awaited rather than blocking the event loop.
    A plain synchronous :class:`AuthProvider` passed to the async client is
    still honoured — its :meth:`~AuthProvider.auth_headers` is invoked in a
    worker thread so a blocking refresh does not stall the loop.
    """

    async def auth_headers_async(self) -> Mapping[str, str]:
        """Return sensitive auth headers for the next request."""


class TokenStore(Protocol):
    """Storage interface for bearer tokens.

    The SDK ships only an in-memory implementation. Applications that need
    persistence should adapt an OS keychain, cloud secret manager, or workload
    identity cache to this protocol.
    """

    def get(self) -> "BearerToken | None":
        """Return the currently cached token, if any."""

    def set(self, token: "BearerToken") -> None:
        """Store a refreshed token."""

    def clear(self) -> None:
        """Forget any cached token."""


@dataclass(frozen=True)
class BearerToken:
    """Bearer token plus optional expiration metadata."""

    access_token: str
    expires_at: datetime | None = None
    token_type: str = "Bearer"  # noqa: S105 -- OAuth2 token_type label, not a secret

    def __post_init__(self) -> None:
        if not self.access_token:
            raise ValueError("access_token must be non-empty.")
        if not self.token_type:
            raise ValueError("token_type must be non-empty.")
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", _normalize_datetime(self.expires_at))

    @classmethod
    def from_expires_in(
        cls,
        access_token: str,
        expires_in_seconds: int | float,
        *,
        token_type: str = "Bearer",  # noqa: S107 -- OAuth2 token_type label, not a secret
        now: datetime | None = None,
    ) -> "BearerToken":
        base = now or datetime.now(UTC)
        return cls(
            access_token=access_token,
            expires_at=base + timedelta(seconds=float(expires_in_seconds)),
            token_type=token_type,
        )

    @property
    def authorization_value(self) -> str:
        return f"{self.token_type} {self.access_token}"

    def expires_within(
        self,
        window: timedelta,
        *,
        now: datetime | None = None,
    ) -> bool:
        if self.expires_at is None:
            return False
        reference = now or datetime.now(UTC)
        return self.expires_at <= reference + window


class InMemoryTokenStore:
    """Thread-safe in-memory token cache."""

    def __init__(self, token: BearerToken | Mapping[str, Any] | str | None = None) -> None:
        self._lock = RLock()
        self._token = _coerce_token(token) if token is not None else None

    def get(self) -> BearerToken | None:
        with self._lock:
            return self._token

    def set(self, token: BearerToken) -> None:
        with self._lock:
            self._token = token

    def clear(self) -> None:
        with self._lock:
            self._token = None


class StaticAuthProvider:
    """Static auth header provider for API-key or bearer-token compatibility."""

    def __init__(self, headers: Mapping[str, str]) -> None:
        self._headers = normalize_auth_headers(headers)

    def auth_headers(self) -> Mapping[str, str]:
        return dict(self._headers)


class CallableAuthProvider:
    """Auth provider backed by a callback returning auth headers per request."""

    def __init__(self, callback: Callable[[], Mapping[str, str]]) -> None:
        self._callback = callback

    def auth_headers(self) -> Mapping[str, str]:
        return normalize_auth_headers(self._callback())


class RefreshableBearerTokenProvider:
    """Refresh bearer tokens before they expire and expose Authorization headers."""

    def __init__(
        self,
        refresh: Callable[[], BearerToken | Mapping[str, Any] | str],
        *,
        initial_token: BearerToken | Mapping[str, Any] | str | None = None,
        token_store: TokenStore | None = None,
        refresh_window_seconds: int | float = 60,
        revoke: Callable[[BearerToken], None] | None = None,
    ) -> None:
        if refresh_window_seconds < 0:
            raise ValueError("refresh_window_seconds must be non-negative.")
        self._refresh = refresh
        self._store = token_store or InMemoryTokenStore(initial_token)
        if token_store is not None and initial_token is not None:
            token_store.set(_coerce_token(initial_token))
        self._refresh_window = timedelta(seconds=float(refresh_window_seconds))
        self._revoke = revoke
        self._lock = RLock()

    def auth_headers(self) -> Mapping[str, str]:
        token = self.get_token()
        return {"Authorization": token.authorization_value}

    def get_token(self) -> BearerToken:
        with self._lock:
            token = self._store.get()
            if token is None or token.expires_within(self._refresh_window):
                token = self._refresh_locked()
            return token

    def refresh(self) -> BearerToken:
        """Force a token refresh and store the result."""
        with self._lock:
            return self._refresh_locked()

    def revoke(self) -> None:
        """Call the optional revocation hook and clear the cached token."""
        with self._lock:
            token = self._store.get()
            if token is not None and self._revoke is not None:
                self._revoke(token)
            self._store.clear()

    def _refresh_locked(self) -> BearerToken:
        token = _coerce_token(self._refresh())
        self._store.set(token)
        return token


class AsyncRefreshableBearerTokenProvider:
    """Async counterpart of :class:`RefreshableBearerTokenProvider`.

    Awaits an async ``refresh`` callback so the async client can renew an
    expiring bearer token without blocking the event loop. The token cache is
    guarded by an :class:`asyncio.Lock`, so concurrent requests that arrive
    while a refresh is in flight wait for the single refresh rather than each
    firing their own.
    """

    def __init__(
        self,
        refresh: Callable[[], Awaitable[BearerToken | Mapping[str, Any] | str]],
        *,
        initial_token: BearerToken | Mapping[str, Any] | str | None = None,
        token_store: TokenStore | None = None,
        refresh_window_seconds: int | float = 60,
        revoke: Callable[[BearerToken], Awaitable[None]] | None = None,
    ) -> None:
        if refresh_window_seconds < 0:
            raise ValueError("refresh_window_seconds must be non-negative.")
        self._refresh = refresh
        self._store = token_store or InMemoryTokenStore(initial_token)
        if token_store is not None and initial_token is not None:
            token_store.set(_coerce_token(initial_token))
        self._refresh_window = timedelta(seconds=float(refresh_window_seconds))
        self._revoke = revoke
        self._lock = asyncio.Lock()

    async def auth_headers_async(self) -> Mapping[str, str]:
        token = await self.get_token()
        return {"Authorization": token.authorization_value}

    async def get_token(self) -> BearerToken:
        async with self._lock:
            token = self._store.get()
            if token is None or token.expires_within(self._refresh_window):
                token = await self._refresh_locked()
            return token

    async def refresh(self) -> BearerToken:
        """Force a token refresh and store the result."""
        async with self._lock:
            return await self._refresh_locked()

    async def revoke(self) -> None:
        """Call the optional revocation hook and clear the cached token."""
        async with self._lock:
            token = self._store.get()
            if token is not None and self._revoke is not None:
                await self._revoke(token)
            self._store.clear()

    async def _refresh_locked(self) -> BearerToken:
        token = _coerce_token(await self._refresh())
        self._store.set(token)
        return token


def normalize_auth_headers(headers: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name, value in headers.items():
        lower_name = name.lower()
        if lower_name not in SENSITIVE_AUTH_HEADER_NAMES:
            raise ValueError(f"Unsupported auth header {name!r}.")
        if not isinstance(value, str) or not value:
            raise ValueError(f"Auth header {name!r} must be a non-empty string.")
        canonical_name = "Authorization" if lower_name == "authorization" else "X-API-Key"
        normalized[canonical_name] = value
    return normalized


def _first_present(value: Mapping[str, Any], *keys: str) -> Any:
    """Return the value for the first key that is present and not ``None``.

    Unlike chained ``or`` lookups, this preserves legitimate falsy values
    (``0``, ``""``, ``False``): only an absent key or an explicit ``None`` is
    skipped in favour of the next candidate.
    """
    for key in keys:
        candidate = value.get(key)
        if candidate is not None:
            return candidate
    return None


def _coerce_token(value: BearerToken | Mapping[str, Any] | str) -> BearerToken:
    if isinstance(value, BearerToken):
        return value
    if isinstance(value, str):
        return BearerToken(value)
    if not isinstance(value, Mapping):
        raise TypeError("Token refresh callbacks must return BearerToken, mapping, or string.")

    access_token = _first_present(value, "access_token", "accessToken", "token")
    if not isinstance(access_token, str):
        raise ValueError("Token mapping must include an access_token string.")

    # ``token_type`` falls back to ``"Bearer"`` when absent or empty:
    # ``BearerToken`` forbids an empty ``token_type``, so an empty value is a
    # missing one for our purposes.
    token_type = value.get("token_type") or value.get("tokenType") or "Bearer"
    if not isinstance(token_type, str):
        raise ValueError("Token mapping token_type must be a string.")

    # Use sentinel-aware lookups so a legitimate ``0`` epoch (treated as a
    # concrete expiry) is not discarded by ``or``-style falsy coercion.
    expires_at = _first_present(value, "expires_at", "expiresAt")
    if expires_at is None and value.get("expires_in") is not None:
        expires_in = value["expires_in"]
        if not isinstance(expires_in, int | float):
            raise ValueError("Token mapping expires_in must be numeric.")
        return BearerToken.from_expires_in(access_token, expires_in, token_type=token_type)

    return BearerToken(
        access_token=access_token,
        expires_at=_parse_expires_at(expires_at),
        token_type=token_type,
    )


def _parse_expires_at(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _normalize_datetime(value)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            # Some valid RFC-3339 forms (e.g. >6-digit fractional seconds on
            # Python 3.11) are rejected by ``fromisoformat``. Degrade to "no
            # known expiry" instead of crashing token coercion.
            return None
        return _normalize_datetime(parsed)
    raise ValueError("expires_at must be a datetime, timestamp, ISO datetime string, or None.")


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
