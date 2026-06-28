"""gRPC clients for Honua FeatureService."""
from __future__ import annotations

from collections.abc import Iterator, Mapping

import grpc

from honua_sdk._http import (
    _build_sensitive_auth_headers,
    _resolve_dynamic_auth_headers_async,
    _validate_auth_configuration,
)
from honua_sdk.auth import AuthProvider, normalize_auth_headers
from honua_sdk.errors import HonuaGrpcError

from . import _models as models
from . import _proto_adapter as adapter


def build_grpc_metadata(
    *,
    api_key: str | None = None,
    bearer_token: str | None = None,
    auth_provider: AuthProvider | None = None,
    extra_metadata: Mapping[str, str] | None = None,
) -> list[tuple[str, str]]:
    """Build gRPC metadata entries from SDK auth options.

    When ``auth_provider`` is supplied its headers are resolved synchronously
    *once*, so the returned list is a static snapshot. Refreshable providers
    are renewed per call only when the provider is passed to the gRPC client
    (see :meth:`HonuaGrpcClient` / :meth:`HonuaGrpcAsyncClient`), which consult
    it on every RPC. An async-only provider (one exposing ``auth_headers_async``
    but no synchronous ``auth_headers``) cannot be resolved here and raises a
    clear ``ValueError`` rather than an opaque ``AttributeError``.
    """
    _validate_auth_configuration(bearer_token=bearer_token, auth_provider=auth_provider)
    headers = _build_sensitive_auth_headers(api_key=api_key, bearer_token=bearer_token)
    if auth_provider is not None:
        for name, value in _provider_auth_headers_sync(auth_provider).items():
            headers.setdefault(name, value)
    if extra_metadata:
        headers.update(extra_metadata)
    return [(name.lower(), value) for name, value in headers.items()]


def _provider_auth_headers_sync(auth_provider: AuthProvider) -> dict[str, str]:
    """Resolve an auth provider's headers synchronously, rejecting async-only ones."""
    sync_getter = getattr(auth_provider, "auth_headers", None)
    if sync_getter is None:
        raise ValueError(
            "auth_provider exposes only `auth_headers_async`; it cannot be resolved "
            "on the synchronous gRPC path. Use a synchronous AuthProvider here, or "
            "construct the client via the AsyncHonuaClient.grpc() surface, which "
            "resolves async providers per call without blocking the event loop."
        )
    return normalize_auth_headers(sync_getter())


def _merge_provider_metadata(
    static_metadata: list[tuple[str, str]],
    provider_headers: Mapping[str, str],
) -> list[tuple[str, str]]:
    """Merge per-call provider headers under static metadata (static wins on dupes).

    Mirrors the ``setdefault`` precedence of :func:`build_grpc_metadata`: the
    static api-key/bearer/``extra_metadata`` entries take precedence, and the
    refreshable provider only fills metadata keys not already present.
    """
    if not provider_headers:
        return static_metadata
    present = {name for name, _ in static_metadata}
    merged = list(static_metadata)
    for name, value in provider_headers.items():
        lowered = name.lower()
        if lowered not in present:
            merged.append((lowered, value))
    return merged


