"""Codemod coverage for the raster / Spatial Analyst tools added by PR #175.

PR #175 shipped ``honua_gp.sa`` -- an ``arcpy.sa``-style surface wrapping 16
working honua-server raster/surface processes -- plus three honest STUBS
(Kriging, Histogram, SpectralIndex) that raise ``HonuaGpUnsupportedError`` at
runtime. These tests assert the ``honua_sdk.migration`` codemod:

* recognizes each of the 16 working arcpy raster tools and maps it to its
  honua-server raster process id + names its ``honua_gp.sa`` migration target
  (classified ``manual-review`` -- raster ids 404 on direct OGC execution and
  are not bare-OGC job-executable, so the codemod never claims a
  server-runnable migration);
* leaves the three stubs UNSUPPORTED so the codemod never emits a translation
  for ``honua_gp.sa.Kriging`` / ``Histogram`` / ``SpectralIndex``, which would
  be a guaranteed runtime failure -- exactly the overclaim #175 guarded against.

The migration targets are cross-checked against the ACTUAL ``honua_gp.sa`` /
``honua_gp.management`` signatures (imported, not guessed) so a rename on either
side fails loudly.
"""

from __future__ import annotations

import pytest

from honua_sdk.migration import (
    build_parity_evidence_for_source,
    scan_arcpy_source,
    translate_arcpy_source,
)

# The 16 working tools -> (arcpy family, honua-server raster process id,
# honua_gp.sa migration target named in the manual-review note).
WORKING_TOOLS = {
    "Slope": ("spatial-analyst", "surface.slope", "honua_gp.sa.Slope"),
    "Aspect": ("spatial-analyst", "surface.aspect", "honua_gp.sa.Aspect"),
    "Hillshade": ("spatial-analyst", "surface.hillshade", "honua_gp.sa.Hillshade"),
    "Contour": ("spatial-analyst", "surface.contour", "honua_gp.sa.Contour"),
    "Viewshed": ("spatial-analyst", "surface.viewshed", "honua_gp.sa.Viewshed"),
    "Roughness": ("spatial-analyst", "surface.roughness", "honua_gp.sa.Roughness"),
    "TPI": ("spatial-analyst", "surface.rugosity-tpi", "honua_gp.sa.TPI"),
    "TRI": ("spatial-analyst", "surface.rugosity-tri", "honua_gp.sa.TRI"),
    "Reclassify": ("spatial-analyst", "raster.reclassify", "honua_gp.sa.Reclassify"),
    "RasterCalculator": ("spatial-analyst", "raster.map-algebra", "honua_gp.sa.RasterCalculator"),
    "Idw": ("spatial-analyst", "raster.interpolate-idw", "honua_gp.sa.Idw"),
    "ZonalStatisticsAsTable": (
        "spatial-analyst",
        "raster.zonal-statistics",
        "honua_gp.sa.ZonalStatisticsAsTable",
    ),
    "ProjectRaster": ("management", "raster.reproject", "honua_gp.management.ProjectRaster"),
    "Resample": ("management", "raster.resample", "honua_gp.management.Resample"),
    "Clip": ("management", "raster.clip", "honua_gp.management.Clip"),
    "Mosaic": ("management", "raster.mosaic", "honua_gp.management.Mosaic"),
}

# A script exercising each working tool once, using real Esri namespacing
# (arcpy.sa.* for Spatial Analyst, arcpy.management.* for the raster Data
# Management tools).
RASTER_SCRIPT = """
import arcpy

arcpy.sa.Slope("dem", "DEGREE", 1.0)
arcpy.sa.Aspect("dem")
arcpy.sa.Hillshade("dem", 315, 45)
arcpy.sa.Contour("dem", "contours", 10)
arcpy.sa.Viewshed("dem", "obs", "vshed")
arcpy.sa.Roughness("dem", "rough")
arcpy.sa.TPI("dem", "tpi")
arcpy.sa.TRI("dem", "tri")
arcpy.sa.Reclassify("landcover", "VALUE", "1 5;2 10", "reclass")
arcpy.sa.RasterCalculator("(A-B)/(A+B)", "ndvi")
arcpy.sa.Idw("stations", "ELEV", "idw_out")
arcpy.sa.ZonalStatisticsAsTable("zones", "ZONE_ID", "value", "zstats", "MEAN")
arcpy.management.ProjectRaster("dem", "dem_wgs84", 4326)
arcpy.management.Resample("dem", "dem_10m", 10)
arcpy.management.Clip("dem", "0 0 10 10", "dem_clip")
arcpy.management.Mosaic(["a.tif", "b.tif"], "target.tif")
"""


