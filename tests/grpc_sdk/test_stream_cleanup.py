"""Owned RPC cleanup, including a real local peer; not candidate/provider qualification."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock, patch

import grpc
import pytest

from honua_sdk.grpc import HonuaGrpcAsyncClient, HonuaGrpcClient, HonuaGrpcError, QueryFeaturesRequest
from honua_sdk.grpc._generated.geospatial.v1 import feature_service_pb2 as pb


class ControlledCall:
    def __init__(self, terminal: bool = False) -> None:
        self.pages = iter([pb.FeaturePage(is_last_page=terminal), pb.FeaturePage()])
        self.cancel_count = 0
        self.waiting = asyncio.Event()
        self.park = False
        self.error = None

    def cancel(self) -> bool:
        self.cancel_count += 1
        return True

    def __iter__(self):
        return self

    def __next__(self):
        if self.error is not None:
            raise self.error
        return next(self.pages)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.park:
            self.waiting.set()
            await asyncio.Future()
        try:
            return next(self)
        except StopIteration as error:
            raise StopAsyncIteration from error


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("path", ["close", "exhausted", "terminal", "decode-error", "rpc-error"])
def test_every_iterator_exit_releases_rpc_without_closing_shared_channel(asynchronous, path):
    call = ControlledCall(terminal=path == "terminal")
    if path == 'rpc-error':
        call.error = grpc.aio.AioRpcError(
            grpc.StatusCode.INTERNAL, grpc.aio.Metadata(('initial-control', 'one')),
            grpc.aio.Metadata(('trailing-control', 'two')), 'stream failed')
    channel = MagicMock()
    client_type = HonuaGrpcAsyncClient if asynchronous else HonuaGrpcClient
    with patch('honua_sdk.grpc._generated.geospatial.v1.feature_service_pb2_grpc.FeatureServiceStub') as stub:
        stub.return_value.QueryFeaturesStream.return_value = call
        client = client_type('unused', channel=channel)
    request = QueryFeaturesRequest(service_id='control', layer_id=0)

    async def run_async():
        pages = client.query_features_stream(request)
        if path == 'close':
            await anext(pages)
            await pages.aclose()
        else:
            return [page async for page in pages]

    def consume():
        if asynchronous:
            return asyncio.run(run_async())
        pages = client.query_features_stream(request)
        if path == 'close':
            next(pages)
            pages.close()
        else:
            return list(pages)
        return None

    if path == 'rpc-error':
        with pytest.raises(HonuaGrpcError) as caught:
            consume()
        assert caught.value.code == grpc.StatusCode.INTERNAL
        assert caught.value.protocol_metadata.initial['initial-control'] == ('one',)
        assert caught.value.protocol_metadata.trailing['trailing-control'] == ('two',)
    elif path == 'decode-error':
        with patch('honua_sdk.grpc._client.adapter.from_proto_page', side_effect=ValueError('malformed geometry')):
            with pytest.raises(ValueError, match='malformed geometry'):
                consume()
    else:
        result = consume()
        if path in {'terminal', 'exhausted'}:
            assert len(result) == (1 if path == 'terminal' else 2)
    assert call.cancel_count == 1
    channel.close.assert_not_called()


def test_cancelled_async_read_cancels_the_call():
    async def scenario():
        call = ControlledCall()
        call.park = True
        with patch('honua_sdk.grpc._generated.geospatial.v1.feature_service_pb2_grpc.FeatureServiceStub') as stub:
            stub.return_value.QueryFeaturesStream.return_value = call
            client = HonuaGrpcAsyncClient('unused', channel=MagicMock())
        pages = client.query_features_stream(QueryFeaturesRequest(service_id='control', layer_id=0))
        pending = asyncio.create_task(anext(pages))
        try:
            await asyncio.wait_for(call.waiting.wait(), timeout=5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert call.cancel_count == 1
        finally:
            pending.cancel()
            await pages.aclose()
    asyncio.run(scenario())


@pytest.fixture
def local_peer():
    """A real HTTP/2 peer holds responses open until cancellation, independently per RPC."""
    stopped = {key: Event() for key in ('target', 'other')}
    release = Event()

    def stream(request, context):
        done = stopped[request.service_id]
        context.add_callback(done.set)
        yield pb.FeaturePage(is_last_page=request.layer_id == 1)
        # The test cancels well before this safety bound. A terminal-marked page must
        # also release its still-open transport instead of relying on peer completion.
        release.wait(15)
        if context.is_active():
            yield pb.FeaturePage(is_last_page=True)

    def query(request, context):
        response = pb.QueryFeaturesResponse(object_id_field_name='objectid')
        response.features.add().id = 7
        return response

    handlers = {'QueryFeatures': grpc.unary_unary_rpc_method_handler(
        query, request_deserializer=pb.QueryFeaturesRequest.FromString,
        response_serializer=pb.QueryFeaturesResponse.SerializeToString), 'QueryFeaturesStream': grpc.unary_stream_rpc_method_handler(
        stream, request_deserializer=pb.QueryFeaturesRequest.FromString,
        response_serializer=pb.FeaturePage.SerializeToString)}
    with ThreadPoolExecutor(max_workers=4) as pool:
        server = grpc.server(pool)
        server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler('geospatial.v1.FeatureService', handlers),))
        port = server.add_insecure_port('127.0.0.1:0')
        assert port > 0
        server.start()
        try:
            yield f'127.0.0.1:{port}', stopped
        finally:
            release.set()
            server.stop(0).wait(timeout=5)


@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.parametrize('terminal', [False, True])
def test_real_peer_observes_cleanup_while_an_unrelated_stream_remains_open(local_peer, asynchronous, terminal):
    target, stopped = local_peer
    calls = []  # Keep the real calls alive: garbage collection must not be our cancellation mechanism.
    def observe(client):
        actual = client._stub.QueryFeaturesStream
        def start(*args, **kwargs):
            call = actual(*args, **kwargs)
            calls.append(call)
            return call
        client._stub.QueryFeaturesStream = start
    request = QueryFeaturesRequest(service_id='target', layer_id=int(terminal))
    other_request = QueryFeaturesRequest(service_id='other', layer_id=0)

    async def scenario():
        async with HonuaGrpcAsyncClient(target, insecure=True, timeout=10) as client:
            observe(client)
            other = client.query_features_stream(other_request)
            pages = client.query_features_stream(request)
            try:
                await anext(other)
                await anext(pages)
                if terminal:
                    with pytest.raises(StopAsyncIteration):
                        await anext(pages)
                else:
                    await pages.aclose()
                assert await asyncio.to_thread(stopped['target'].wait, 5)
                assert not stopped['other'].is_set()
                assert calls[0].cancelled() is False
                assert calls[1].cancelled() is True
                assert (await client.query_features(request)).features[0].id == 7
            finally:
                await pages.aclose()
                await other.aclose()
            assert await asyncio.to_thread(stopped['other'].wait, 5)

    if asynchronous:
        asyncio.run(scenario())
    else:
        with HonuaGrpcClient(target, insecure=True, timeout=10) as client:
            observe(client)
            other = client.query_features_stream(other_request)
            pages = client.query_features_stream(request)
            try:
                next(other)
                next(pages)
                if terminal:
                    with pytest.raises(StopIteration):
                        next(pages)
                else:
                    pages.close()
                assert stopped['target'].wait(5)
                assert not stopped['other'].is_set()
                assert not calls[0].cancelled()
                assert calls[1].cancelled()
                assert client.query_features(request).features[0].id == 7
            finally:
                pages.close()
                other.close()
            assert stopped['other'].wait(5)
