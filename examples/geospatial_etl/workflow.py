"""Shared geospatial ETL workflow used by the CLI and notebook example."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

try:
    import geopandas as gpd
    from shapely.geometry import Point
except ImportError as exc:  # pragma: no cover - import guard for local usage
    raise ImportError(
        "The geospatial ETL example requires geopandas and shapely. "
        "Install them with: pip install -e \"packages/honua-sdk[geopandas]\""
    ) from exc

from honua_sdk.errors import HonuaHttpError
from honua_sdk.geopandas import features_to_geodataframe, geodataframe_to_features

DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_SERVICE_ID = "test_service"
DEFAULT_LAYER_ID = 0
DEFAULT_SOURCE_CRS = "EPSG:3857"
DEFAULT_TARGET_CRS = "EPSG:4326"
DEFAULT_UID_PREFIX = "demo-etl-"
REQUIRED_SOURCE_COLUMNS = ("uid", "name", "status", "count", "x_3857", "y_3857")
REQUIRED_FIELDS = ("uid", "name", "status")
LOAD_FIELDS = ("uid", "name", "status", "count")


class HonuaClientProtocol(Protocol):
    """Small protocol for the workflow's client dependency."""

    def query_features(
        self,
        service_id: str,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: str | list[str] = "*",
        return_geometry: bool = True,
    ) -> dict[str, Any]: ...

    def apply_edits(
        self,
        service_id: str,
        layer_id: int,
        *,
        adds: list[dict[str, Any]] | None = None,
        updates: list[dict[str, Any]] | None = None,
        rollback_on_failure: bool = True,
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class ValidationIssue:
    source_row: int
    uid: str | None
    reasons: list[str]
    record: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_row": self.source_row,
            "uid": self.uid,
            "reasons": list(self.reasons),
            "record": dict(self.record),
        }


@dataclass(slots=True)
class ValidationResult:
    source_row_count: int
    valid_gdf: "gpd.GeoDataFrame"
    rejected_rows: list[ValidationIssue]

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_rows)

    @property
    def valid_count(self) -> int:
        return len(self.valid_gdf)


@dataclass(slots=True)
class TargetSnapshot:
    response: dict[str, Any]
    geodataframe: "gpd.GeoDataFrame"
    feature_count: int
    target_crs: str


@dataclass(slots=True)
class UpsertPlan:
    adds_gdf: "gpd.GeoDataFrame"
    updates_gdf: "gpd.GeoDataFrame"
    add_features: list[dict[str, Any]]
    update_features: list[dict[str, Any]]

    @property
    def add_count(self) -> int:
        return len(self.add_features)

    @property
    def update_count(self) -> int:
        return len(self.update_features)


@dataclass(slots=True)
class WorkflowRun:
    source_gdf: "gpd.GeoDataFrame"
    transformed_gdf: "gpd.GeoDataFrame"
    validation: ValidationResult
    pre_load: TargetSnapshot | None
    post_load: TargetSnapshot | None
    plan: UpsertPlan | None
    apply_edits_result: dict[str, Any]
    summary: dict[str, Any]
    summary_path: Path
    preview_path: Path | None
    exit_code: int
    error_stage: str | None = None
    error_summary: dict[str, Any] | None = None


def build_demo_where(uid_prefix: str = DEFAULT_UID_PREFIX) -> str:
    escaped_prefix = uid_prefix.replace("'", "''")
    return f"uid LIKE '{escaped_prefix}%'"


def load_source_dataframe(input_path: str | Path) -> pd.DataFrame:
    frame = _read_source_dataframe(input_path)
    return _prepare_source_dataframe(frame, context="Input CSV")


