"""Focused tests for the spatial-analysis GeoPandas walkthrough example.

These exercise the shared, pure-Python helpers (no live server) and assert the
paired notebook stays import-clean with cleared outputs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

gpd = pytest.importorskip("geopandas")

from examples.spatial_analysis import analysis

NOTEBOOK_DIR = Path(__file__).resolve().parents[1] / "examples" / "notebooks"
NOTEBOOK_PATH = NOTEBOOK_DIR / "spatial_analysis_walkthrough.ipynb"
SCRIPT_MIRROR_PATH = NOTEBOOK_DIR / "spatial_analysis_walkthrough.py"


def test_response_to_geodataframe_uses_working_crs() -> None:
    gdf = analysis.response_to_geodataframe(analysis.DEMO_SENSOR_RESPONSE)

    assert len(gdf) == 6
    assert gdf.crs is not None
    assert gdf.crs.to_epsg() == 3857
    assert set(["objectid", "name", "district", "pm25"]).issubset(gdf.columns)


def test_buffer_sensors_requires_projected_crs() -> None:
    gdf = analysis.response_to_geodataframe(analysis.DEMO_SENSOR_RESPONSE)
    gdf = gdf.set_crs(None, allow_override=True)

    with pytest.raises(ValueError, match="projected CRS"):
        analysis.buffer_sensors(gdf)


def test_buffer_sensors_produces_polygons() -> None:
    gdf = analysis.response_to_geodataframe(analysis.DEMO_SENSOR_RESPONSE)
    buffered = analysis.buffer_sensors(gdf, distance_meters=3000.0)

    assert len(buffered) == len(gdf)
    assert all(geom.geom_type == "Polygon" for geom in buffered.geometry)
    # Buffer must grow the footprint relative to the zero-area points.
    assert buffered.geometry.area.min() > 0


def test_join_points_to_buffers_counts_neighbors() -> None:
    gdf = analysis.response_to_geodataframe(analysis.DEMO_SENSOR_RESPONSE)
    buffers = analysis.buffer_sensors(gdf, distance_meters=analysis.DEFAULT_BUFFER_METERS)
    joined = analysis.join_points_to_buffers(gdf, buffers)

    assert "neighbors_in_buffer" in joined.columns
    by_name = dict(zip(joined["name"], joined["neighbors_in_buffer"], strict=True))
    # Pier 39 and Ferry Building are close enough to share buffers.
    assert by_name["Pier 39"] == 2
    assert by_name["Ferry Building"] == 2
    # Every sensor counts at least itself.
    assert joined["neighbors_in_buffer"].min() >= 1


def test_dissolve_by_district_collapses_to_one_row_per_district() -> None:
    gdf = analysis.response_to_geodataframe(analysis.DEMO_SENSOR_RESPONSE)
    dissolved = analysis.dissolve_by_district(gdf)

    assert sorted(dissolved["district"]) == ["central", "north", "south", "west"]
    assert dissolved["district"].is_unique
    assert "pm25" in dissolved.columns


def test_summarize_by_district_orders_by_mean_pm25() -> None:
    gdf = analysis.response_to_geodataframe(analysis.DEMO_SENSOR_RESPONSE)
    summary = analysis.summarize_by_district(gdf)

    assert list(summary.columns) == ["district", "sensor_count", "mean_pm25", "max_pm25"]
    # Sorted dirtiest-first.
    assert summary["mean_pm25"].is_monotonic_decreasing
    assert summary.iloc[0]["district"] == "south"
    assert int(summary["sensor_count"].sum()) == 6


def test_run_demo_analysis_returns_all_artifacts() -> None:
    artifacts = analysis.run_demo_analysis()

    assert set(artifacts) == {"sensors", "buffers", "joined", "dissolved", "summary"}
    for value in artifacts.values():
        assert hasattr(value, "shape")


def test_env_contract_from_env_applies_defaults() -> None:
    contract = analysis.EnvContract.from_env({})
    assert contract.base_url == analysis.DEFAULT_BASE_URL
    assert contract.service_id == analysis.DEFAULT_SERVICE_ID
    assert contract.layer_id == analysis.DEFAULT_LAYER_ID
    assert contract.api_key is None

    overridden = analysis.EnvContract.from_env(
        {
            "HONUA_BASE_URL": "https://demo.honua.io",
            "HONUA_SERVICE_ID": "sensors",
            "HONUA_LAYER_ID": "3",
            "HONUA_API_KEY": "secret",
        }
    )
    assert overridden.base_url == "https://demo.honua.io"
    assert overridden.service_id == "sensors"
    assert overridden.layer_id == 3
    assert overridden.api_key == "secret"


def test_notebook_is_valid_with_cleared_outputs() -> None:
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))

    assert notebook["nbformat"] == 4
    code_cells = [c for c in notebook["cells"] if c["cell_type"] == "code"]
    assert code_cells, "expected at least one code cell"
    for cell in code_cells:
        assert cell.get("outputs") == []
        assert cell.get("execution_count") is None


def test_script_mirror_compiles() -> None:
    source = SCRIPT_MIRROR_PATH.read_text(encoding="utf-8")
    compile(source, str(SCRIPT_MIRROR_PATH), "exec")
    # The percent-format mirror imports from the shared module.
    assert "from examples.spatial_analysis.analysis import" in source
