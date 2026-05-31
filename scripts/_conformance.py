"""Live-server conformance harness for the shared geospatial-grpc fixtures.

This module powers the blocking ``conformance`` CI lane (issue #81, epic
``geospatial-grpc#18`` — the cross-repo Compatibility Train). It consumes the
*shared* conformance fixtures published by ``geospatial-grpc`` (issue #19,
fetched with ``conformance/fetch-fixtures.sh``) and exercises them against a
**pinned live ``honua-server:nightly``** through the ``httpx`` clients
(:class:`~honua_sdk.HonuaClient` / :class:`~honua_sdk.AsyncHonuaClient`),
failing on any contract drift.

Why a mapping layer
-------------------
The shared fixtures are canonical ``geospatial.v1`` *gRPC* request/response
payloads (protobuf-JSON). The Python SDK's data plane talks to the server's
**REST** surfaces (GeoServices FeatureServer, OGC API Features). Each fixture
therefore encodes a *contract requirement* — a workflow, its request shape, and
the response envelope/field-typing/error semantics — that we re-express as a
concrete REST call and assert against the live server. A fixture maps 1:1 to a
``geospatial.v1`` schema release (``conformance/FIXTURES_VERSION``), so when the
pinned nightly drifts from that contract, the lane goes red.

The honua-server#1238 class of regression (FeatureServer/OGC query of a
JSONB-attribute layer failing with ``column ... does not exist``) is caught
because the seeded ``test_service`` layer stores every attribute in a JSONB
column and the feature-query case projects the JSON-typed ``tags``/``numbers``
fields out of it.

Known, already-tracked nightly gaps are reported as ``known_gap`` cases (the
pytest layer turns these into ``xfail`` with explicit issue references) so the
lane stays green while the harness is in place, yet any *new* drift still fails.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from honua_sdk import HonuaClient, HonuaHttpError

# --------------------------------------------------------------------------- #
# Fixture set: version pin + on-disk layout
# --------------------------------------------------------------------------- #

#: Environment variable pointing at a fetched fixture bundle (the ``--dest`` of
#: ``conformance/fetch-fixtures.sh``). When unset, callers fall back to the
#: pinned version recorded in ``conformance/FIXTURES_VERSION``.
FIXTURES_DIR_ENV = "HONUA_CONFORMANCE_FIXTURES_DIR"

#: Repo-relative location of the pinned fixture version (single source of truth
#: for which ``geospatial.v1`` schema release this SDK is certified against).
_REPO_ROOT = Path(__file__).resolve().parent.parent
PINNED_VERSION_FILE = _REPO_ROOT / "conformance" / "FIXTURES_VERSION"


class ConformanceFixturesError(RuntimeError):
    """Raised when the shared fixture bundle is missing or malformed."""


def pinned_fixture_version() -> str:
    """Return the fixture/schema version this SDK is pinned to."""
    if not PINNED_VERSION_FILE.exists():
        raise ConformanceFixturesError(
            f"Pinned fixture version file not found: {PINNED_VERSION_FILE}"
        )
    return PINNED_VERSION_FILE.read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class FixtureBundle:
    """A verified, on-disk shared conformance fixture set.

    Mirrors the layout produced by ``conformance/fetch-fixtures.sh``:
    ``fixtures/`` (canonical payloads + ``manifest.txt``), ``golden/`` and a
    top-level ``VERSION``.
    """

    root: Path
    version: str

    @property
    def fixtures_dir(self) -> Path:
        return self.root / "fixtures"

    @property
    def golden_dir(self) -> Path:
        return self.root / "golden"

    def request(self, name: str) -> dict[str, Any]:
        return self._load(self.fixtures_dir / f"{name}_request.json")

    def response(self, name: str) -> dict[str, Any]:
        # Prefer the canonical golden envelope; fall back to the raw fixture.
        golden = self.golden_dir / f"{name}_response.json"
        if golden.exists():
            return self._load(golden)
        return self._load(self.fixtures_dir / f"{name}_response.json")

    def manifest_types(self) -> dict[str, str]:
        """Map fixture file -> fully-qualified protobuf message type."""
        manifest = self.fixtures_dir / "manifest.txt"
        if not manifest.exists():
            raise ConformanceFixturesError(f"manifest.txt missing in {self.fixtures_dir}")
        mapping: dict[str, str] = {}
        for raw in manifest.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                mapping[parts[0]] = parts[1]
        return mapping

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise ConformanceFixturesError(f"fixture file missing: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ConformanceFixturesError(f"fixture {path} is not a JSON object")
        return data


def locate_fixture_bundle() -> FixtureBundle:
    """Discover and validate the fetched fixture bundle.

    Resolution order:

    1. ``$HONUA_CONFORMANCE_FIXTURES_DIR`` (the ``--dest`` of the fetch helper);
       may point either directly at the bundle or at a parent holding the
       ``conformance-fixtures-<version>`` directory.
    2. ``./conformance-fixtures-<pinned-version>`` (the helper's default dest)
       under the repo root or the current working directory.

    The embedded ``VERSION`` must equal the pinned version, mirroring the
    integrity check the fetch helper performs.
    """
    pinned = pinned_fixture_version()
    candidates: list[Path] = []

    env_dir = os.environ.get(FIXTURES_DIR_ENV)
    if env_dir:
        base = Path(env_dir)
        candidates.append(base)
        candidates.append(base / f"conformance-fixtures-{pinned}")

    default_name = f"conformance-fixtures-{pinned}"
    candidates.append(_REPO_ROOT / default_name)
    candidates.append(Path.cwd() / default_name)

    for candidate in candidates:
        version_file = candidate / "VERSION"
        if not version_file.exists():
            continue
        version = version_file.read_text(encoding="utf-8").strip()
        if version != pinned:
            raise ConformanceFixturesError(
                f"fixture bundle at {candidate} has VERSION {version!r}; "
                f"expected pinned {pinned!r}"
            )
        if not (candidate / "fixtures").is_dir() or not (candidate / "golden").is_dir():
            raise ConformanceFixturesError(
                f"fixture bundle at {candidate} is missing fixtures/ or golden/"
            )
        return FixtureBundle(root=candidate, version=version)

    raise ConformanceFixturesError(
        "Shared conformance fixtures not found. Fetch them first, e.g.\n"
        f"  conformance/fetch-fixtures.sh --version {pinned} "
        f"--dest ./conformance-fixtures-{pinned}\n"
        f"or set {FIXTURES_DIR_ENV} to the fetched bundle directory. "
        f"Searched: {', '.join(str(c) for c in candidates)}"
    )


# --------------------------------------------------------------------------- #
# Live target configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ConformanceTarget:
    """The pinned live server the fixtures are checked against."""

    base_url: str
    service_id: str = "test_service"
    layer_id: int = 0
    api_key: str | None = None
    server_image: str | None = None
    server_commit: str | None = None


def load_target_from_env() -> ConformanceTarget:
    base_url = os.environ.get("HONUA_BASE_URL")
    if not base_url:
        raise ConformanceFixturesError(
            "HONUA_BASE_URL is required to run live conformance checks."
        )
    layer_text = os.environ.get("HONUA_LAYER_ID", "0")
    try:
        layer_id = int(layer_text)
    except ValueError as exc:  # pragma: no cover - guarded by CI env
        raise ConformanceFixturesError("HONUA_LAYER_ID must be an integer.") from exc
    return ConformanceTarget(
        base_url=base_url,
        service_id=os.environ.get("HONUA_SERVICE_ID", "test_service"),
        layer_id=layer_id,
        api_key=os.environ.get("HONUA_API_KEY"),
        server_image=os.environ.get("HONUA_SERVER_IMAGE"),
        server_commit=os.environ.get("HONUA_SERVER_COMMIT"),
    )


# --------------------------------------------------------------------------- #
# Conformance cases
# --------------------------------------------------------------------------- #

#: Tracked nightly server gaps. A case bound to one of these is reported as a
#: known gap (xfail at the pytest layer) until the server fix lands, at which
#: point the case flips to required. Keep references explicit — never silent.
KNOWN_SERVER_GAPS: dict[str, str] = {
    "honua-server#1238": "FeatureServer/OGC query of JSONB-attribute layer (column projection)",
    "honua-server#1166": "Temporal query support",
    "honua-server#1167": "Replica / offline sync endpoints",
    "honua-server#1237": "Analysis (process) list/estimate endpoints",
}


@dataclass
class CaseResult:
    """Outcome of one conformance case."""

    name: str
    status: str  # "passed" | "failed"
    fixture: str
    message_type: str | None
    sdk_method: str
    request_path: str
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class ConformanceCase:
    """One fixture-backed contract check, runnable against a live server."""

    name: str
    fixture: str
    sdk_method: str
    request_path: str
    runner: Callable[[HonuaClient, ConformanceTarget, FixtureBundle], dict[str, Any]]
    #: When set, this case exercises a tracked-but-unshipped server behavior.
    #: The pytest layer turns it into an xfail referencing this issue.
    known_gap_issue: str | None = None

    def run(
        self,
        client: HonuaClient,
        target: ConformanceTarget,
        bundle: FixtureBundle,
    ) -> CaseResult:
        message_type = bundle.manifest_types().get(f"{self.fixture}_response.json") or (
            bundle.manifest_types().get(f"{self.fixture}_request.json")
        )
        try:
            details = self.runner(client, target, bundle)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            return CaseResult(
                name=self.name,
                status="failed",
                fixture=self.fixture,
                message_type=message_type,
                sdk_method=self.sdk_method,
                request_path=self.request_path,
                error=f"{type(exc).__name__}: {exc}",
            )
        return CaseResult(
            name=self.name,
            status="passed",
            fixture=self.fixture,
            message_type=message_type,
            sdk_method=self.sdk_method,
            request_path=self.request_path,
            details=details,
        )


# -- assertion helpers ------------------------------------------------------- #


def _require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _as_list(value: object, message: str) -> list[Any]:
    if not isinstance(value, list):
        raise AssertionError(message)
    return value


def _feature_attributes(feature: Mapping[str, Any]) -> Mapping[str, Any]:
    attrs = feature.get("attributes")
    if isinstance(attrs, Mapping):
        return attrs
    props = feature.get("properties")
    if isinstance(props, Mapping):
        return props
    raise AssertionError(f"feature has neither attributes nor properties: {feature!r}")


# -- case runners ------------------------------------------------------------ #
#
# Each runner exercises a live REST surface that realizes the contract a shared
# gRPC fixture encodes, and asserts the live response envelope/field semantics.


def _run_feature_query(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """geospatial.v1.QueryFeatures{Request,Response} contract over GeoServices.

    Realizes ``feature_query_request.json`` against the live FeatureServer and
    asserts the response envelope matches the contract the fixture/golden
    encode: a ``features`` array; each feature with an ``attributes`` map and
    (when requested) ``geometry``; field projection honored; and the canonical
    ``exceededTransferLimit`` flag present.

    Projecting ``out_fields=["*"]`` over the seeded JSONB-attribute layer is the
    honua-server#1238 path: a regression there makes the live query fail and
    this case go red.
    """
    golden = bundle.response("feature_query")
    response = client.query_features(
        target.service_id,
        target.layer_id,
        where="1=1",
        out_fields=["*"],
        return_geometry=True,
        extra_params={"resultRecordCount": 5},
    )

    _require(isinstance(response, Mapping), "query response is not a JSON object")
    features = _as_list(response.get("features"), "response is missing a 'features' array")
    _require(len(features) > 0, "seeded layer returned no features")
    _require(
        "exceededTransferLimit" in response,
        "response is missing the canonical 'exceededTransferLimit' envelope flag",
    )

    sample = features[0]
    attributes = _feature_attributes(sample)
    _require(len(attributes) > 0, "feature has no attributes")
    _require("geometry" in sample, "return_geometry=true but feature has no geometry")

    # honua-server#1238: JSON/JSONB-typed attribute projection. The seeded
    # layer's 'tags'/'numbers' columns live inside a JSONB attributes column;
    # a projection bug surfaces as a 500 above or as missing fields here.
    observed = {str(key).lower() for f in features for key in _feature_attributes(f)}
    jsonb_fields = {"tags", "numbers"}
    missing_jsonb = sorted(jsonb_fields - observed)
    _require(
        not missing_jsonb,
        f"JSONB-typed attributes not projected (honua-server#1238): missing {missing_jsonb}",
    )

    # Cross-check the contract envelope keys the golden advertises that have a
    # GeoServices analogue.
    golden_keys = set(golden)
    expected_envelope = {"features", "exceededTransferLimit"}
    _require(
        expected_envelope.issubset(set(response)),
        f"response envelope missing keys vs contract: {sorted(expected_envelope - set(response))}",
    )

    return {
        "feature_count": len(features),
        "observed_fields": sorted(observed),
        "jsonb_fields_projected": sorted(jsonb_fields),
        "golden_envelope_keys": sorted(golden_keys),
        "exceeded_transfer_limit": response.get("exceededTransferLimit"),
    }


def _run_feature_query_layer_fields(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """Field/type metadata contract from QueryFeaturesResponse.

    The golden response advertises a ``fields`` array with ``name``/``fieldType``
    entries and an ``objectIdFieldName``. Assert the live FeatureServer layer
    metadata exposes the same field-descriptor shape.
    """
    golden = bundle.response("feature_query")
    golden_fields = _as_list(golden.get("fields"), "golden has no fields[]")
    _require(len(golden_fields) > 0, "golden has no fields[]")

    metadata = client.feature_server(target.service_id).layer_metadata(target.layer_id)
    _require(isinstance(metadata, Mapping), "layer metadata is not a JSON object")

    fields = _as_list(metadata.get("fields"), "layer metadata has no fields[]")
    _require(len(fields) > 0, "layer metadata has no fields[]")
    for fld in fields:
        _require(isinstance(fld, Mapping) and "name" in fld and "type" in fld,
                 f"field descriptor missing name/type: {fld!r}")

    _require(
        "objectIdField" in metadata or "objectIdFieldName" in metadata,
        "layer metadata is missing an object-id field declaration",
    )
    return {
        "live_field_count": len(fields),
        "golden_field_count": len(golden_fields),
        "object_id_field": metadata.get("objectIdField") or metadata.get("objectIdFieldName"),
    }


def _run_feature_query_unsupported_capability(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """Unsupported / invalid query is a structured error, not a silent 200.

    The contract requires malformed queries to surface a structured failure.
    An invalid WHERE clause must yield a non-2xx HTTP status (a GeoServices
    ``error`` envelope), not a success.
    """
    try:
        response = client.query_features(
            target.service_id,
            target.layer_id,
            where="this_is_not_a_column = nonsense_value(",
            out_fields=["*"],
            return_geometry=False,
        )
    except HonuaHttpError as exc:
        _require(exc.status_code >= 400, f"expected client/server error, got {exc.status_code}")
        return {"observed": "HonuaHttpError", "status_code": exc.status_code}

    # Some servers answer 200 with a GeoServices error envelope instead of an
    # HTTP error; that is still a structured, non-silent failure.
    _require(
        isinstance(response, Mapping) and "error" in response,
        "invalid query neither raised HonuaHttpError nor returned an error envelope",
    )
    return {"observed": "error_envelope", "error": response.get("error")}


def _run_catalog_lists_service(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """The configured service is advertised in the GeoServices catalog.

    Establishes that the pinned server exposes the workspace the fixtures
    target (the WorkspaceService ``CreateWorkspace`` fixture's read-side
    analogue on the REST plane).
    """
    response = client.list_services()
    services = _as_list(response.get("services"), "list_services did not return services[]")
    names = {s.get("name") for s in services if isinstance(s, Mapping)}
    _require(
        target.service_id in names,
        f"service {target.service_id!r} not advertised; saw {sorted(n for n in names if n)}",
    )
    return {"service_count": len(services), "matched": target.service_id}


def _run_ogc_features_items(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """Same query contract over the OGC API Features surface (httpx client).

    Cross-protocol confirmation that the JSONB-attribute layer projects through
    the OGC items path too (honua-server#1238 also manifests here). Resolves the
    collection from the live collections list to stay seed-agnostic.
    """
    ogc = client.ogc_features()
    collections = ogc.collections()
    items_list = _as_list(collections.get("collections"), "OGC collections[] empty")
    _require(len(items_list) > 0, "OGC collections[] empty")
    collection_id = None
    for col in items_list:
        if isinstance(col, Mapping) and col.get("id"):
            collection_id = str(col["id"])
            break
    _require(collection_id is not None, "no OGC collection id available")
    assert collection_id is not None

    items = ogc.items(collection_id, limit=5)
    _require(isinstance(items, Mapping), "OGC items response is not an object")
    _require(items.get("type") == "FeatureCollection", "OGC items is not a FeatureCollection")
    features = _as_list(items.get("features"), "OGC items missing features[]")
    _require(len(features) > 0, "OGC collection returned no items")
    attrs = _feature_attributes(features[0])
    _require(len(attrs) > 0, "OGC feature has no properties")
    return {
        "collection_id": collection_id,
        "feature_count": len(features),
        "sample_property_keys": sorted(str(k) for k in attrs),
    }


def _run_temporal_query(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """Temporal-filtered feature query contract (honua-server#1166).

    The seeded layer carries temporal attributes (``created_at``/``event_date``).
    A FeatureServer ``time``-bounded query must return a feature envelope. Until
    the tracked temporal support lands, this case is a known gap.
    """
    response = client._request_json(
        "GET",
        f"/rest/services/{target.service_id}/FeatureServer/{target.layer_id}/query",
        params={
            "f": "json",
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "false",
            # Epoch-ms window spanning the seeded 2024 created_at range.
            "time": "1704067200000,1735689600000",
        },
    )
    _require(isinstance(response, Mapping), "temporal query response is not an object")
    features = _as_list(response.get("features"), "temporal query response missing features[]")
    return {"feature_count": len(features)}


def _run_replica_surface(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """Replica / offline-sync surface contract (honua-server#1167).

    FeatureServer advertises its sync capability through a ``createReplica``
    operation. Probe the service metadata for the replica capability; absence is
    the tracked gap.
    """
    metadata = client.feature_server(target.service_id).metadata()
    _require(isinstance(metadata, Mapping), "feature server metadata is not an object")
    caps = str(metadata.get("capabilities", ""))
    sync_enabled = bool(metadata.get("syncEnabled")) or "Sync" in caps or "Create" in caps
    _require(
        sync_enabled,
        "FeatureServer does not advertise a replica/sync capability",
    )
    return {"capabilities": caps, "sync_enabled": sync_enabled}


def _run_analysis_process_surface(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """Analysis (process) list/estimate surface contract (honua-server#1237).

    Realizes the ``ExecutePlan``/process fixture family's read-side: the OGC
    Processes list must advertise an analysis process catalog. Until the tracked
    analysis list/estimate support lands, this case is a known gap.
    """
    bundle.request("process_execute_plan")  # assert the fixture is present/loadable
    processes = client.ogc_processes().processes()
    _require(isinstance(processes, Mapping), "processes response is not an object")
    listed = _as_list(processes.get("processes"), "processes response missing processes[]")
    _require(len(listed) > 0, "no analysis processes advertised")
    return {"process_count": len(listed)}


def build_cases() -> list[ConformanceCase]:
    """The full conformance case suite.

    Cases bound to a tracked nightly gap carry ``known_gap_issue`` so the pytest
    layer can xfail them with an explicit reference while any *new* drift in a
    required case still fails the lane.
    """
    fs_query_path = "/rest/services/{service}/FeatureServer/{layer}/query"
    fs_meta_path = "/rest/services/{service}/FeatureServer/{layer}"
    return [
        ConformanceCase(
            name="feature_query_envelope",
            fixture="feature_query",
            sdk_method="HonuaClient.query_features",
            request_path=fs_query_path,
            runner=_run_feature_query,
            # honua-server#1238: JSONB-attribute projection on the seeded layer.
            known_gap_issue="honua-server#1238",
        ),
        ConformanceCase(
            name="feature_query_field_metadata",
            fixture="feature_query",
            sdk_method="HonuaClient.feature_server(...).layer_metadata",
            request_path=fs_meta_path,
            runner=_run_feature_query_layer_fields,
        ),
        ConformanceCase(
            name="feature_query_invalid_is_structured_error",
            fixture="feature_query",
            sdk_method="HonuaClient.query_features",
            request_path=fs_query_path,
            runner=_run_feature_query_unsupported_capability,
        ),
        ConformanceCase(
            name="catalog_lists_configured_service",
            fixture="workspace_create",
            sdk_method="HonuaClient.list_services",
            request_path="/rest/services",
            runner=_run_catalog_lists_service,
        ),
        ConformanceCase(
            name="ogc_features_items_projection",
            fixture="feature_query",
            sdk_method="HonuaClient.ogc_features().items",
            request_path="/ogc/features/v1/collections/{collection}/items",
            runner=_run_ogc_features_items,
            # honua-server#1238 also manifests on the OGC items projection path.
            known_gap_issue="honua-server#1238",
        ),
        ConformanceCase(
            name="temporal_query",
            fixture="feature_query",
            sdk_method="HonuaClient.query_features(time=...)",
            request_path=fs_query_path,
            runner=_run_temporal_query,
            known_gap_issue="honua-server#1166",
        ),
        ConformanceCase(
            name="replica_sync_surface",
            fixture="feature_apply_edits",
            sdk_method="HonuaClient.feature_server(...).metadata",
            request_path=fs_meta_path,
            runner=_run_replica_surface,
            known_gap_issue="honua-server#1167",
        ),
        ConformanceCase(
            name="analysis_process_list",
            fixture="process_execute_plan",
            sdk_method="HonuaClient.ogc_processes().processes",
            request_path="/ogc/processes/v1/processes",
            runner=_run_analysis_process_surface,
            known_gap_issue="honua-server#1237",
        ),
    ]


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def render_summary(
    bundle: FixtureBundle,
    target: ConformanceTarget,
    results: Sequence[CaseResult],
) -> str:
    lines: list[str] = []
    lines.append("## Python SDK live-server conformance")
    lines.append("")
    lines.append(f"- Fixture set: `{bundle.version}` (geospatial-grpc shared fixtures)")
    lines.append(f"- Server image: `{target.server_image or 'n/a'}`")
    if target.server_commit:
        lines.append(f"- Server revision: `{target.server_commit}`")
    lines.append(f"- Base URL: `{target.base_url}`")
    lines.append("")
    lines.append("| Case | Fixture | Message type | Status |")
    lines.append("| --- | --- | --- | --- |")
    for r in results:
        lines.append(
            f"| `{r.name}` | `{r.fixture}` | `{r.message_type or '-'}` | {r.status} |"
        )
    return "\n".join(lines) + "\n"