def dataframe_to_source_geodataframe(
    frame: pd.DataFrame,
    *,
    source_crs: str = DEFAULT_SOURCE_CRS,
) -> "gpd.GeoDataFrame":
    _require_columns(frame, REQUIRED_SOURCE_COLUMNS, context="Source dataframe")

    geometry = []
    for x_value, y_value in zip(frame["x_3857"], frame["y_3857"], strict=True):
        if _is_missing(x_value) or _is_missing(y_value):
            geometry.append(None)
            continue
        geometry.append(Point(float(x_value), float(y_value)))

    return gpd.GeoDataFrame(frame.copy(), geometry=geometry, crs=source_crs)


def normalize_source_geodataframe(
    source_gdf: "gpd.GeoDataFrame",
    *,
    target_crs: str,
) -> "gpd.GeoDataFrame":
    normalized = source_gdf.copy()

    normalized["uid"] = normalized["uid"].map(_normalize_text)
    normalized["name"] = normalized["name"].map(_normalize_text)
    normalized["status"] = normalized["status"].map(_normalize_status)
    normalized["count"] = pd.to_numeric(normalized["count"], errors="coerce").astype("Int64")

    current_crs = normalized.crs.to_string() if normalized.crs is not None else None
    if current_crs != target_crs:
        normalized = normalized.to_crs(target_crs)

    return normalized


def validate_source_geodataframe(source_gdf: "gpd.GeoDataFrame") -> ValidationResult:
    _require_columns(source_gdf, REQUIRED_FIELDS, context="Transformed GeoDataFrame")

    valid_indices: list[int] = []
    rejected_rows: list[ValidationIssue] = []
    seen_uids: set[str] = set()

    for index, row in source_gdf.iterrows():
        reasons: list[str] = []
        uid = _normalize_text(row.get("uid"))

        if uid is None:
            reasons.append("missing_required_field:uid")
        elif uid in seen_uids:
            reasons.append("duplicate_uid")
        else:
            seen_uids.add(uid)

        for field_name in ("name", "status"):
            if _normalize_text(row.get(field_name)) is None:
                reasons.append(f"missing_required_field:{field_name}")

        if _is_missing(row.get("x_3857")) or _is_missing(row.get("y_3857")):
            reasons.append("missing_coordinates")
        else:
            geometry = row.geometry
            if geometry is None or geometry.is_empty:
                reasons.append("null_geometry")
            elif hasattr(geometry, "is_valid") and not geometry.is_valid:
                reasons.append("invalid_geometry")

        if reasons:
            rejected_rows.append(
                ValidationIssue(
                    source_row=int(row.get("_source_row", index)),
                    uid=uid,
                    reasons=reasons,
                    record=_serialize_source_record(row, source_gdf.geometry.name),
                )
            )
            continue

        valid_indices.append(index)

    if valid_indices:
        valid_frame = source_gdf.loc[valid_indices].copy()
    else:
        valid_frame = source_gdf.iloc[0:0].copy()

    return ValidationResult(
        source_row_count=len(source_gdf),
        valid_gdf=gpd.GeoDataFrame(
            valid_frame,
            geometry=source_gdf.geometry.name,
            crs=source_gdf.crs,
        ),
        rejected_rows=rejected_rows,
    )


def query_target_snapshot(
    client: HonuaClientProtocol,
    *,
    service_id: str,
    layer_id: int,
    where: str,
    fallback_target_crs: str = DEFAULT_TARGET_CRS,
) -> TargetSnapshot:
    response = client.query_features(
        service_id=service_id,
        layer_id=layer_id,
        where=where,
        out_fields=["*"],
        return_geometry=True,
    )
    target_gdf = features_to_geodataframe(response)

    return TargetSnapshot(
        response=response,
        geodataframe=target_gdf,
        feature_count=len(target_gdf),
        target_crs=resolve_target_crs(target_gdf, fallback=fallback_target_crs),
    )


def resolve_target_crs(
    target_gdf: "gpd.GeoDataFrame",
    *,
    fallback: str = DEFAULT_TARGET_CRS,
) -> str:
    if target_gdf.crs is None:
        return fallback
    return target_gdf.crs.to_string()


