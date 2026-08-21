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
JSONB-attribute layer failing with ``column ... does not exist``, closed
2026-05-31 and re-verified live 2026-07-10) is caught because the seeded
``test_service`` layer stores every attribute in a JSONB column and a
dedicated ``*_jsonb_projection`` case projects the JSON-typed
``tags``/``numbers`` fields out of it — kept structurally separate from the
core ``feature_query_envelope`` / ``ogc_features_items`` read-contract cases
(features array, ``exceededTransferLimit``, FeatureCollection shape, etc.) so
a regression in one is never silently absorbed by an xfail meant for the
other.

Known, already-tracked nightly gaps are reported as ``known_gap`` cases (the
pytest layer turns these into ``xfail`` with explicit issue references) so the
lane stays green while the harness is in place, yet any *new* drift still fails.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
    server_image_digest: str | None = None
    sdk_source_sha: str | None = None
    evidence_uri: str | None = None
    candidate_cut_at: str | None = None
    certification_tier: str = "nightly"


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
        server_image_digest=os.environ.get("HONUA_SERVER_IMAGE_DIGEST"),
        sdk_source_sha=os.environ.get("HONUA_SDK_SOURCE_SHA"),
        evidence_uri=os.environ.get("HONUA_EVIDENCE_URI"),
        candidate_cut_at=os.environ.get("HONUA_CANDIDATE_CUT_AT"),
        certification_tier=os.environ.get("HONUA_CERTIFICATION_TIER", "nightly"),
    )


# --------------------------------------------------------------------------- #
# Conformance cases
# --------------------------------------------------------------------------- #

