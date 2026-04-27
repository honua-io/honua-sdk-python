from __future__ import annotations

import pytest

from scripts._smoke_harness import (
    _feature_server_layer_path,
    assert_probe_passed,
    probe_list_services,
    probe_query_seeded_layer,
    probe_readiness,
    probe_context,
    run_probe,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.staging,
    pytest.mark.smoke,
]


def test_staging_readiness(smoke_client, smoke_config, smoke_report) -> None:
    result = smoke_report.record(
        run_probe(
            "readiness",
            lambda: probe_readiness(smoke_client, smoke_config),
            context=probe_context(
                smoke_config,
                protocol_surface="Honua Server health",
                sdk_method="HonuaClient.readiness",
                request_path="/healthz/ready",
            ),
        )
    )
    assert_probe_passed(result)


def test_staging_lists_configured_service(smoke_client, smoke_config, smoke_report) -> None:
    result = smoke_report.record(
        run_probe(
            "list_services",
            lambda: probe_list_services(smoke_client, smoke_config),
            context=probe_context(
                smoke_config,
                protocol_surface="GeoServices catalog",
                sdk_method="HonuaClient.list_services",
                request_path="/rest/services",
            ),
        )
    )
    assert_probe_passed(result)


def test_staging_queries_seeded_layer(smoke_client, smoke_config, smoke_report) -> None:
    result = smoke_report.record(
        run_probe(
            "query_seeded_layer",
            lambda: probe_query_seeded_layer(smoke_client, smoke_config),
            context=probe_context(
                smoke_config,
                protocol_surface="GeoServices FeatureServer",
                sdk_method="HonuaClient.query_features",
                request_path=_feature_server_layer_path(smoke_config, "/query"),
            ),
        )
    )
    assert_probe_passed(result)
