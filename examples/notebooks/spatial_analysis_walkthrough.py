# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Spatial analysis walkthrough (Honua SDK + GeoPandas)
#
# This notebook is the analyst-facing companion to the `spatial_query_cookbook`
# and `geospatial_etl` examples. It walks through a small air-quality workflow:
#
# 1. **Connect / query** sensor features from a Honua FeatureServer layer.
# 2. **Convert** the Esri JSON response to a GeoPandas `GeoDataFrame` via the SDK.
# 3. **Run spatial operations**: buffer, spatial join, and dissolve.
# 4. **Summarise / visualise** the results per district.
#
# Following the repo convention, the logic lives in a shared, importable module
# (`examples.spatial_analysis.analysis`) so the script mirror, this notebook, and
# the tests all reuse the same code. This `.py` file is the diff-friendly source
# of truth (jupytext `py:percent` format) paired with the committed `.ipynb`.
#
# **Live-server policy:** every cell below runs against the bundled demo fixture
# (`DEMO_SENSOR_RESPONSE`) and needs *no* server. One clearly-marked cell shows
# how to swap in a live `HonuaClient` using the shared `HONUA_*` environment
# contract (see `examples/README.md`); it is guarded so it is a no-op unless you
# opt in.

# %%
from __future__ import annotations

from pathlib import Path
import sys

# Make `examples...` importable whether the notebook is opened from the repo
# root or from examples/notebooks/.
cwd = Path.cwd().resolve()
if (cwd / "examples" / "spatial_analysis" / "analysis.py").exists():
    REPO_ROOT = cwd
elif (cwd / "spatial_analysis" / "analysis.py").exists():
    REPO_ROOT = cwd.parents[0]
elif (cwd.parents[1] / "examples" / "spatial_analysis" / "analysis.py").exists():
    REPO_ROOT = cwd.parents[1]
else:
    raise RuntimeError("Open this notebook from the repo root or examples/notebooks/.")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.spatial_analysis.analysis import (
    DEFAULT_BUFFER_METERS,
    DEMO_SENSOR_RESPONSE,
    EnvContract,
    buffer_sensors,
    dissolve_by_district,
    join_points_to_buffers,
    query_sensor_features,
    response_to_geodataframe,
    summarize_by_district,
)

# %% [markdown]
# ## 1. Query features
#
# The demo uses a bundled Esri JSON fixture shaped exactly like a
# `HonuaClient.query_features(...)` response, so the notebook is runnable
# offline. Six air-quality sensors around San Francisco, in Web Mercator.

# %%
response = DEMO_SENSOR_RESPONSE
print(f"Returned {len(response['features'])} features")
print("spatialReference:", response["spatialReference"])

# %% [markdown]
# ### (Optional) Query a live Honua layer
#
# **This cell needs a live endpoint.** It is disabled by default. Set
# `USE_LIVE_SERVER = True` and export the `HONUA_*` variables documented in
# `examples/README.md` (`HONUA_BASE_URL`, `HONUA_SERVICE_ID`, `HONUA_LAYER_ID`,
# optional `HONUA_API_KEY`) to fetch real features instead of the fixture. The
# response shape is identical, so every later cell works unchanged.

# %%
USE_LIVE_SERVER = False  # flip to True against a real deployment

if USE_LIVE_SERVER:
    from honua_sdk import HonuaClient

    env = EnvContract.from_env()
    print(f"Connecting to {env.base_url} (service={env.service_id}, layer={env.layer_id})")
    with HonuaClient(env.base_url, api_key=env.api_key) as client:
        response = query_sensor_features(
            client,
            service_id=env.service_id,
            layer_id=env.layer_id,
        )
    print(f"Live query returned {len(response['features'])} features")
else:
    print("Live server disabled; using the bundled demo fixture.")

# %% [markdown]
# ## 2. Convert to a GeoDataFrame
#
# `response_to_geodataframe` calls the SDK's `features_to_geodataframe` and
# reprojects to a metric CRS (Web Mercator) so buffer distances are in metres.

# %%
sensors = response_to_geodataframe(response)
print("CRS:", sensors.crs)
sensors[["objectid", "name", "district", "pm25", "geometry"]]

# %% [markdown]
# ## 3a. Buffer
#
# Buffer each sensor by ~3 km (projected metres) to model its catchment area.

# %%
buffers = buffer_sensors(sensors, distance_meters=DEFAULT_BUFFER_METERS)
print(f"Buffer radius: {DEFAULT_BUFFER_METERS:.0f} projected metres")
print("Geometry type:", buffers.geometry.iloc[0].geom_type)
buffers[["objectid", "name", "geometry"]].head()

# %% [markdown]
# ## 3b. Spatial join
#
# Count how many sensors fall within each sensor's buffer (neighbour density).
# A value of 1 means an isolated sensor; higher values flag clustered ones.

# %%
joined = join_points_to_buffers(sensors, buffers)
joined[["objectid", "name", "district", "neighbors_in_buffer"]]

# %% [markdown]
# ## 3c. Dissolve
#
# Dissolve the sensor points into one geometry per district and aggregate the
# mean PM2.5 reading per district.

# %%
dissolved = dissolve_by_district(sensors)
dissolved

# %% [markdown]
# ## 4. Summarise and visualise
#
# A per-district summary table sorted by mean PM2.5 (dirtiest first).

# %%
summary = summarize_by_district(sensors)
summary

# %% [markdown]
# ### Map (needs matplotlib)
#
# Plotting requires `matplotlib` (`pip install "honua-sdk[geopandas]" matplotlib`).
# The cell degrades gracefully if it is not installed, so the notebook still runs
# end-to-end without it.

# %%
try:
    import matplotlib.pyplot as plt

    display_sensors = sensors.to_crs("EPSG:4326")
    display_buffers = buffers.to_crs("EPSG:4326")

    ax = display_buffers.plot(
        figsize=(8, 6), alpha=0.25, edgecolor="#0f766e", color="#5eead4"
    )
    display_sensors.plot(ax=ax, column="district", legend=True, markersize=60)
    for _, row in display_sensors.iterrows():
        ax.annotate(
            row["name"],
            xy=(row.geometry.x, row.geometry.y),
            xytext=(4, 4),
            textcoords="offset points",
            fontsize=8,
        )
    ax.set_title("San Francisco air-quality sensors and 3 km catchments")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    plt.tight_layout()
    plt.show()
except ImportError:
    print("matplotlib not installed; skipping the map. Summary table:")
    print(summary.to_string(index=False))
