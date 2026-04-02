"""Shared staging smoke helpers for pytest and release validation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from honua_sdk import HonuaClient, HonuaHttpError

DEFAULT_SERVICE_ID = "test_service"
DEFAULT_LAYER_ID = 0
DEFAULT_UID_PREFIX = "sdk-python-smoke"
DEFAULT_RESULTS_PATH = Path("staging-smoke-results.json")
EXPECTED_QUERY_FIELDS = frozenset({"objectid", "name", "status", "count", "ratio"})
READ_QUERY_LIMIT = 2
WRITE_QUERY_LIMIT = 25
INITIAL_GEOMETRY = {"x": -122.4013, "y": 37.7925}
UPDATED_GEOMETRY = {"x": -122.4008, "y": 37.7931}


class SmokeConfigError(ValueError):
    """Raised when the staging smoke configuration is invalid."""


@dataclass
class SmokeConfig:
    base_url: str
    service_id: str = DEFAULT_SERVICE_ID
    layer_id: int = DEFAULT_LAYER_ID
    api_key: str | None = None
    enable_write_smoke: bool = False
    uid_prefix: str = DEFAULT_UID_PREFIX
    results_path: Path = DEFAULT_RESULTS_PATH

    def target_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "service_id": self.service_id,
            "layer_id": self.layer_id,
            "write_smoke_enabled": self.enable_write_smoke,
            "uid_prefix": self.uid_prefix,
        }


ProbeStatus = Literal["passed", "failed", "skipped"]


@dataclass
class ProbeResult:
    name: str
    status: ProbeStatus
    required: bool
    started_at: str
    completed_at: str
    details: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "status": self.status,
            "required": self.required,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "details": self.details,
        }
        if self.error is not None:
            payload["error"] = self.error
        return payload


@dataclass
class SmokeReport:
    config: SmokeConfig
    started_at: str = field(default_factory=lambda: utc_now())
    probes: list[ProbeResult] = field(default_factory=list)
    completed_at: str | None = None

    def record(self, probe: ProbeResult) -> ProbeResult:
        self.probes.append(probe)
        return probe

    def finish(self) -> None:
        if self.completed_at is None:
            self.completed_at = utc_now()

    @property
    def overall_status(self) -> str:
        if any(probe.required and probe.status == "failed" for probe in self.probes):
            return "failed"
        return "passed"

    def counts(self) -> dict[str, int]:
        counts = {"passed": 0, "failed": 0, "skipped": 0}
        for probe in self.probes:
            counts[probe.status] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        self.finish()
        return {
            "schema_version": 1,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "overall_status": self.overall_status,
            "target": self.config.target_dict(),
            "probe_counts": self.counts(),
            "probes": [probe.to_dict() for probe in self.probes],
        }

    def write(self, path: str | Path | None = None) -> Path:
        output_path = Path(path or self.config.results_path)
        if output_path.parent != Path("."):
            output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return output_path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_smoke_config_from_env(*, require_base_url: bool = True) -> SmokeConfig:
    base_url = _read_env("HONUA_BASE_URL")
    if not base_url:
        if require_base_url:
            raise SmokeConfigError("HONUA_BASE_URL is required for staging smoke runs.")
        raise SmokeConfigError("HONUA_BASE_URL is not configured.")

    layer_text = _read_env("HONUA_LAYER_ID") or str(DEFAULT_LAYER_ID)
    try:
        layer_id = int(layer_text)
    except ValueError as exc:
        raise SmokeConfigError("HONUA_LAYER_ID must be an integer.") from exc

    return SmokeConfig(
        base_url=base_url,
        service_id=_read_env("HONUA_SERVICE_ID") or DEFAULT_SERVICE_ID,
        layer_id=layer_id,
        api_key=_read_env("HONUA_API_KEY"),
        enable_write_smoke=_read_bool_env("HONUA_ENABLE_WRITE_SMOKE", default=False),
        uid_prefix=_read_env("HONUA_SMOKE_UID_PREFIX") or DEFAULT_UID_PREFIX,
        results_path=Path(_read_env("HONUA_SMOKE_RESULTS_PATH") or DEFAULT_RESULTS_PATH),
    )


def _serialize_probe_exception(exc: Exception) -> dict[str, Any]:
    message = exc.message if isinstance(exc, HonuaHttpError) else str(exc)
    payload = {
        "type": type(exc).__name__,
        "message": message,
    }
    if isinstance(exc, HonuaHttpError):
        payload["status_code"] = exc.status_code
        payload["body"] = exc.body
    return payload


def _probe_error_context(
    context: Mapping[str, Any] | None,
    exc: Exception,
) -> dict[str, Any]:
    error_context = dict(context or {})
    cleanup_error = getattr(exc, "_smoke_cleanup_error", None)
    if cleanup_error is not None:
        error_context["cleanup_error"] = dict(cleanup_error)
    return error_context


def _attach_cleanup_error(main_error: Exception, cleanup_error: Exception) -> Exception:
    setattr(main_error, "_smoke_cleanup_error", _serialize_probe_exception(cleanup_error))
    return main_error


def run_probe(
    name: str,
    func: Callable[[], dict[str, Any]],
    *,
    required: bool = True,
    context: Mapping[str, Any] | None = None,
) -> ProbeResult:
    started_at = utc_now()
    try:
        details = func()
        error = None
        status: ProbeStatus = "passed"
    except HonuaHttpError as exc:
        details = {}
        error = _serialize_probe_exception(exc)
        error["context"] = _probe_error_context(context, exc)
        status = "failed"
    except Exception as exc:  # pragma: no cover - exercised through callers
        details = {}
        error = _serialize_probe_exception(exc)
        error["context"] = _probe_error_context(context, exc)
        status = "failed"

    return ProbeResult(
        name=name,
        status=status,
        required=required,
        started_at=started_at,
        completed_at=utc_now(),
        details=details,
        error=error,
    )


def skipped_probe(
    name: str,
    reason: str,
    *,
    required: bool = False,
    context: Mapping[str, Any] | None = None,
) -> ProbeResult:
    started_at = utc_now()
    details = {"reason": reason}
    if context:
        details["context"] = dict(context)
    return ProbeResult(
        name=name,
        status="skipped",
        required=required,
        started_at=started_at,
        completed_at=utc_now(),
        details=details,
    )


def assert_probe_passed(result: ProbeResult) -> None:
    if result.status == "passed":
        return

    if result.error is None:
        raise AssertionError(f"{result.name} did not pass: {result.details}")

    error = result.error
    status_code = error.get("status_code")
    if status_code is None:
        raise AssertionError(f"{result.name} failed: {error['type']}: {error['message']}")

    raise AssertionError(
        f"{result.name} failed with HTTP {status_code}: {error['message']}"
    )


def run_smoke_suite(config: SmokeConfig) -> SmokeReport:
    report = SmokeReport(config=config)
    context = config.target_dict()

    with HonuaClient(config.base_url, api_key=config.api_key) as client:
        report.record(
            run_probe(
                "readiness",
                lambda: probe_readiness(client, config),
                context=context,
            )
        )
        report.record(
            run_probe(
                "list_services",
                lambda: probe_list_services(client, config),
                context=context,
            )
        )
        report.record(
            run_probe(
                "query_seeded_layer",
                lambda: probe_query_seeded_layer(client, config),
                context=context,
            )
        )

        if config.enable_write_smoke:
            report.record(
                run_probe(
                    "apply_edits_roundtrip",
                    lambda: probe_apply_edits_roundtrip(client, config),
                    context=context,
                )
            )
        else:
            report.record(
                skipped_probe(
                    "apply_edits_roundtrip",
                    "Write smoke disabled. Set HONUA_ENABLE_WRITE_SMOKE=true to enable applyEdits coverage.",
                    context=context,
                )
            )

    return report


def probe_readiness(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.readiness()
    return {
        "base_url": config.base_url,
        "response_keys": sorted(response.keys()),
        "status": response.get("status"),
    }


def probe_list_services(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.list_services()
    services = response.get("services")
    if not isinstance(services, list):
        raise AssertionError("list_services() did not return a 'services' array.")

    matches = []
    for service in services:
        if not isinstance(service, Mapping):
            continue
        if service.get("name") == config.service_id:
            matches.append(
                {
                    "name": service.get("name"),
                    "type": service.get("type"),
                }
            )

    if not matches:
        raise AssertionError(
            f"Service {config.service_id!r} was not listed by /rest/services."
        )

    return {
        "service_count": len(services),
        "matched_services": matches,
    }


def probe_query_seeded_layer(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.query_features(
        config.service_id,
        config.layer_id,
        out_fields=["*"],
        return_geometry=True,
        extra_params={"resultRecordCount": READ_QUERY_LIMIT},
    )
    features = _response_features(response)
    if not features:
        raise AssertionError(
            "The seeded staging layer returned no features. The smoke suite expects seeded data for field-surface verification."
        )

    attributes = _feature_attributes(features[0])
    observed_fields = {str(key).lower() for key in attributes}
    missing_fields = sorted(EXPECTED_QUERY_FIELDS - observed_fields)
    if missing_fields:
        raise AssertionError(
            f"Seeded layer response is missing expected fields: {', '.join(missing_fields)}"
        )

    return {
        "sampled_feature_count": len(features),
        "sample_objectid": _extract_objectid(attributes),
        "observed_fields": sorted(observed_fields),
        "spatial_reference": response.get("spatialReference"),
    }


def probe_apply_edits_roundtrip(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    uid = str(uuid4())
    description = build_smoke_description(config.uid_prefix, uid)
    details: dict[str, Any] = {
        "uid": uid,
        "description": description,
        "where": build_uid_where(uid),
    }
    known_objectids: set[int] = set()
    main_error: Exception | None = None
    cleanup_error: Exception | None = None

    try:
        add_feature = _make_smoke_feature(
            uid=uid,
            name="SDK smoke add",
            description=description,
            status="active",
            count=1,
            geometry=INITIAL_GEOMETRY,
        )
        add_response = client.apply_edits(
            config.service_id,
            config.layer_id,
            adds=[add_feature],
            rollback_on_failure=True,
        )
        details["add_response"] = summarize_edit_response(add_response)
        add_objectid = _extract_objectid(_first_success_result(add_response, "addResults"))
        if add_objectid is not None:
            known_objectids.add(add_objectid)

        added_feature = _query_single_feature(client, config, uid)
        added_attributes = _feature_attributes(added_feature)
        queried_objectid = _extract_objectid(added_attributes)
        if queried_objectid is None:
            raise AssertionError("Added smoke feature did not expose an objectid field.")
        known_objectids.add(queried_objectid)
        _assert_feature_fields(
            added_attributes,
            uid=uid,
            name="SDK smoke add",
            description=description,
            status="active",
            count=1,
        )

        update_feature = _make_smoke_feature(
            uid=uid,
            name="SDK smoke updated",
            description=description,
            status="inactive",
            count=2,
            geometry=UPDATED_GEOMETRY,
            objectid=queried_objectid,
        )
        update_response = client.apply_edits(
            config.service_id,
            config.layer_id,
            updates=[update_feature],
            rollback_on_failure=True,
        )
        details["update_response"] = summarize_edit_response(update_response)
        _first_success_result(update_response, "updateResults")

        updated_feature = _query_single_feature(client, config, uid)
        updated_attributes = _feature_attributes(updated_feature)
        _assert_feature_fields(
            updated_attributes,
            uid=uid,
            name="SDK smoke updated",
            description=description,
            status="inactive",
            count=2,
        )
    except Exception as exc:
        main_error = exc
    finally:
        try:
            details["cleanup"] = cleanup_smoke_records(
                client,
                config,
                uid=uid,
                known_objectids=known_objectids,
            )
        except Exception as exc:  # pragma: no cover - exercised by integration flow
            cleanup_error = exc

    if main_error is not None and cleanup_error is not None:
        raise _attach_cleanup_error(main_error, cleanup_error)
    if main_error is not None:
        raise main_error
    if cleanup_error is not None:
        raise cleanup_error

    return details


def cleanup_smoke_records(
    client: HonuaClient,
    config: SmokeConfig,
    *,
    uid: str,
    known_objectids: set[int] | None = None,
) -> dict[str, Any]:
    objectids = set(known_objectids or set())
    response = client.query_features(
        config.service_id,
        config.layer_id,
        where=build_uid_where(uid),
        out_fields=["objectid", "uid"],
        return_geometry=False,
        extra_params={"resultRecordCount": WRITE_QUERY_LIMIT},
    )
    features = _response_features(response)
    for feature in features:
        objectid = _extract_objectid(_feature_attributes(feature))
        if objectid is not None:
            objectids.add(objectid)

    if objectids:
        delete_response = client.apply_edits(
            config.service_id,
            config.layer_id,
            deletes=sorted(objectids),
            rollback_on_failure=True,
        )
        delete_summary = summarize_edit_response(delete_response)
    else:
        delete_summary = {
            "delete_total": 0,
            "delete_successes": 0,
        }

    verify_response = client.query_features(
        config.service_id,
        config.layer_id,
        where=build_uid_where(uid),
        out_fields=["objectid", "uid"],
        return_geometry=False,
        extra_params={"resultRecordCount": WRITE_QUERY_LIMIT},
    )
    remaining_features = _response_features(verify_response)
    if remaining_features:
        raise AssertionError(
            f"Cleanup left {len(remaining_features)} smoke feature(s) behind for uid {uid}."
        )

    return {
        "deleted_objectids": sorted(objectids),
        "delete_response": delete_summary,
        "remaining_feature_count": len(remaining_features),
    }


def summarize_edit_response(response: Mapping[str, Any]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for key, prefix in (
        ("addResults", "add"),
        ("updateResults", "update"),
        ("deleteResults", "delete"),
    ):
        results = response.get(key)
        if not isinstance(results, list):
            continue
        summary[f"{prefix}_total"] = len(results)
        summary[f"{prefix}_successes"] = sum(
            1 for item in results if isinstance(item, Mapping) and item.get("success") is True
        )
    return summary


def build_uid_where(uid: str) -> str:
    escaped_uid = uid.replace("'", "''")
    return f"uid = '{escaped_uid}'"


def build_smoke_description(uid_prefix: str, uid: str) -> str:
    return f"{uid_prefix}:{uid}"


def load_smoke_report(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def render_smoke_summary(report: SmokeReport | Mapping[str, Any]) -> str:
    payload = report.to_dict() if isinstance(report, SmokeReport) else dict(report)
    counts = payload.get("probe_counts", {})
    target = payload.get("target", {})
    probes = payload.get("probes", [])

    lines = [
        "## Python SDK staging smoke",
        f"- Overall status: `{payload.get('overall_status', 'unknown')}`",
        f"- Target: `{target.get('base_url', 'unknown')}` / `{target.get('service_id', 'unknown')}` layer `{target.get('layer_id', 'unknown')}`",
        f"- Probe counts: passed `{counts.get('passed', 0)}`, failed `{counts.get('failed', 0)}`, skipped `{counts.get('skipped', 0)}`",
    ]

    failed_probes = [probe for probe in probes if probe.get("status") == "failed"]
    if failed_probes:
        lines.append("")
        lines.append("### Failures")
        for probe in failed_probes:
            error = probe.get("error") or {}
            message = error.get("message", "unknown failure")
            status_code = error.get("status_code")
            if status_code is None:
                lines.append(f"- `{probe.get('name', 'unknown')}`: {message}")
            else:
                lines.append(f"- `{probe.get('name', 'unknown')}`: HTTP {status_code} {message}")

    return "\n".join(lines) + "\n"


def _query_single_feature(
    client: HonuaClient,
    config: SmokeConfig,
    uid: str,
) -> Mapping[str, Any]:
    response = client.query_features(
        config.service_id,
        config.layer_id,
        where=build_uid_where(uid),
        out_fields=["*"],
        return_geometry=True,
        extra_params={"resultRecordCount": 2},
    )
    features = _response_features(response)
    if len(features) != 1:
        raise AssertionError(f"Expected 1 smoke feature for uid {uid}, found {len(features)}.")
    return features[0]


def _response_features(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    features = response.get("features")
    if not isinstance(features, list):
        raise AssertionError("Feature query did not return a 'features' array.")

    normalized: list[Mapping[str, Any]] = []
    for feature in features:
        if not isinstance(feature, Mapping):
            raise AssertionError("Feature query returned a non-object feature entry.")
        normalized.append(feature)
    return normalized


def _feature_attributes(feature: Mapping[str, Any]) -> Mapping[str, Any]:
    attributes = feature.get("attributes")
    if not isinstance(attributes, Mapping):
        raise AssertionError("Feature query result did not include an 'attributes' object.")
    return attributes


def _make_smoke_feature(
    *,
    uid: str,
    name: str,
    description: str | None = None,
    status: str,
    count: int,
    geometry: Mapping[str, float],
    objectid: int | None = None,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "uid": uid,
        "name": name,
        "status": status,
        "count": count,
    }
    if description is not None:
        attributes["description"] = description
    if objectid is not None:
        attributes["objectid"] = objectid

    return {
        "attributes": attributes,
        "geometry": dict(geometry),
    }


def _assert_feature_fields(
    attributes: Mapping[str, Any],
    *,
    uid: str,
    name: str,
    description: str | None = None,
    status: str,
    count: int,
) -> None:
    if attributes.get("uid") != uid:
        raise AssertionError(f"Expected uid {uid!r}, got {attributes.get('uid')!r}.")
    if attributes.get("name") != name:
        raise AssertionError(f"Expected name {name!r}, got {attributes.get('name')!r}.")
    if description is not None and attributes.get("description") != description:
        raise AssertionError(
            f"Expected description {description!r}, got {attributes.get('description')!r}."
        )
    if attributes.get("status") != status:
        raise AssertionError(f"Expected status {status!r}, got {attributes.get('status')!r}.")
    if int(attributes.get("count")) != count:
        raise AssertionError(f"Expected count {count!r}, got {attributes.get('count')!r}.")


def _first_success_result(response: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    results = response.get(key)
    if not isinstance(results, list) or not results:
        raise AssertionError(f"apply_edits() response did not include any {key}.")

    for result in results:
        if isinstance(result, Mapping) and result.get("success") is True:
            return result

    raise AssertionError(f"apply_edits() returned {key}, but none succeeded: {results}")


def _extract_objectid(payload: Mapping[str, Any]) -> int | None:
    for key in ("objectid", "objectId", "OBJECTID"):
        value = payload.get(key)
        if value is None:
            continue
        return int(value)
    return None


def _read_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _read_bool_env(name: str, *, default: bool) -> bool:
    value = _read_env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}