#: Tracked nightly server gaps. A case bound to one of these is reported as a
#: known gap (xfail at the pytest layer) until the server fix lands, at which
#: point the case flips to required. Keep references explicit — never silent.
#:
#: honua-server#1238 (JSONB-attribute projection) and honua-server#1237
#: (analysis process list/estimate) were closed 2026-05-31 and re-verified
#: live against a seeded honua-server:nightly-20260530 target on 2026-07-10:
#: both now genuinely pass, so no case references them any more (removed
#: rather than left dangling).
KNOWN_SERVER_GAPS: dict[str, str] = {
    "honua-server#2643": (
        "client-compat-v1.sql seed does not set timeInfo for test_service "
        "layer 0, so FeatureServer time= queries 400 as non-time-aware "
        "(by-design per honua-server#1444) instead of filtering. NOTE: the "
        "temporal_query case previously carried honua-server#1166, which was "
        "re-verified 2026-07-10 to be an unrelated, already-closed as-of/"
        "diff/rollback history API with no bearing on the time= query filter; "
        "honua-server#2643 is the correct, newly-filed reference for the "
        "actual seed gap this case hits."
    ),
    "honua-server#2645": (
        "client-compat-v1.sql seed hardcodes an empty Metadata-V2 'options' "
        "object for test_service, so the already-implemented Sync capability "
        "advertisement (BuildServiceCapabilitiesV2/ServiceSupportsSyncV2) can "
        "never surface a 'Sync' token / syncEnabled field for the seeded "
        "layer. NOTE: the replica_sync_surface case previously carried "
        "honua-server#1167, which was re-verified 2026-07-10 to be an "
        "unrelated, already-closed admin conflict-review/named-replica API "
        "with no bearing on FeatureServer capability advertisement; "
        "honua-server#2645 is the correct, newly-filed reference for the "
        "actual seed gap this case hits."
    ),
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
    started_at: str
    completed_at: str
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
        started_at = _utc_now()
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
                started_at=started_at,
                completed_at=_utc_now(),
                error=f"{type(exc).__name__}: {exc}",
            )
        return CaseResult(
            name=self.name,
            status="passed",
            fixture=self.fixture,
            message_type=message_type,
            sdk_method=self.sdk_method,
            request_path=self.request_path,
            started_at=started_at,
            completed_at=_utc_now(),
            details=details,
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    (when requested) ``geometry``; and the canonical ``exceededTransferLimit``
    flag present. This is the core read contract and is unconditionally
    required — it does not carry a ``known_gap_issue``, so it can never go
    silently advisory. The JSONB-typed-attribute-projection behavior is a
    narrower, separately tracked concern; see
    :func:`_run_feature_query_jsonb_projection`.
    """
    golden = bundle.response("feature_query")
    page_size = 5
    response = client.query_features(
        target.service_id,
        target.layer_id,
        where="1=1",
        out_fields=["*"],
        return_geometry=True,
        extra_params={
            "resultOffset": 0,
            "resultRecordCount": page_size,
            "orderByFields": "objectid ASC",
        },
    )

    _require(isinstance(response, Mapping), "query response is not a JSON object")
    features = _as_list(response.get("features"), "response is missing a 'features' array")
    _require(len(features) == page_size, "first page did not honor resultRecordCount")
    _require(
        response.get("exceededTransferLimit") is True,
        "first page did not prove a continuation with exceededTransferLimit=true",
    )

    sample = features[0]
    attributes = _feature_attributes(sample)
    _require(len(attributes) > 0, "feature has no attributes")
    _require("geometry" in sample, "return_geometry=true but feature has no geometry")

    # Cross-check the contract envelope keys the golden advertises that have a
    # GeoServices analogue.
    golden_keys = set(golden)
    expected_envelope = {"features", "exceededTransferLimit"}
    _require(
        expected_envelope.issubset(set(response)),
        f"response envelope missing keys vs contract: {sorted(expected_envelope - set(response))}",
    )

    second_response = client.query_features(
        target.service_id,
        target.layer_id,
        where="1=1",
        out_fields=["*"],
        return_geometry=True,
        extra_params={
            "resultOffset": page_size,
            "resultRecordCount": page_size,
            "orderByFields": "objectid ASC",
        },
    )
    _require(isinstance(second_response, Mapping), "second page is not a JSON object")
    second_features = _as_list(
        second_response.get("features"), "second page is missing a 'features' array"
    )
    _require(0 < len(second_features) <= page_size, "second page is empty or unbounded")
    _require(
        "exceededTransferLimit" in second_response,
        "second page is missing exceededTransferLimit",
    )
    for feature in second_features:
        _require(len(_feature_attributes(feature)) > 0, "second-page feature has no attributes")
        _require("geometry" in feature, "second-page feature has no geometry")

    def object_ids(page: list[Any]) -> list[Any]:
        ids: list[Any] = []
        for feature in page:
            attributes = _feature_attributes(feature)
            normalized = {str(key).lower(): value for key, value in attributes.items()}
            _require("objectid" in normalized, "feature is missing its objectid attribute")
            ids.append(normalized["objectid"])
        return ids

    first_ids = object_ids(features)
    second_ids = object_ids(second_features)
    _require(first_ids == sorted(first_ids), "first page is not ordered by objectid")
    _require(second_ids == sorted(second_ids), "second page is not ordered by objectid")
    _require(first_ids[-1] < second_ids[0], "feature-query pages are not ordered and non-overlapping")

    return {
        "feature_count": len(features) + len(second_features),
        "first_page_count": len(features),
        "second_page_count": len(second_features),
        "first_page_object_ids": first_ids,
        "second_page_object_ids": second_ids,
        "golden_envelope_keys": sorted(golden_keys),
        "exceeded_transfer_limit": response["exceededTransferLimit"],
    }


def _run_feature_query_jsonb_projection(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """JSON/JSONB-typed attribute projection over GeoServices FeatureServer.

    Split out from :func:`_run_feature_query` so a regression here (or in the
    core read contract) is attributable to the right failure mode instead of
    both being hidden behind one ``known_gap`` xfail. Projecting
    ``out_fields=["*"]`` over the seeded JSONB-attribute layer is the
    honua-server#1238 path: a regression there makes the live query fail
    outright or silently drop the 'tags'/'numbers' fields.
    """
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

    observed = _validate_seeded_json_fields(features, "FeatureServer")
    jsonb_fields = {"tags", "numbers"}
    return {
        "feature_count": len(features),
        "observed_fields": sorted(observed),
        "jsonb_fields_projected": sorted(jsonb_fields),
    }


def _validate_seeded_json_fields(features: list[Any], surface: str) -> set[str]:
    observed: set[str] = set()
    for feature in features:
        attributes = {str(key).lower(): value for key, value in _feature_attributes(feature).items()}
        observed.update(attributes)
        missing = sorted({"tags", "numbers"} - attributes.keys())
        _require(not missing, f"{surface} JSON field projection is missing {missing}")

        tags = attributes["tags"]
        _require(
            isinstance(tags, list) and all(isinstance(value, str) for value in tags),
            f"{surface} tags value/type drift: expected an array of strings, got {tags!r}",
        )
        numbers = attributes["numbers"]
        _require(
            isinstance(numbers, list)
            and all(isinstance(value, int) and not isinstance(value, bool) for value in numbers),
            f"{surface} numbers must be an array of integers, got {numbers!r}",
        )
    return observed


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

    def field_family(value: str) -> str:
        token = value.upper().replace("ESRIFIELDTYPE", "").replace("FIELD_TYPE_", "")
        if token in {"OID", "BIG_INTEGER", "INTEGER", "SMALL_INTEGER", "LONG"}:
            return "integer"
        if token in {"SINGLE", "DOUBLE", "FLOAT"}:
            return "floating"
        if token in {"STRING", "TEXT"}:
            return "string"
        return token.lower()

    expected_fields: dict[str, str] = {}
    for fld in golden_fields:
        _require(isinstance(fld, Mapping), f"golden field descriptor is invalid: {fld!r}")
        name = fld.get("name")
        field_type = fld.get("fieldType")
        _require(isinstance(name, str) and bool(name.strip()), f"golden field name is invalid: {name!r}")
        _require(
            isinstance(field_type, str) and bool(field_type.strip()),
            f"golden field type is invalid for {name!r}: {field_type!r}",
        )
        expected_fields[name.casefold()] = field_family(field_type)

    live_fields: dict[str, str] = {}
    for fld in fields:
        _require(isinstance(fld, Mapping), f"field descriptor is invalid: {fld!r}")
        name = fld.get("name")
        field_type = fld.get("type")
        _require(isinstance(name, str) and bool(name.strip()), f"field name is invalid: {name!r}")
        _require(
            isinstance(field_type, str) and bool(field_type.strip()),
            f"field type is invalid for {name!r}: {field_type!r}",
        )
        live_fields[name.casefold()] = field_family(field_type)

    missing_fields = sorted(set(expected_fields) - set(live_fields))
    _require(not missing_fields, f"layer metadata is missing golden fields: {missing_fields}")
    mismatched_types = sorted(
        name for name, family in expected_fields.items() if live_fields[name] != family
    )
    _require(not mismatched_types, f"layer metadata field types drifted: {mismatched_types}")

    expected_object_id = golden.get("objectIdFieldName")
    live_object_id = metadata.get("objectIdField") or metadata.get("objectIdFieldName")
    _require(
        isinstance(expected_object_id, str) and bool(expected_object_id.strip()),
        "golden response has no objectIdFieldName",
    )
    _require(
        isinstance(live_object_id, str)
        and live_object_id.casefold() == expected_object_id.casefold(),
        f"layer object-id field drifted: expected {expected_object_id!r}, got {live_object_id!r}",
    )
    return {
        "live_field_count": len(fields),
        "golden_field_count": len(golden_fields),
        "object_id_field": live_object_id,
        "matched_fields": sorted(expected_fields),
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
        _require(400 <= exc.status_code < 500, f"expected client error, got {exc.status_code}")
        _require(isinstance(exc.body, Mapping), "invalid query HTTP error body is not structured JSON")
        error = exc.body.get("error")
        _require(isinstance(error, Mapping), "invalid query body is missing a structured error envelope")
        code = error.get("code")
        message = error.get("message")
        _require(isinstance(code, int) and 400 <= code < 500, f"unexpected error code {code!r}")
        _require(isinstance(message, str) and bool(message.strip()), "error envelope is missing a message")
        return {
            "observed": "HonuaHttpError",
            "status_code": exc.status_code,
            "error_code": code,
            "error_message": message,
        }

    # Some servers answer 200 with a GeoServices error envelope instead of an
    # HTTP error; that is still a structured, non-silent failure.
    _require(isinstance(response, Mapping), "invalid query response is not structured JSON")
    error = response.get("error")
    _require(isinstance(error, Mapping), "invalid query response is missing an error envelope")
    code = error.get("code")
    message = error.get("message")
    _require(isinstance(code, int) and 400 <= code < 500, f"unexpected error code {code!r}")
    _require(isinstance(message, str) and bool(message.strip()), "error envelope is missing a message")
    return {"observed": "error_envelope", "error_code": code, "error_message": message}


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


def _configured_ogc_collection_candidates(target: ConformanceTarget) -> list[str]:
    """OGC collection ids honua-server may expose for the configured target.

    honua-server derives an OGC API Features collection id from the layer
    publication's ``serviceLocalId`` (see honua-server
    ``CollectionsEndpoints.CreateCollectionAsync``:
    ``collectionId = publication.ServiceLocalId ?? publication.Path
    ?? resource.Metadata.Name``). For the seeded ``test_service`` layer 0 the
    ``ogc-collection`` publication's ``serviceLocalId`` is the layer index as
    text (``"0"``). Other deployments/naming schemes may instead expose the
    collection under the service id or a service-qualified composite, so accept
    the known equivalent forms. Service-qualified candidates are tried first so
    they win over the bare layer-index form when a server uses them; the bare
    ``str(layer_id)`` is the seeded default and is matched last.
    """
    sid = target.service_id
    lid = target.layer_id
    return [
        f"{sid}_{lid}",
        f"{sid}.{lid}",
        f"{sid}/{lid}",
        f"{sid}:{lid}",
        f"{sid}-{lid}",
        sid,
        str(lid),
    ]


def _resolve_ogc_collection_id(client: HonuaClient, target: ConformanceTarget) -> str:
    """Resolve the OGC API Features collection for the configured target.

    Selects the advertised collection that corresponds to the
    ``HONUA_SERVICE_ID``/``HONUA_LAYER_ID`` conformance target rather than
    whichever collection the server happens to list first. On a live target
    advertising multiple collections, taking the first would let the required
    OGC cases pass or fail against an unrelated collection and stop validating
    the seeded ``test_service``/layer 0. If no advertised collection matches the
    configured target we fail with a clear error instead of silently falling
    back to the first.
    """
    ogc = client.ogc_features()
    collections = ogc.collections()
    items_list = _as_list(collections.get("collections"), "OGC collections[] empty")
    _require(len(items_list) > 0, "OGC collections[] empty")

    advertised: list[str] = []
    by_id: dict[str, str] = {}
    for col in items_list:
        if isinstance(col, Mapping) and col.get("id"):
            cid = str(col["id"])
            advertised.append(cid)
            # First writer wins so the earliest-listed id is the one returned on
            # a (server-side) duplicate; case-insensitive to tolerate casing.
            by_id.setdefault(cid.casefold(), cid)
    _require(len(advertised) > 0, "no OGC collection id available")

    for candidate in _configured_ogc_collection_candidates(target):
        matched = by_id.get(candidate.casefold())
        if matched is not None:
            return matched

    raise AssertionError(
        "no advertised OGC collection matches the configured conformance target "
        f"(service_id={target.service_id!r}, layer_id={target.layer_id!r}); "
        f"tried {_configured_ogc_collection_candidates(target)!r} against "
        f"advertised {sorted(advertised)!r}. Refusing to fall back to the first "
        "collection so the required OGC cases keep validating the seeded target."
    )


def _run_ogc_features_items(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """Same query contract over the OGC API Features surface (httpx client).

    Core read contract: a FeatureCollection with non-empty items and
    non-empty per-feature properties. Unconditionally required — it does not
    carry a ``known_gap_issue``. The JSONB-typed-attribute-projection
    behavior is a narrower, separately tracked concern; see
    :func:`_run_ogc_features_items_jsonb_projection`.
    """
    collection_id = _resolve_ogc_collection_id(client, target)
    ogc = client.ogc_features()

    pages = iter(ogc.items_pages(collection_id, page_size=1, limit=2, max_pages=2))
    items = next(pages, None)
    _require(isinstance(items, Mapping), "OGC items response is not an object")
    _require(items.get("type") == "FeatureCollection", "OGC items is not a FeatureCollection")
    features = _as_list(items.get("features"), "OGC items missing features[]")
    _require(len(features) == 1, f"OGC limit=1 returned {len(features)} features")
    attrs = _feature_attributes(features[0])
    _require(len(attrs) > 0, "OGC feature has no properties")
    number_matched = items.get("numberMatched")
    _require(
        isinstance(number_matched, int) and not isinstance(number_matched, bool) and number_matched >= 2,
        f"OGC paging fixture must report numberMatched >= 2, got {number_matched!r}",
    )
    links = _as_list(items.get("links"), "OGC items missing links[]")
    next_links = [
        link for link in links
        if isinstance(link, Mapping) and link.get("rel") == "next" and isinstance(link.get("href"), str)
    ]
    _require(bool(next_links), "OGC first page did not advertise a rel=next continuation link")

    next_href = next_links[0]["href"]
    target_authority = urlsplit(target.base_url)
    next_authority = urlsplit(next_href)
    if next_authority.netloc:
        _require(
            (next_authority.scheme.lower(), next_authority.netloc.lower())
            == (target_authority.scheme.lower(), target_authority.netloc.lower()),
            "OGC Features next link changed deployment authority",
        )
    # Continuation links are opaque. The SDK's public page walker follows the
    # complete advertised URL, preserving path, cursor, and vendor parameters.
    second_page = next(pages, None)
    _require(isinstance(second_page, Mapping), "OGC second page response is not an object")
    _require(
        second_page.get("type") == "FeatureCollection",
        "OGC second page is not a FeatureCollection",
    )
    second_features = _as_list(second_page.get("features"), "OGC second page missing features[]")
    _require(len(second_features) == 1, f"OGC second limit=1 page returned {len(second_features)} features")
    second_attrs = _feature_attributes(second_features[0])
    _require(len(second_attrs) > 0, "OGC second-page feature has no properties")
    first_id = features[0].get("id") if isinstance(features[0], Mapping) else None
    second_id = second_features[0].get("id") if isinstance(second_features[0], Mapping) else None
    _require(first_id is not None and second_id is not None, "OGC paged features must carry stable ids")
    _require(first_id != second_id, "OGC offset=1 repeated the first page feature")
    return {
        "collection_id": collection_id,
        "feature_count": len(features),
        "number_matched": number_matched,
        "next_href": next_href,
        "second_page_feature_id": second_id,
        "sample_property_keys": sorted(str(k) for k in attrs),
    }


def _run_ogc_features_items_jsonb_projection(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """JSON/JSONB-typed attribute projection over the OGC API Features surface.

    Cross-protocol confirmation that the JSONB-attribute layer projects
    through the OGC items path too (honua-server#1238 also manifests here).
    Split out from :func:`_run_ogc_features_items` so a regression here is
    attributable to the right failure mode instead of hiding the core OGC
    read contract behind the same xfail.
    """
    collection_id = _resolve_ogc_collection_id(client, target)
    ogc = client.ogc_features()

    items = ogc.items(collection_id, limit=5)
    _require(isinstance(items, Mapping), "OGC items response is not an object")
    features = _as_list(items.get("features"), "OGC items missing features[]")
    _require(len(features) > 0, "OGC collection returned no items")

    _validate_seeded_json_fields(features, "OGC API Features")
    jsonb_fields = {"tags", "numbers"}
    return {
        "collection_id": collection_id,
        "feature_count": len(features),
        "jsonb_fields_projected": sorted(jsonb_fields),
    }


def _run_temporal_query(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """Temporal-filtered feature query contract (honua-server#2643).

    The seeded layer carries temporal attributes (``created_at``/``event_date``).
    A FeatureServer ``time``-bounded query must actually *constrain* results by
    the window — not merely accept and ignore an unknown ``time`` param. We
    therefore compare three queries: unfiltered, an in-range window, and a
    disjoint (pre-seed) window. A server that ignores ``time`` returns the same
    set for the disjoint window as for the unfiltered query, which fails the
    probe instead of producing a false green PASS.

    Re-verified 2026-07-10: this previously carried honua-server#1166, but that
    issue is closed and delivers an unrelated as-of/diff/rollback temporal
    *history* API — it has no bearing on the classic FeatureServer ``time=``
    query filter. Live re-run against a seeded honua-server:nightly-20260530
    target shows the *actual* blocker is that ``tests/seed/client-compat-v1.sql``
    never sets ``timeInfo`` on ``test_service`` layer 0, so the layer is not
    time-aware and any non-empty ``time=`` value 400s by design (see
    honua-server#1444, closed "by design"). honua-server#2643 tracks that seed
    gap; until it lands, this case stays a known gap under the corrected
    reference.
    """
    path = f"/rest/services/{target.service_id}/FeatureServer/{target.layer_id}/query"

    def _query(time_window: str | None) -> list[Any]:
        params: dict[str, Any] = {
            "f": "json",
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "false",
        }
        if time_window is not None:
            params["time"] = time_window
        response = client._request_json("GET", path, params=params)
        _require(isinstance(response, Mapping), "temporal query response is not an object")
        return _as_list(response.get("features"), "temporal query response missing features[]")

    unfiltered = _query(None)
    # Epoch-ms window spanning the seeded 2024 created_at range.
    in_window = _query("1704067200000,1735689600000")
    # Disjoint window in 1970, strictly before any seeded 2024 data: a server
    # that honors ``time`` must return fewer features here than the unfiltered
    # baseline; one that ignores it returns the full set.
    disjoint = _query("0,1")

    _require(len(unfiltered) > 0, "baseline (unfiltered) query returned no features")
    _require(len(in_window) > 0, "seeded in-range temporal window returned no features")
    _require(
        len(disjoint) == 0,
        "time filter leaked seeded features into the disjoint pre-seed window: "
        f"expected 0, got {len(disjoint)}",
    )
    return {
        "feature_count": len(in_window),
        "unfiltered_count": len(unfiltered),
        "disjoint_count": len(disjoint),
    }


def _run_replica_surface(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """Replica / offline-sync surface contract (honua-server#2645).

    FeatureServer advertises its sync capability through a ``createReplica``
    operation. Probe the service metadata for the replica capability; absence is
    the tracked gap.

    Re-verified 2026-07-10: this previously carried honua-server#1167, but
    that issue is closed and delivers an unrelated admin conflict-review /
    named-replica-listing API — it has no bearing on the FeatureServer
    ``capabilities``/``syncEnabled`` advertisement checked here. Live re-run
    against a seeded honua-server:nightly-20260530 target shows the *actual*
    blocker is that ``tests/seed/client-compat-v1.sql``'s synthetic
    Metadata-V2 snapshot hardcodes an empty ``options`` object for
    ``test_service``, so the already-implemented Sync-capability advertisement
    (``BuildServiceCapabilitiesV2``/``ServiceSupportsSyncV2``, gated on
    ``Options["capabilities"]``) can never surface a ``"Sync"`` token for this
    seeded layer. honua-server#2645 tracks that seed gap; until it lands, this
    case stays a known gap under the corrected reference.
    """
    metadata = client.feature_server(target.service_id).metadata()
    _require(isinstance(metadata, Mapping), "feature server metadata is not an object")
    caps_value = metadata.get("capabilities", "")
    _require(isinstance(caps_value, str), "FeatureServer capabilities must be a string")
    caps = caps_value
    # Gate strictly on sync/replica signals. The old ``"Create" in caps``
    # disjunct matched the unrelated ``Create`` editing capability that *any*
    # editable FeatureServer advertises, so this probe reported replica/sync
    # support present when it was absent.
    caps_tokens = {token.strip().lower() for token in caps.split(",")}
    sync_enabled = (
        metadata.get("syncEnabled") is True
        or "sync" in caps_tokens
        or "createreplica" in caps_tokens
    )
    _require(
        sync_enabled,
        "FeatureServer does not advertise a replica/sync capability",
    )
    return {"capabilities": caps, "sync_enabled": sync_enabled}


def _run_analysis_process_surface(
    client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle
) -> dict[str, Any]:
    """Analysis (process) list/estimate surface contract.

    Realizes the ``ExecutePlan``/process fixture family's read-side: the OGC
    Processes list must advertise an analysis process catalog. Previously
    tracked as honua-server#1237 (closed 2026-05-31); re-verified passing live
    2026-07-10 against a seeded honua-server:nightly-20260530 target, so this
    is now an unconditionally required assertion.
    """
    request = bundle.request("process_execute_plan")
    plan = request.get("plan") if isinstance(request, Mapping) else None
    steps = _as_list(plan.get("steps") if isinstance(plan, Mapping) else None,
                     "process fixture has no plan.steps[]")
    fixture_kinds = {
        str(step["kind"]).strip().lower().replace("_", "-")
        for step in steps
        if isinstance(step, Mapping) and isinstance(step.get("kind"), str) and step["kind"].strip()
    }
    _require(bool(fixture_kinds), "process fixture has no executable step kinds")

    # The vendor-neutral ExecutePlan fixture describes abstract workflow kinds,
    # while OGC API Processes advertises Honua's executable catalog identifiers.
    # Keep that translation explicit so a merely non-empty or unrelated catalog
    # cannot certify the fixture's source-query and aggregation capabilities.
    fixture_process_ids = {
        "query-features": "source.honua-layer",
        "aggregate": "transform.aggregate",
    }
    unmapped_kinds = sorted(fixture_kinds - fixture_process_ids.keys())
    _require(not unmapped_kinds, f"process fixture has unmapped step kinds: {unmapped_kinds}")
    expected_ids = {fixture_process_ids[kind] for kind in fixture_kinds}

    processes = client.ogc_processes().processes()
    _require(isinstance(processes, Mapping), "processes response is not an object")
    listed = _as_list(processes.get("processes"), "processes response missing processes[]")
    _require(len(listed) > 0, "no analysis processes advertised")
    advertised_ids: set[str] = set()
    for process in listed:
        _require(isinstance(process, Mapping), f"process entry is not an object: {process!r}")
        process_id = process.get("id") or process.get("identifier")
        _require(
            isinstance(process_id, str) and bool(process_id.strip()),
            f"process entry has no identifier: {process!r}",
        )
        advertised_ids.add(process_id.strip().lower().replace("_", "-"))
    missing = sorted(expected_ids - advertised_ids)
    _require(
        not missing,
        f"process catalog is missing fixture capabilities {missing!r}",
    )
    return {
        "process_count": len(listed),
        "fixture_kinds": sorted(fixture_kinds),
        "matched_fixture_processes": sorted(expected_ids),
    }


def build_cases() -> list[ConformanceCase]:
    """The full conformance case suite.

    Cases bound to a tracked nightly gap carry ``known_gap_issue`` so the pytest
    layer can xfail them with an explicit reference while any *new* drift in a
    required case still fails the lane.

    The core read-contract cases for ``feature_query`` and
    ``ogc_features_items`` are unconditionally required (no ``known_gap_issue``)
    and are kept structurally separate from their narrower
    JSONB-attribute-projection variants, so a regression in one is never
    silently absorbed by an xfail meant for the other.
    """
    fs_query_path = "/rest/services/{service}/FeatureServer/{layer}/query"
    fs_meta_path = "/rest/services/{service}/FeatureServer/{layer}"
    ogc_items_path = "/ogc/features/v1/collections/{collection}/items"
    return [
        ConformanceCase(
            name="feature_query_envelope",
            fixture="feature_query",
            sdk_method="HonuaClient.query_features",
            request_path=fs_query_path,
            runner=_run_feature_query,
        ),
        ConformanceCase(
            name="feature_query_jsonb_projection",
            fixture="feature_query",
            sdk_method="HonuaClient.query_features",
            request_path=fs_query_path,
            runner=_run_feature_query_jsonb_projection,
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
            name="ogc_features_items",
            fixture="feature_query",
            sdk_method="HonuaClient.ogc_features().items",
            request_path=ogc_items_path,
            runner=_run_ogc_features_items,
        ),
        ConformanceCase(
            name="ogc_features_items_jsonb_projection",
            fixture="feature_query",
            sdk_method="HonuaClient.ogc_features().items",
            request_path=ogc_items_path,
            runner=_run_ogc_features_items_jsonb_projection,
        ),
        ConformanceCase(
            name="temporal_query",
            fixture="feature_query",
            sdk_method="HonuaClient.query_features(time=...)",
            request_path=fs_query_path,
            runner=_run_temporal_query,
            known_gap_issue="honua-server#2643",
        ),
        ConformanceCase(
            name="replica_sync_surface",
            fixture="feature_apply_edits",
            sdk_method="HonuaClient.feature_server(...).metadata",
            request_path=fs_meta_path,
            runner=_run_replica_surface,
            known_gap_issue="honua-server#2645",
        ),
        ConformanceCase(
            name="analysis_process_list",
            fixture="process_execute_plan",
            sdk_method="HonuaClient.ogc_processes().processes",
            request_path="/ogc/processes/v1/processes",
            runner=_run_analysis_process_surface,
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


CASE_CERTIFICATION: dict[str, tuple[str, str, str, list[str]]] = {
    "feature_query_envelope": (
        "serve.geoservices-featureserver", "geoservices-featureserver", "query", ["positive", "pagination"]
    ),
    "feature_query_jsonb_projection": (
        "serve.geoservices-featureserver", "geoservices-featureserver", "query-json-fields", ["positive", "media-schema"]
    ),
    "feature_query_field_metadata": (
        "serve.geoservices-featureserver", "geoservices-featureserver", "layer-metadata", ["positive", "metadata"]
    ),
    "feature_query_invalid_is_structured_error": (
        "serve.geoservices-featureserver", "geoservices-featureserver", "query-invalid", ["negative", "media-schema"]
    ),
    "catalog_lists_configured_service": (
        "serve.geoservices-root", "geoservices-root", "list-services", ["positive", "metadata"]
    ),
    "ogc_features_items": (
        "serve.ogc-api-features", "ogc-api-features", "items", ["positive", "pagination"]
    ),
    "ogc_features_items_jsonb_projection": (
        "serve.ogc-api-features", "ogc-api-features", "items-json-fields", ["positive", "media-schema"]
    ),
    "temporal_query": (
        "serve.geoservices-featureserver", "geoservices-featureserver", "temporal-query", ["positive", "boundary"]
    ),
    "replica_sync_surface": (
        "editing.featureserver-edits", "geoservices-featureserver", "sync-capability", ["positive", "metadata"]
    ),
    "analysis_process_list": (
        "process.ogc-api-processes", "ogc-api-processes", "list-processes", ["positive", "metadata"]
    ),
}


def build_certification_fragment(
    bundle: FixtureBundle,
    target: ConformanceTarget,
    case_results: Sequence[tuple[ConformanceCase, CaseResult]],
) -> dict[str, Any]:
    """Normalize live SDK case outcomes for the central evidence ledger."""
    missing_target = [
        name
        for name, value in {
            "server_commit": target.server_commit,
            "server_image_digest": target.server_image_digest,
            "evidence_uri": target.evidence_uri,
            "candidate_cut_at": target.candidate_cut_at,
        }.items()
        if not value
    ]
    if missing_target:
        raise ConformanceFixturesError(
            "normalized certification evidence needs " + ", ".join(missing_target)
        )

    client_version = importlib.metadata.version("honua-sdk")
    observations: list[dict[str, Any]] = []
    for case, result in case_results:
        capability_key, surface, operation, facets = CASE_CERTIFICATION[case.name]
        known_gap = case.known_gap_issue if result.status != "passed" else None
        observations.append(
            {
                "surface": surface,
                "operation": operation,
                "canonical_client": "honua-sdk-python",
                "client_version": client_version,
                "deployment_target": "local-docker",
                "result": "pass" if result.status == "passed" else "fail",
                "skip_reason": known_gap,
                "source_sha": target.server_commit,
                "image_digest": target.server_image_digest,
                "fixture_revision": (
                    f"geospatial-grpc@{bundle.version};"
                    f"honua-sdk-python@{target.sdk_source_sha or 'unknown'};"
                    f"capability={capability_key};facets={','.join(facets)}"
                ),
                "evidence_uri": target.evidence_uri,
                "started_at": result.started_at,
                "completed_at": result.completed_at,
            }
        )

    return {
        "schema": "honua.protocol-certification-fragment/v1",
        "producer": "honua-sdk-python",
        "generated_at": _utc_now(),
        "candidate": {
            "source_sha": target.server_commit,
            "image_digest": target.server_image_digest,
            "cut_at": target.candidate_cut_at,
        },
        "observations": observations,
    }
