"""Unit tests for the gRPC client wrappers."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import pytest

from honua_sdk import HonuaGrpcError as RootHonuaGrpcError
from honua_sdk.grpc import HonuaGrpcError as GrpcModuleHonuaGrpcError
from honua_sdk.grpc._client import HonuaGrpcAsyncClient, HonuaGrpcClient
from honua_sdk.grpc._generated.honua.v1 import feature_service_pb2 as pb2
from honua_sdk.grpc._models import (
    GeometryType,
    QueryFeaturesRequest,
)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestClientConstruction:
    """Tests for HonuaGrpcClient construction."""

    def test_requires_explicit_insecure_opt_in_without_credentials(self) -> None:
        with pytest.raises(
            ValueError,
            match="set `insecure=True` explicitly",
        ):
            HonuaGrpcClient("localhost:50051")

    @patch("honua_sdk.grpc._client.grpc.insecure_channel")
    @patch(
        "honua_sdk.grpc._generated.honua.v1.feature_service_pb2_grpc.FeatureServiceStub"
    )
    def test_creates_insecure_channel_when_opted_in(
        self, mock_stub_cls: MagicMock, mock_insecure: MagicMock
    ) -> None:
        mock_insecure.return_value = MagicMock()
        client = HonuaGrpcClient("localhost:50051", insecure=True)

        mock_insecure.assert_called_once_with(
            "localhost:50051", compression=grpc.Compression.Gzip
        )
        mock_stub_cls.assert_called_once()
        assert client._owns_channel is True
        client.close()

    @patch("honua_sdk.grpc._client.grpc.secure_channel")
    @patch(
        "honua_sdk.grpc._generated.honua.v1.feature_service_pb2_grpc.FeatureServiceStub"
    )
    def test_creates_secure_channel_when_credentials_provided(
        self, mock_stub_cls: MagicMock, mock_secure: MagicMock
    ) -> None:
        credentials = MagicMock()
        mock_channel = MagicMock()
        mock_secure.return_value = mock_channel

        client = HonuaGrpcClient("localhost:50051", credentials=credentials)

        mock_secure.assert_called_once_with(
            "localhost:50051",
            credentials,
            compression=grpc.Compression.Gzip,
        )
        assert client._channel is mock_channel
        client.close()

    @patch(
        "honua_sdk.grpc._generated.honua.v1.feature_service_pb2_grpc.FeatureServiceStub"
    )
    def test_uses_provided_channel(self, mock_stub_cls: MagicMock) -> None:
        channel = MagicMock()
        client = HonuaGrpcClient("localhost:50051", channel=channel)

        assert client._owns_channel is False
        assert client._channel is channel
        client.close()

    @patch(
        "honua_sdk.grpc._generated.honua.v1.feature_service_pb2_grpc.FeatureServiceStub"
    )
    def test_context_manager(self, mock_stub_cls: MagicMock) -> None:
        channel = MagicMock()
        with HonuaGrpcClient("localhost:50051", channel=channel) as client:
            assert client._channel is channel
        # close should NOT close provided channel
        channel.close.assert_not_called()

    @patch("honua_sdk.grpc._client.grpc.insecure_channel")
    @patch(
        "honua_sdk.grpc._generated.honua.v1.feature_service_pb2_grpc.FeatureServiceStub"
    )
    def test_context_manager_closes_owned_channel(
        self, mock_stub_cls: MagicMock, mock_insecure: MagicMock
    ) -> None:
        mock_channel = MagicMock()
        mock_insecure.return_value = mock_channel

        with HonuaGrpcClient("localhost:50051", insecure=True):
            pass

        mock_channel.close.assert_called_once()


# ---------------------------------------------------------------------------
# query_features
# ---------------------------------------------------------------------------


class TestQueryFeatures:
    """Tests for the unary query_features method."""

    def _make_client(self) -> tuple[HonuaGrpcClient, MagicMock]:
        """Create a client with a mocked stub."""
        channel = MagicMock()
        with patch(
            "honua_sdk.grpc._generated.honua.v1.feature_service_pb2_grpc.FeatureServiceStub"
        ) as stub_cls:
            mock_stub = MagicMock()
            stub_cls.return_value = mock_stub
            client = HonuaGrpcClient("localhost:50051", channel=channel)
        return client, mock_stub

    def test_delegates_to_stub_and_converts(self) -> None:
        client, mock_stub = self._make_client()

        proto_resp = pb2.QueryFeaturesResponse()
        proto_resp.object_id_field_name = "OBJECTID"
        proto_resp.geometry_type = pb2.GEOMETRY_TYPE_POINT
        proto_resp.count = 100
        mock_stub.QueryFeatures.return_value = proto_resp

        request = QueryFeaturesRequest(
            service_id="svc",
            layer_id=0,
            where="1=1",
            return_count_only=True,
        )
        result = client.query_features(request)

        mock_stub.QueryFeatures.assert_called_once()
        assert result.object_id_field_name == "OBJECTID"
        assert result.geometry_type == GeometryType.POINT
        assert result.count == 100
        client.close()

    def test_wraps_rpc_error(self) -> None:
        client, mock_stub = self._make_client()

        rpc_error = grpc.RpcError()
        rpc_error.code = lambda: grpc.StatusCode.UNAVAILABLE
        rpc_error.details = lambda: "connection refused"
        mock_stub.QueryFeatures.side_effect = rpc_error

        request = QueryFeaturesRequest(service_id="svc", layer_id=0)

        with pytest.raises(RootHonuaGrpcError) as exc_info:
            client.query_features(request)

        assert exc_info.value.code == grpc.StatusCode.UNAVAILABLE
        assert "connection refused" in exc_info.value.message
        client.close()

    def test_passes_metadata(self) -> None:
        channel = MagicMock()
        metadata = [("authorization", "Bearer token123")]
        with patch(
            "honua_sdk.grpc._generated.honua.v1.feature_service_pb2_grpc.FeatureServiceStub"
        ) as stub_cls:
            mock_stub = MagicMock()
            stub_cls.return_value = mock_stub
            client = HonuaGrpcClient(
                "localhost:50051", channel=channel, metadata=metadata
            )

        proto_resp = pb2.QueryFeaturesResponse()
        mock_stub.QueryFeatures.return_value = proto_resp

        client.query_features(QueryFeaturesRequest(service_id="svc", layer_id=0))

        call_kwargs = mock_stub.QueryFeatures.call_args
        assert call_kwargs[1]["metadata"] == metadata
        client.close()


# ---------------------------------------------------------------------------
# query_features_stream
# ---------------------------------------------------------------------------


class TestQueryFeaturesStream:
    """Tests for the streaming query_features_stream method."""

    def _make_client(self) -> tuple[HonuaGrpcClient, MagicMock]:
        """Create a client with a mocked stub."""
        channel = MagicMock()
        with patch(
            "honua_sdk.grpc._generated.honua.v1.feature_service_pb2_grpc.FeatureServiceStub"
        ) as stub_cls:
            mock_stub = MagicMock()
            stub_cls.return_value = mock_stub
            client = HonuaGrpcClient("localhost:50051", channel=channel)
        return client, mock_stub

    def test_yields_pages(self) -> None:
        client, mock_stub = self._make_client()

        page1 = pb2.FeaturePage()
        page1.object_id_field_name = "OBJECTID"
        page1.geometry_type = pb2.GEOMETRY_TYPE_POINT
        f1 = page1.features.add()
        f1.id = 1
        page1.is_last_page = False

        page2 = pb2.FeaturePage()
        f2 = page2.features.add()
        f2.id = 2
        page2.is_last_page = True

        mock_stub.QueryFeaturesStream.return_value = iter([page1, page2])

        request = QueryFeaturesRequest(service_id="svc", layer_id=0)
        pages = list(client.query_features_stream(request))

        assert len(pages) == 2
        assert pages[0].features[0].id == 1
        assert pages[0].is_last_page is False
        assert pages[1].features[0].id == 2
        assert pages[1].is_last_page is True
        client.close()

    def test_stops_on_last_page(self) -> None:
        client, mock_stub = self._make_client()

        page = pb2.FeaturePage()
        page.is_last_page = True

        # Iterator with extra pages after last (should not be reached)
        extra_page = pb2.FeaturePage()
        extra_page.is_last_page = False
        ef = extra_page.features.add()
        ef.id = 999

        mock_stub.QueryFeaturesStream.return_value = iter([page, extra_page])

        request = QueryFeaturesRequest(service_id="svc", layer_id=0)
        pages = list(client.query_features_stream(request))

        assert len(pages) == 1
        assert pages[0].is_last_page is True
        client.close()

    def test_wraps_stream_rpc_error(self) -> None:
        client, mock_stub = self._make_client()

        rpc_error = grpc.RpcError()
        rpc_error.code = lambda: grpc.StatusCode.INTERNAL
        rpc_error.details = lambda: "stream broke"
        mock_stub.QueryFeaturesStream.side_effect = rpc_error

        request = QueryFeaturesRequest(service_id="svc", layer_id=0)

        with pytest.raises(RootHonuaGrpcError) as exc_info:
            list(client.query_features_stream(request))

        assert exc_info.value.code == grpc.StatusCode.INTERNAL
        client.close()


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class _FakeAioRpcError(Exception):
    def __init__(self, code: grpc.StatusCode, details: str) -> None:
        super().__init__(details)
        self._code = code
        self._details = details

    def code(self) -> grpc.StatusCode:
        return self._code

    def details(self) -> str:
        return self._details


class _AsyncPageStream:
    def __init__(self, pages: list[pb2.FeaturePage]) -> None:
        self._iter = iter(pages)

    def __aiter__(self) -> _AsyncPageStream:
        return self

    async def __anext__(self) -> pb2.FeaturePage:
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class TestAsyncClient:
    def test_requires_explicit_insecure_opt_in_without_credentials(self) -> None:
        with pytest.raises(
            ValueError,
            match="set `insecure=True` explicitly",
        ):
            HonuaGrpcAsyncClient("localhost:50051")

    @patch("honua_sdk.grpc._client.grpc.aio.insecure_channel")
    @patch(
        "honua_sdk.grpc._generated.honua.v1.feature_service_pb2_grpc.FeatureServiceStub"
    )
    def test_creates_insecure_channel_when_opted_in(
        self, mock_stub_cls: MagicMock, mock_insecure: MagicMock
    ) -> None:
        mock_channel = MagicMock()
        mock_insecure.return_value = mock_channel

        client = HonuaGrpcAsyncClient("localhost:50051", insecure=True)

        mock_insecure.assert_called_once_with(
            "localhost:50051", compression=grpc.Compression.Gzip
        )
        assert client._channel is mock_channel

    def test_query_features_wraps_aio_rpc_errors(self) -> None:
        channel = MagicMock()
        with patch(
            "honua_sdk.grpc._generated.honua.v1.feature_service_pb2_grpc.FeatureServiceStub"
        ) as stub_cls:
            mock_stub = MagicMock()
            mock_stub.QueryFeatures = AsyncMock(
                side_effect=_FakeAioRpcError(grpc.StatusCode.UNAVAILABLE, "async unavailable")
            )
            stub_cls.return_value = mock_stub
            client = HonuaGrpcAsyncClient("localhost:50051", channel=channel)

        async def _run() -> None:
            with pytest.raises(RootHonuaGrpcError) as exc_info:
                await client.query_features(QueryFeaturesRequest(service_id="svc", layer_id=0))
            assert exc_info.value.code == grpc.StatusCode.UNAVAILABLE
            assert exc_info.value.message == "async unavailable"

        with patch("honua_sdk.grpc._client.grpc.aio.AioRpcError", _FakeAioRpcError):
            asyncio.run(_run())

    def test_query_features_stream_yields_pages(self) -> None:
        channel = MagicMock()
        with patch(
            "honua_sdk.grpc._generated.honua.v1.feature_service_pb2_grpc.FeatureServiceStub"
        ) as stub_cls:
            mock_stub = MagicMock()
            stub_cls.return_value = mock_stub
            client = HonuaGrpcAsyncClient("localhost:50051", channel=channel)

        page1 = pb2.FeaturePage()
        page1.object_id_field_name = "OBJECTID"
        page1.geometry_type = pb2.GEOMETRY_TYPE_POINT
        page1.features.add().id = 1
        page1.is_last_page = False

        page2 = pb2.FeaturePage()
        page2.features.add().id = 2
        page2.is_last_page = True

        mock_stub.QueryFeaturesStream.return_value = _AsyncPageStream([page1, page2])

        async def _run() -> list[int]:
            feature_ids: list[int] = []
            async for page in client.query_features_stream(
                QueryFeaturesRequest(service_id="svc", layer_id=0)
            ):
                feature_ids.extend(feature.id for feature in page.features)
            return feature_ids

        feature_ids = asyncio.run(_run())
        assert feature_ids == [1, 2]


# ---------------------------------------------------------------------------
# HonuaGrpcError
# ---------------------------------------------------------------------------


class TestHonuaGrpcError:
    """Tests for the HonuaGrpcError exception class."""

    def test_single_error_type_is_shared_across_modules(self) -> None:
        from honua_sdk.grpc import _client as grpc_client_module

        assert grpc_client_module.HonuaGrpcError is RootHonuaGrpcError
        assert GrpcModuleHonuaGrpcError is RootHonuaGrpcError

    def test_inherits_from_honua_error(self) -> None:
        from honua_sdk.errors import HonuaError

        err = RootHonuaGrpcError(grpc.StatusCode.NOT_FOUND, "layer not found")
        assert isinstance(err, HonuaError)

    def test_message_formatting(self) -> None:
        err = RootHonuaGrpcError(grpc.StatusCode.UNAVAILABLE, "connection refused")
        assert "UNAVAILABLE" in str(err)
        assert "connection refused" in str(err)

    def test_attributes(self) -> None:
        err = RootHonuaGrpcError(
            grpc.StatusCode.PERMISSION_DENIED, "forbidden", details={"key": "val"}
        )
        assert err.code == grpc.StatusCode.PERMISSION_DENIED
        assert err.message == "forbidden"
        assert err.details == {"key": "val"}