def build_upsert_plan(
    valid_gdf: "gpd.GeoDataFrame",
    existing_gdf: "gpd.GeoDataFrame",
    *,
    target_crs: str,
) -> UpsertPlan:
    _require_columns(valid_gdf, ("uid",), context="Validated GeoDataFrame")

    objectid_field = _find_objectid_field(existing_gdf.columns)
    working = valid_gdf.copy()

    current_crs = working.crs.to_string() if working.crs is not None else None
    if current_crs != target_crs:
        working = working.to_crs(target_crs)

    uid_to_objectid: dict[str, Any] = {}
    if len(existing_gdf) > 0:
        _require_columns(existing_gdf, ("uid", objectid_field), context="Existing target GeoDataFrame")
        uid_to_objectid = dict(zip(existing_gdf["uid"], existing_gdf[objectid_field], strict=True))

    working[objectid_field] = working["uid"].map(uid_to_objectid)

    adds_frame = working.loc[working[objectid_field].isna()].copy()
    updates_frame = working.loc[working[objectid_field].notna()].copy()

    if len(updates_frame) > 0:
        updates_frame[objectid_field] = updates_frame[objectid_field].map(lambda value: int(value))

    adds_gdf = _select_load_columns(adds_frame, geometry_name=working.geometry.name)
    updates_gdf = _select_load_columns(
        updates_frame,
        geometry_name=working.geometry.name,
        objectid_field=objectid_field,
    )

    return UpsertPlan(
        adds_gdf=adds_gdf,
        updates_gdf=updates_gdf,
        add_features=features_from_geodataframe(adds_gdf),
        update_features=features_from_geodataframe(updates_gdf),
    )


def features_from_geodataframe(gdf: "gpd.GeoDataFrame") -> list[dict[str, Any]]:
    if len(gdf) == 0:
        return []
    return [_json_safe(feature) for feature in geodataframe_to_features(gdf)]


def count_successful_edits(apply_edits_response: dict[str, Any]) -> int:
    success_count = 0
    for key in ("addResults", "updateResults", "deleteResults"):
        for result in apply_edits_response.get(key, []):
            if result.get("success") is True:
                success_count += 1
    return success_count