def test_all_sixteen_working_raster_tools_are_recognized() -> None:
    report = scan_arcpy_source(RASTER_SCRIPT, filename="raster.py")
    by_tool = {call.tool: call for call in report.calls}

    assert set(WORKING_TOOLS).issubset(by_tool), (
        "codemod did not recognize every working raster tool"
    )
    for tool, (family, process_id, _target) in WORKING_TOOLS.items():
        call = by_tool[tool]
        assert call.family == family, f"{tool} classified under {call.family!r}"
        # Recognized + mapped, but honestly NOT server-runnable via bare OGC.
        assert call.supported is True, f"{tool} should be a recognized mapping"
        assert call.status == "manual-review", f"{tool} status={call.status!r}"
        assert call.translatable is False, f"{tool} must not claim executability"
        assert call.process_id == process_id, f"{tool} -> {call.process_id!r}"
        # Raster ids are never in the reconciled job-executable catalog.
        assert call.job_process_id is None, f"{tool} leaked a job id"


def test_manual_review_notes_name_the_honua_gp_migration_target() -> None:
    evidence = build_parity_evidence_for_source(RASTER_SCRIPT, filename="raster.py")
    by_tool = {(c["family"], c["tool"]): c for c in evidence["calls"]}

    for tool, (family, _process_id, target) in WORKING_TOOLS.items():
        entry = by_tool[(family, tool)]
        assert entry["status"] == "manual-review"
        # Manual-review entries carry a reason + notes but no runnable payload.
        assert "payload" not in entry
        joined = entry["reason"] + " " + " ".join(entry.get("notes", ()))
        assert target in joined, f"{tool} note did not name {target}"


def test_raster_tools_translate_to_bare_ogc_ids_without_job_ids() -> None:
    plan = translate_arcpy_source(RASTER_SCRIPT, filename="raster.py")
    process_ids = {t.call.tool: t.process_id for t in plan.translations}
    job_ids = {t.call.tool: t.job_process_id for t in plan.translations}

    for tool, (_family, process_id, _target) in WORKING_TOOLS.items():
        assert process_ids[tool] == process_id
        # The raster run path is never claimed as server job-executable.
        assert job_ids[tool] is None


def test_bare_project_raster_call_classifies_as_management() -> None:
    # arcpy.ProjectRaster (un-suffixed, un-namespaced) still resolves to the
    # management raster.reproject spec.
    report = scan_arcpy_source('import arcpy\narcpy.ProjectRaster("dem", "out", 4326)\n')
    (call,) = report.calls
    assert call.family == "management"
    assert call.tool == "ProjectRaster"
    assert call.process_id == "raster.reproject"
    assert call.status == "manual-review"


@pytest.mark.parametrize("stub", ["Kriging", "Histogram", "SpectralIndex"])
def test_honest_stubs_are_unsupported_not_translated(stub: str) -> None:
    # honua_gp.sa.Kriging/Histogram/SpectralIndex raise HonuaGpUnsupportedError
    # at runtime; the codemod must surface them as UNSUPPORTED (no mapping) so
    # it never emits a translation that pretends they work.
    source = f'import arcpy\narcpy.sa.{stub}("in", "out")\n'
    report = scan_arcpy_source(source)
    (call,) = report.calls

    assert call.family == "spatial-analyst"
    assert call.supported is False
    assert call.status == "unsupported"
    assert call.translatable is False
    assert call.process_id is None
    assert call.job_process_id is None

    # No translation is emitted for the stub -- nothing resembling a
    # honua_gp.sa.<stub> call reaches the plan.
    plan = translate_arcpy_source(source)
    assert plan.translations == ()
    assert ("spatial-analyst", stub) in {
        (c.family, c.tool) for c in plan.unsupported_calls
    }


def test_kriging_evidence_reports_gap_at_translation_time() -> None:
    evidence = build_parity_evidence_for_source(
        'import arcpy\narcpy.sa.Kriging("stations", "PredZ")\n'
    )
    (entry,) = evidence["calls"]
    assert entry["status"] == "unsupported"
    assert entry["processId"] is None
    assert "No Honua process mapping" in entry["reason"]
    assert evidence["summary"]["unsupportedCalls"] == 1
    assert evidence["summary"]["translatableCalls"] == 0


def test_migration_targets_match_actual_honua_gp_signatures() -> None:
    # Cross-check the honua_gp.sa / honua_gp.management migration targets named
    # by the codemod against the ACTUAL PR #175 surface (imported, not guessed).
    sa = pytest.importorskip("honua_gp.sa")
    management = pytest.importorskip("honua_gp.management")
    from honua_gp._compat import COMPAT

    for tool, (_family, _process_id, target) in WORKING_TOOLS.items():
        module = sa if target.startswith("honua_gp.sa.") else management
        attr = target.rsplit(".", 1)[1]
        assert hasattr(module, attr), f"{target} is not a real honua_gp function"
        assert callable(getattr(module, attr))
        # The manifest agrees these 16 are working (supported/partial), so the
        # codemod is right to map (not stub) them.
        assert COMPAT[f"sa.{tool}"].status in {"supported", "partial"}

    # ...and the three stubs really are stubs in the ground-truth manifest.
    for stub in ("Kriging", "Histogram", "SpectralIndex"):
        assert COMPAT[f"sa.{stub}"].status == "stub"
        assert COMPAT[f"sa.{stub}"].backend == "not_implemented"
