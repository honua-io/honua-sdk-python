"""Focused tests for the geospatial ETL example workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

gpd = pytest.importorskip("geopandas")

from examples.geospatial_etl import workflow

EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "geospatial_etl"
DEMO_CSV = EXAMPLE_DIR / "data" / "demo_sites.csv"


def test_normalize_source_geodataframe_reprojects_to_target_crs() -> None:
    source_frame = workflow.load_source_dataframe(DEMO_CSV)
    source_gdf = workflow.dataframe_to_source_geodataframe(source_frame)

    normalized = workflow.normalize_source_geodataframe(source_gdf, target_crs="EPSG:4326")

    assert normalized.crs is not None
    assert normalized.crs.to_epsg() == 4326

    first_point = normalized.geometry.iloc[0]
    assert first_point.x == pytest.approx(-122.4098, abs=1e-4)
    assert first_point.y == pytest.approx(37.8087, abs=1e-4)
    assert normalized.loc[0, "status"] == "active"
    assert normalized.loc[2, "status"] == "needs review"


def test_validate_source_geodataframe_rejects_expected_bad_rows() -> None:
    source_frame = workflow.load_source_dataframe(DEMO_CSV)
    source_gdf = workflow.dataframe_to_source_geodataframe(source_frame)
    normalized = workflow.normalize_source_geodataframe(source_gdf, target_crs="EPSG:4326")

    validation = workflow.validate_source_geodataframe(normalized)

    assert validation.source_row_count == 9
    assert validation.valid_count == 6
    assert validation.rejected_count == 3

    rejected_by_row = {
        issue.source_row: set(issue.reasons)
        for issue in validation.rejected_rows
    }
    assert rejected_by_row[8] == {"duplicate_uid"}
    assert rejected_by_row[9] == {"missing_coordinates"}
    assert rejected_by_row[10] == {"missing_required_field:name"}


def test_build_upsert_plan_preserves_add_and_update_payloads() -> None:
    source_frame = workflow.load_source_dataframe(DEMO_CSV)
    source_gdf = workflow.dataframe_to_source_geodataframe(source_frame)
    normalized = workflow.normalize_source_geodataframe(source_gdf, target_crs="EPSG:4326")
    validation = workflow.validate_source_geodataframe(normalized)
    valid_subset = validation.valid_gdf.iloc[:2].copy()

    existing_response = {
        "spatialReference": {"wkid": 4326},
        "features": [
            {
                "attributes": {
                    "objectid": 41,
                    "uid": "demo-etl-001",
                    "name": "Pier 39 Sensor",
                    "status": "active",
                    "count": 12,
                },
                "geometry": {"x": -122.4098, "y": 37.8087},
            }
        ],
    }
    existing_gdf = workflow.features_to_geodataframe(existing_response)

    plan = workflow.build_upsert_plan(valid_subset, existing_gdf, target_crs="EPSG:4326")

    assert plan.add_count == 1
    assert plan.update_count == 1

    add_feature = plan.add_features[0]
    assert add_feature["attributes"]["uid"] == "demo-etl-002"
    assert "objectid" not in add_feature["attributes"]

    update_feature = plan.update_features[0]
    assert update_feature["attributes"]["uid"] == "demo-etl-001"
    assert update_feature["attributes"]["objectid"] == 41
    assert update_feature["geometry"]["x"] == pytest.approx(-122.4098, abs=1e-4)
    assert update_feature["geometry"]["y"] == pytest.approx(37.8087, abs=1e-4)


def test_run_workflow_queries_then_loads_then_requeries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    preview_writes: list[Path] = []

    def fake_preview_writer(gdf: gpd.GeoDataFrame, output_path: str | Path, *, title: str) -> Path:
        path = Path(output_path)
        path.write_bytes(b"fake-png")
        preview_writes.append(path)
        assert len(gdf) == 6
        assert title.startswith("test_service layer 0 demo records")
        return path

    monkeypatch.setattr(workflow, "write_post_load_preview", fake_preview_writer)

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []
            self.loaded_features: list[dict[str, object]] | None = None

        def query_features(
            self,
            service_id: str,
            layer_id: int,
            *,
            where: str = "1=1",
            out_fields: str | list[str] = "*",
            return_geometry: bool = True,
        ) -> dict[str, object]:
            self.calls.append(("query_features", where))
            assert service_id == "test_service"
            assert layer_id == 0
            assert out_fields == ["*"]
            assert return_geometry is True

            if self.loaded_features is None:
                return {
                    "spatialReference": {"wkid": 4326},
                    "features": [],
                }

            features = []
            for index, feature in enumerate(self.loaded_features, start=1001):
                attributes = dict(feature["attributes"])
                attributes["objectid"] = index
                features.append(
                    {
                        "attributes": attributes,
                        "geometry": feature["geometry"],
                    }
                )

            return {
                "spatialReference": {"wkid": 4326},
                "features": features,
            }

        def apply_edits(
            self,
            service_id: str,
            layer_id: int,
            *,
            adds: list[dict[str, object]] | None = None,
            updates: list[dict[str, object]] | None = None,
            rollback_on_failure: bool = True,
        ) -> dict[str, object]:
            self.calls.append(("apply_edits", f"{len(adds or [])}/{len(updates or [])}"))
            assert service_id == "test_service"
            assert layer_id == 0
            assert rollback_on_failure is True
            assert updates is None
            assert adds is not None

            self.loaded_features = adds
            return {
                "addResults": [
                    {"success": True, "objectId": 1001 + index}
                    for index in range(len(adds))
                ],
                "updateResults": [],
            }

    client = FakeClient()
    result = workflow.run_workflow(
        client,
        input_path=DEMO_CSV,
        output_dir=tmp_path,
    )

    assert result.exit_code == 0
    assert result.plan is not None
    assert result.plan.add_count == 6
    assert result.plan.update_count == 0
    assert result.pre_load.feature_count == 0
    assert result.post_load is not None
    assert result.post_load.feature_count == 6
    assert result.apply_edits_result["successful_edits"] == 6
    assert result.summary_path.exists()
    assert preview_writes == [tmp_path / "post-load-preview.png"]
    assert client.calls == [
        ("query_features", "uid LIKE 'demo-etl-%'"),
        ("apply_edits", "6/0"),
        ("query_features", "uid LIKE 'demo-etl-%'"),
    ]