class HonuaGrpcClient:
    """Synchronous gRPC client for Honua FeatureService."""

    def __init__(
        self,
        target: str,
        *,
        channel: grpc.Channel | None = None,
        credentials: grpc.ChannelCredentials | None = None,
        insecure: bool = False,
        metadata: list[tuple[str, str]] | None = None,
        auth_provider: AuthProvider | None = None,
        timeout: float | None = 30.0,
        compression: grpc.Compression | None = grpc.Compression.Gzip,
    ) -> None:
        self._metadata = metadata or []
        self._auth_provider = auth_provider
        self._timeout = timeout
        self._owns_channel = channel is None

        if channel is not None:
            self._channel = channel
        elif credentials is not None:
            self._channel = grpc.secure_channel(target, credentials, compression=compression)
        elif insecure:
            self._channel = grpc.insecure_channel(target, compression=compression)
        else:
            raise ValueError(
                "Provide `credentials`, a pre-configured `channel`, or set `insecure=True` explicitly."
            )

        from honua_sdk.grpc._generated.honua.v1 import feature_service_pb2_grpc

        self._stub = feature_service_pb2_grpc.FeatureServiceStub(self._channel)  # type: ignore[no-untyped-call]

    def __enter__(self) -> HonuaGrpcClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying channel if owned by this client."""
        if self._owns_channel:
            self._channel.close()

    def _request_metadata(self) -> list[tuple[str, str]]:
        """Resolve per-call metadata, re-consulting any auth provider each RPC.

        Resolving the provider on every call means a refreshable bearer token is
        renewed when it nears expiry instead of being frozen at channel-creation
        time (the static-snapshot behaviour of a bare ``metadata=`` list).
        """
        if self._auth_provider is None:
            return self._metadata
        return _merge_provider_metadata(
            self._metadata, _provider_auth_headers_sync(self._auth_provider)
        )

    def query_features(
        self, request: models.QueryFeaturesRequest
    ) -> models.QueryFeaturesResponse:
        """Execute a unary feature query and return the full response."""
        proto_request = adapter.to_proto_request(request)
        try:
            proto_response = self._stub.QueryFeatures(
                proto_request,
                metadata=self._request_metadata(),
                timeout=self._timeout,
            )
        except grpc.RpcError as e:
            raise HonuaGrpcError(e.code(), e.details() or str(e)) from e
        return adapter.from_proto_response(proto_response)

    def query_features_stream(
        self, request: models.QueryFeaturesRequest
    ) -> Iterator[models.FeaturePage]:
        """Execute a streaming feature query, yielding one page at a time."""
        proto_request = adapter.to_proto_request(request)
        try:
            stream = self._stub.QueryFeaturesStream(
                proto_request,
                metadata=self._request_metadata(),
                timeout=self._timeout,
            )
            for page in stream:
                yield adapter.from_proto_page(page)
                if page.is_last_page:
                    break
        except grpc.RpcError as e:
            raise HonuaGrpcError(e.code(), e.details() or str(e)) from e


class HonuaGrpcAsyncClient:
    """Async gRPC client for Honua FeatureService."""

    def __init__(
        self,
        target: str,
        *,
        channel: grpc.aio.Channel | None = None,
        credentials: grpc.ChannelCredentials | None = None,
        insecure: bool = False,
        metadata: list[tuple[str, str]] | None = None,
        auth_provider: AuthProvider | None = None,
        timeout: float | None = 30.0,
        compression: grpc.Compression | None = grpc.Compression.Gzip,
    ) -> None:
        self._metadata = metadata or []
        self._auth_provider = auth_provider
        self._timeout = timeout
        self._owns_channel = channel is None

        if channel is not None:
            self._channel = channel
        elif credentials is not None:
            self._channel = grpc.aio.secure_channel(target, credentials, compression=compression)
        elif insecure:
            self._channel = grpc.aio.insecure_channel(target, compression=compression)
        else:
            raise ValueError(
                "Provide `credentials`, a pre-configured `channel`, or set `insecure=True` explicitly."
            )

        from honua_sdk.grpc._generated.honua.v1 import feature_service_pb2_grpc

        self._stub = feature_service_pb2_grpc.FeatureServiceStub(self._channel)  # type: ignore[no-untyped-call]

    async def __aenter__(self) -> HonuaGrpcAsyncClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying channel if owned by this client."""
        if self._owns_channel:
            await self._channel.close()

    async def _request_metadata(self) -> list[tuple[str, str]]:
        """Resolve per-call metadata without blocking the event loop.

        Prefers an awaitable ``auth_headers_async`` (an async-only provider
        works here) and re-consults the provider each RPC, so a refreshable
        bearer token is renewed near expiry rather than frozen at channel
        creation.
        """
        if self._auth_provider is None:
            return self._metadata
        provider_headers = await _resolve_dynamic_auth_headers_async(self._auth_provider)
        return _merge_provider_metadata(self._metadata, provider_headers)

    async def query_features(
        self, request: models.QueryFeaturesRequest
    ) -> models.QueryFeaturesResponse:
        """Execute a unary feature query and return the full response."""
        proto_request = adapter.to_proto_request(request)
        try:
            proto_response = await self._stub.QueryFeatures(
                proto_request,
                metadata=await self._request_metadata(),
                timeout=self._timeout,
            )
        except grpc.aio.AioRpcError as e:
            raise HonuaGrpcError(e.code(), e.details() or str(e)) from e
        return adapter.from_proto_response(proto_response)

    async def query_features_stream(  # type: ignore[no-untyped-def]
        self, request: models.QueryFeaturesRequest
    ):  # -> AsyncIterator[models.FeaturePage]
        """Execute a streaming feature query, yielding one page at a time."""
        proto_request = adapter.to_proto_request(request)
        metadata = await self._request_metadata()
        try:
            stream = self._stub.QueryFeaturesStream(
                proto_request,
                metadata=metadata,
                timeout=self._timeout,
            )
            async for page in stream:
                yield adapter.from_proto_page(page)
                if page.is_last_page:
                    break
        except grpc.aio.AioRpcError as e:
            raise HonuaGrpcError(e.code(), e.details() or str(e)) from e