def run_workflow(
    client: HonuaClientProtocol,
    *,
    base_url: str = DEFAULT_BASE_URL,
    service_id: str = DEFAULT_SERVICE_ID,
    layer_id: int = DEFAULT_LAYER_ID,
    input_path: str | Path,
    output_dir: str | Path,
    uid_prefix: str = DEFAULT_UID_PREFIX,
) -> WorkflowRun:
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    summary_path = output_path / "load-summary.json"
    preview_path = output_path / "post-load-preview.png"

    input_path = _resolve_path(input_path)
    where = build_demo_where(uid_prefix)
    summary = _build_summary_scaffold(
        base_url=base_url,
        service_id=service_id,
        layer_id=layer_id,
        input_path=input_path,
        summary_path=summary_path,
        where=where,
    )

    source_gdf = _empty_geodataframe()
    transformed_gdf = _empty_geodataframe()
    validation = _empty_validation_result()
    try:
        source_frame = _read_source_dataframe(input_path)
        summary["source"]["source_row_count"] = len(source_frame)
        source_frame = _prepare_source_dataframe(source_frame, context="Input CSV")
        source_gdf = dataframe_to_source_geodataframe(source_frame)
    except (OSError, ValueError, pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        validation = _empty_validation_result(
            source_row_count=int(summary["source"]["source_row_count"] or 0)
        )
        summary["workflow_error"] = _input_error_summary(exc, stage="source_setup")
        summary["apply_edits"] = _skipped_apply_edits_summary(reason="source_setup_error")
        summary["completed_at"] = _utc_now()
        write_summary_artifact(summary, summary_path)
        return WorkflowRun(
            source_gdf=source_gdf,
            transformed_gdf=transformed_gdf,
            validation=validation,
            pre_load=None,
            post_load=None,
            plan=None,
            apply_edits_result=summary["apply_edits"],
            summary=summary,
            summary_path=summary_path,
            preview_path=None,
            exit_code=1,
            error_stage="source_setup",
            error_summary=summary["workflow_error"],
        )

    try:
        pre_load = query_target_snapshot(
            client,
            service_id=service_id,
            layer_id=layer_id,
            where=where,
        )
    except HonuaHttpError as exc:
        transformed_gdf = normalize_source_geodataframe(source_gdf, target_crs=DEFAULT_TARGET_CRS)
        validation = validate_source_geodataframe(transformed_gdf)
        summary["source"] = _build_source_summary(validation, input_path)
        summary["workflow_error"] = _http_error_summary(exc, stage="pre_load_query")
        summary["apply_edits"] = _skipped_apply_edits_summary(reason="pre_load_query_http_error")
        summary["completed_at"] = _utc_now()
        write_summary_artifact(summary, summary_path)
        return WorkflowRun(
            source_gdf=source_gdf,
            transformed_gdf=transformed_gdf,
            validation=validation,
            pre_load=None,
            post_load=None,
            plan=None,
            apply_edits_result=summary["apply_edits"],
            summary=summary,
            summary_path=summary_path,
            preview_path=None,
            exit_code=1,
            error_stage="pre_load_query",
            error_summary=summary["workflow_error"],
        )

    transformed_gdf = normalize_source_geodataframe(source_gdf, target_crs=pre_load.target_crs)
    validation = validate_source_geodataframe(transformed_gdf)
    summary["target"]["target_crs"] = pre_load.target_crs
    summary["source"] = _build_source_summary(validation, input_path)
    summary["pre_load"] = {
        "matching_feature_count": pre_load.feature_count,
        "target_crs": pre_load.target_crs,
    }

    if validation.valid_count == 0:
        apply_summary = _skipped_apply_edits_summary(reason="all_rows_rejected")
        summary["apply_edits"] = apply_summary
        summary["completed_at"] = _utc_now()
        write_summary_artifact(summary, summary_path)
        return WorkflowRun(
            source_gdf=source_gdf,
            transformed_gdf=transformed_gdf,
            validation=validation,
            pre_load=pre_load,
            post_load=None,
            plan=None,
            apply_edits_result=apply_summary,
            summary=summary,
            summary_path=summary_path,
            preview_path=None,
            exit_code=1,
        )

    plan = build_upsert_plan(
        validation.valid_gdf,
        pre_load.geodataframe,
        target_crs=pre_load.target_crs,
    )
    summary["plan"] = {
        "adds": plan.add_count,
        "updates": plan.update_count,
    }

    try:
        apply_response = client.apply_edits(
            service_id=service_id,
            layer_id=layer_id,
            adds=plan.add_features or None,
            updates=plan.update_features or None,
            rollback_on_failure=True,
        )
    except HonuaHttpError as exc:
        apply_summary = _http_error_summary(exc, stage="apply_edits")
        summary["apply_edits"] = apply_summary
        summary["completed_at"] = _utc_now()
        write_summary_artifact(summary, summary_path)
        return WorkflowRun(
            source_gdf=source_gdf,
            transformed_gdf=transformed_gdf,
            validation=validation,
            pre_load=pre_load,
            post_load=None,
            plan=plan,
            apply_edits_result=apply_summary,
            summary=summary,
            summary_path=summary_path,
            preview_path=None,
            exit_code=1,
            error_stage="apply_edits",
            error_summary=apply_summary,
        )

    apply_summary = {
        "status": "success",
        "successful_edits": count_successful_edits(apply_response),
        "response": _json_safe(apply_response),
    }
    summary["apply_edits"] = apply_summary

    summary["post_load"] = {
        "matching_feature_count": None,
        "target_crs": pre_load.target_crs,
    }
    try:
        post_load = query_target_snapshot(
            client,
            service_id=service_id,
            layer_id=layer_id,
            where=where,
            fallback_target_crs=pre_load.target_crs,
        )
    except HonuaHttpError as exc:
        summary["workflow_error"] = _http_error_summary(exc, stage="post_load_query")
        summary["completed_at"] = _utc_now()
        write_summary_artifact(summary, summary_path)
        return WorkflowRun(
            source_gdf=source_gdf,
            transformed_gdf=transformed_gdf,
            validation=validation,
            pre_load=pre_load,
            post_load=None,
            plan=plan,
            apply_edits_result=apply_summary,
            summary=summary,
            summary_path=summary_path,
            preview_path=None,
            exit_code=1,
            error_stage="post_load_query",
            error_summary=summary["workflow_error"],
        )
    write_post_load_preview(
        post_load.geodataframe,
        preview_path,
        title=f"{service_id} layer {layer_id} demo records ({post_load.feature_count} rows)",
    )

    summary["post_load"] = {
        "matching_feature_count": post_load.feature_count,
        "target_crs": post_load.target_crs,
    }
    summary["artifacts"]["post_load_preview"] = str(preview_path)
    summary["completed_at"] = _utc_now()

    write_summary_artifact(summary, summary_path)

    exit_code = 0 if apply_summary["successful_edits"] > 0 else 1
    return WorkflowRun(
        source_gdf=source_gdf,
        transformed_gdf=transformed_gdf,
        validation=validation,
        pre_load=pre_load,
        post_load=post_load,
        plan=plan,
        apply_edits_result=apply_summary,
        summary=summary,
        summary_path=summary_path,
        preview_path=preview_path,
        exit_code=exit_code,
    )


def write_summary_artifact(summary: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.write_text(json.dumps(_json_safe(summary), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_post_load_preview(
    gdf: "gpd.GeoDataFrame",
    output_path: str | Path,
    *,
    title: str,
) -> Path:
    import matplotlib.pyplot as plt

    path = Path(output_path).expanduser().resolve()
    figure, axis = plt.subplots(figsize=(8, 6))
    preview_gdf, x_label, y_label = _prepare_preview_geodataframe(gdf)

    if len(preview_gdf) == 0:
        axis.text(0.5, 0.5, "No demo features returned", ha="center", va="center")
        axis.set_axis_off()
    else:
        plot_kwargs: dict[str, Any] = {"ax": axis, "markersize": 90}
        if "status" in preview_gdf.columns and preview_gdf["status"].notna().any():
            plot_kwargs.update({"column": "status", "categorical": True, "legend": True})
        else:
            plot_kwargs.update({"color": "#0f766e"})

        preview_gdf.plot(**plot_kwargs)

        label_column = "name" if "name" in preview_gdf.columns else "uid"
        if label_column in preview_gdf.columns:
            for _, row in preview_gdf.iterrows():
                if row.geometry is None:
                    continue
                axis.annotate(
                    str(row[label_column]),
                    xy=(row.geometry.x, row.geometry.y),
                    xytext=(4, 4),
                    textcoords="offset points",
                    fontsize=8,
                )

    axis.set_title(title)
    axis.set_xlabel(x_label)
    axis.set_ylabel(y_label)
    figure.tight_layout()
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)
    return path


def _find_objectid_field(columns: Any) -> str:
    for candidate in ("objectid", "OBJECTID"):
        if candidate in columns:
            return candidate
    return "objectid"


def _select_load_columns(
    frame: "gpd.GeoDataFrame",
    *,
    geometry_name: str,
    objectid_field: str | None = None,
) -> "gpd.GeoDataFrame":
    selected_columns = list(LOAD_FIELDS)
    if objectid_field is not None and objectid_field in frame.columns:
        selected_columns.insert(0, objectid_field)

    columns = [column for column in selected_columns if column in frame.columns]
    columns.append(geometry_name)
    return gpd.GeoDataFrame(frame.loc[:, columns].copy(), geometry=geometry_name, crs=frame.crs)


def _serialize_source_record(row: pd.Series, geometry_name: str) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for key, value in row.items():
        if key == geometry_name:
            continue
        record[key] = _json_safe(value)
    return record


def _resolve_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _read_source_dataframe(input_path: str | Path) -> pd.DataFrame:
    return pd.read_csv(_resolve_path(input_path))


def _prepare_source_dataframe(frame: pd.DataFrame, *, context: str) -> pd.DataFrame:
    prepared = frame.copy()
    _require_columns(prepared, REQUIRED_SOURCE_COLUMNS, context=context)
    prepared["_source_row"] = range(2, len(prepared) + 2)
    return prepared


def _empty_geodataframe(*, crs: str | None = None) -> "gpd.GeoDataFrame":
    return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=crs)


def _empty_validation_result(*, source_row_count: int = 0) -> ValidationResult:
    return ValidationResult(
        source_row_count=source_row_count,
        valid_gdf=_empty_geodataframe(),
        rejected_rows=[],
    )


def _prepare_preview_geodataframe(
    gdf: "gpd.GeoDataFrame",
) -> tuple["gpd.GeoDataFrame", str, str]:
    if gdf.crs is None:
        return gdf, "X", "Y"

    current_crs = gdf.crs.to_string()
    if current_crs != DEFAULT_TARGET_CRS:
        gdf = gdf.to_crs(DEFAULT_TARGET_CRS)

    return gdf, "Longitude", "Latitude"


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def _normalize_status(value: Any) -> str | None:
    text = _normalize_text(value)
    return text.lower() if text is not None else None


def _require_columns(frame: Any, expected_columns: tuple[str, ...], *, context: str) -> None:
    missing = [column for column in expected_columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{context} is missing expected columns: {', '.join(missing)}")


def _is_missing(value: Any) -> bool:
    return bool(pd.isna(value))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if _is_missing(value):
        return None
    return value


def _build_source_summary(validation: ValidationResult, input_path: str | Path) -> dict[str, Any]:
    return {
        "input_path": str(_resolve_path(input_path)),
        "source_row_count": validation.source_row_count,
        "valid_row_count": validation.valid_count,
        "rejected_row_count": validation.rejected_count,
        "rejected_rows": [issue.to_dict() for issue in validation.rejected_rows],
    }


def _build_summary_scaffold(
    *,
    base_url: str,
    service_id: str,
    layer_id: int,
    input_path: str | Path,
    summary_path: str | Path,
    where: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "started_at": _utc_now(),
        "target": {
            "base_url": base_url,
            "service_id": service_id,
            "layer_id": layer_id,
            "where": where,
            "target_crs": None,
        },
        "source": {
            "input_path": str(_resolve_path(input_path)),
            "source_row_count": None,
            "valid_row_count": None,
            "rejected_row_count": None,
            "rejected_rows": [],
        },
        "pre_load": {
            "matching_feature_count": None,
            "target_crs": None,
        },
        "plan": {
            "adds": 0,
            "updates": 0,
        },
        "artifacts": {
            "load_summary": str(_resolve_path(summary_path)),
            "post_load_preview": None,
        },
        "apply_edits": _skipped_apply_edits_summary(reason="not_started"),
    }


def _input_error_summary(exc: Exception, *, stage: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": "input_error",
        "status_code": None,
        "message": str(exc),
        "body": None,
        "error_type": type(exc).__name__,
        "successful_edits": 0,
        "response": None,
    }


def _http_error_summary(exc: HonuaHttpError, *, stage: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": "http_error",
        "status_code": exc.status_code,
        "message": exc.message,
        "body": _json_safe(exc.body),
        "successful_edits": 0,
        "response": None,
    }


def _skipped_apply_edits_summary(*, reason: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "reason": reason,
        "successful_edits": 0,
        "response": None,
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
