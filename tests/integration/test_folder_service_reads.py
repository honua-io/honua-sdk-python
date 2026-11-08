"""Read a seeded Folder Service through explicit links and its saved Root alias."""

from __future__ import annotations

import inspect
import os
from urllib.parse import quote

import pytest

from honua_sdk import AsyncHonuaClient, HonuaClient, ServiceAddress

pytestmark = [pytest.mark.integration, pytest.mark.staging, pytest.mark.smoke]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def folder_read_config(smoke_config):
    folder_name = os.environ.get("HONUA_FOLDER_TEST_FOLDER")
    expected_name = os.environ.get("HONUA_FOLDER_TEST_EXPECTED_NAME")
    if not folder_name:
        pytest.skip("Folder reads require a seeded HONUA_FOLDER_TEST_FOLDER")
    assert expected_name, "HONUA_FOLDER_TEST_EXPECTED_NAME must identify a seeded feature"
    return smoke_config, folder_name, expected_name


@pytest.mark.anyio
@pytest.mark.parametrize("client_mode", ["sync", "async"])
@pytest.mark.parametrize("address_kind", ["root-alias", "folder-link", "source-link"])
async def test_folder_service_reads_preserve_features_and_logical_identity(folder_read_config, client_mode, address_kind) -> None:
    config, folder_name, expected_name = folder_read_config
    client_type = AsyncHonuaClient if client_mode == "async" else HonuaClient
    client = client_type(config.base_url, api_key=config.api_key)
    path = f"/rest/services/{quote(folder_name, safe='')}/{quote(config.service_id, safe='')}/FeatureServer"
    try:
        if address_kind == "source-link":
            source = client.source({
                "id": config.service_id,
                "protocol": "geoservices-feature-service",
                "locator": {"serviceId": config.service_id, "layerId": config.layer_id, "url": path},
            })
            result = source.query()
        else:
            address = config.service_id if address_kind == "root-alias" else ServiceAddress(path)
            result = client.query_feature_set(address, config.layer_id)
        if inspect.isawaitable(result):
            result = await result
        assert result.features
        attributes = [
            feature.properties if address_kind == "source-link" else feature.attributes
            for feature in result.features
        ]
        assert any(item.get("name") == expected_name for item in attributes)
        assert all(feature.geometry is not None for feature in result.features)
        if address_kind == "source-link":
            assert result.source_id == config.service_id
            assert all(feature.source == config.service_id for feature in result.features)
        catalog = client.list_service_summaries(folder_name=folder_name)
        if inspect.isawaitable(catalog):
            catalog = await catalog
        assert any(service.name == f"{folder_name}/{config.service_id}" for service in catalog)
    finally:
        closed = client.close()
        if inspect.isawaitable(closed):
            await closed
