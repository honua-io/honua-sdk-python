from __future__ import annotations

import pytest

from scripts._smoke_harness import SmokeReport, load_smoke_config_from_env


@pytest.fixture(scope="session")
def smoke_config():
    return load_smoke_config_from_env()


@pytest.fixture(scope="session")
def smoke_report(smoke_config):
    report = SmokeReport(config=smoke_config)
    yield report
    report.write()


@pytest.fixture(scope="session")
def smoke_client(smoke_config):
    from honua_sdk import HonuaClient

    with HonuaClient(smoke_config.base_url, api_key=smoke_config.api_key) as client:
        yield client
