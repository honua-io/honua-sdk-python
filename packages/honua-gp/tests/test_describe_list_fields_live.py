"""Live-server integration test for ``management.Describe`` / ``ListFields``.

Skipped by default (the rest of the suite runs against the stub transport in
``eval/_stub.py``). Set ``HONUA_GP_LIVE_BASE_URL`` to a real honua-server to
run this against it -- e.g. the pinned ``docker/client-compat`` target used
by the ``Python SDK Conformance`` workflow (``.github/workflows/conformance.yml``
in this repo), which seeds a ``test_service`` FeatureServer with layer ``0``:

    cd <honua-server checkout>
    docker pull ghcr.io/honua-io/honua-server:nightly-20260530-amd64
    docker build -t client-compat-seed:latest -f docker/client-compat/seed/Dockerfile .
    docker compose -f docker/client-compat/compose.yml \\
        -f <override adding `ports: ["5000:5000"]` to the honua service,\\
            see conformance.yml's "Start seeded pinned Honua target" step> \\
        up -d --no-build honua
    curl -fsS http://localhost:5000/healthz/ready

    HONUA_GP_LIVE_BASE_URL=http://localhost:5000 \\
    HONUA_GP_LIVE_SERVICE_ID=test_service \\
        python -m pytest packages/honua-gp/tests/test_describe_list_fields_live.py -q

A deliberately separate env var (not ``HONUA_BASE_URL``) so this test never
activates by accident in a shell where ``HONUA_BASE_URL`` happens to be set
for an unrelated purpose (e.g. a developer's live shell profile).
"""

from __future__ import annotations

import os

import pytest

import honua_gp

_LIVE_BASE_URL = os.environ.get("HONUA_GP_LIVE_BASE_URL")

pytestmark = pytest.mark.skipif(
    not _LIVE_BASE_URL,
    reason=(
        "set HONUA_GP_LIVE_BASE_URL (and optionally HONUA_GP_LIVE_SERVICE_ID, "
        "default 'test_service') to run Describe/ListFields against a real "
        "honua-server; see this file's module docstring for the docker/client-compat "
        "recipe."
    ),
)


@pytest.fixture(autouse=True)
def _live_session():
    honua_gp.reset()
    yield
    honua_gp.reset()


def test_describe_returns_real_schema_from_live_server() -> None:
    service_id = os.environ.get("HONUA_GP_LIVE_SERVICE_ID", "test_service")
    honua_gp.configure(base_url=_LIVE_BASE_URL)
    honua_gp.env.workspace = f"honua://services/{service_id}"

    desc = honua_gp.Describe("live_layer")

    assert desc.shapeType, "expected a non-empty geometry type from the live layer"
    assert desc.OIDFieldName, "expected the live layer to advertise an OID field"
    assert desc.fields, "expected at least one field from the live layer"
    assert desc.spatialReference is not None
    assert isinstance(desc.spatialReference.factoryCode, int)

    field_names = {f.name for f in desc.fields}
    assert desc.OIDFieldName in field_names


def test_list_fields_matches_describe_and_supports_filters_on_live_server() -> None:
    service_id = os.environ.get("HONUA_GP_LIVE_SERVICE_ID", "test_service")
    honua_gp.configure(base_url=_LIVE_BASE_URL)
    honua_gp.env.workspace = f"honua://services/{service_id}"

    desc = honua_gp.Describe("live_layer")
    all_fields = honua_gp.management.ListFields("live_layer")
    assert {f.name for f in all_fields} == {f.name for f in desc.fields}

    string_fields = honua_gp.management.ListFields("live_layer", field_type="String")
    assert string_fields, "expected at least one String field on the live layer"
    assert all(f.type == "String" for f in string_fields)

    # A wildcard that cannot match anything real must return an empty list,
    # not raise.
    assert honua_gp.management.ListFields("live_layer", wild_card="__no_such_field__*") == []


def test_describe_unknown_service_raises_execute_error_on_live_server() -> None:
    honua_gp.configure(base_url=_LIVE_BASE_URL)
    honua_gp.env.workspace = "honua://services/__honua_gp_live_test_unknown_service__"

    with pytest.raises(honua_gp.ExecuteError) as info:
        honua_gp.Describe("nope")
    assert info.value.function == "management.Describe"
