"""gRPC clients for Honua FeatureService."""
from __future__ import annotations

from collections.abc import Iterator, Mapping

import grpc

from honua_sdk._http import _build_sensitive_auth_headers, _validate_auth_configuration
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
    """Build gRPC metadata entries from SDK auth options."""
    _validate_auth_configuration(bearer_token=bearer_token, auth_provider=auth_provider)
    headers = _build_sensitive_auth_headers(api_key=api_key, bearer_token=bearer_token)
    if auth_provider is not None:
        for name, value in normalize_auth_headers(auth_provider.auth_headers()).items():
            headers.setdefault(name, value)
    if extra_metadata:
        headers.update(extra_metadata)
    return [(name.lower(), value) for name, value in headers.items()]


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
        timeout: float | None = 30.0,
        compression: grpc.Compression | None = grpc.Compression.Gzip,
    ) -> None:
        self._metadata = metadata or []
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

    def query_features(
        self, request: models.QueryFeaturesRequest
    ) -> models.QueryFeaturesResponse:
        """Execute a unary feature query and return the full response."""
        proto_request = adapter.to_proto_request(request)
        try:
            proto_response = self._stub.QueryFeatures(
                proto_request,
                metadata=self._metadata,
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
                metadata=self._metadata,
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
        timeout: float | None = 30.0,
        compression: grpc.Compression | None = grpc.Compression.Gzip,
    ) -> None:
        self._metadata = metadata or []
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

    async def query_features(
        self, request: models.QueryFeaturesRequest
    ) -> models.QueryFeaturesResponse:
        """Execute a unary feature query and return the full response."""
        proto_request = adapter.to_proto_request(request)
        try:
            proto_response = await self._stub.QueryFeatures(
                proto_request,
                metadata=self._metadata,
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
        try:
            stream = self._stub.QueryFeaturesStream(
                proto_request,
                metadata=self._metadata,
                timeout=self._timeout,
            )
            async for page in stream:
                yield adapter.from_proto_page(page)
                if page.is_last_page:
                    break
        except grpc.aio.AioRpcError as e:
            raise HonuaGrpcError(e.code(), e.details() or str(e)) from e
