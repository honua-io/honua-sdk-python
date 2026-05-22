"""arcpy.env attribute mirroring."""

from __future__ import annotations

import honua_arcpy


def test_env_attributes_mirror_to_session() -> None:
    session = honua_arcpy.get_session()
    honua_arcpy.env.workspace = "honua://services/test"
    honua_arcpy.env.overwriteOutput = True
    honua_arcpy.env.outputCoordinateSystem = 4326
    honua_arcpy.env.parallelProcessingFactor = "75%"
    honua_arcpy.env.scratchWorkspace = "honua://services/scratch"

    assert session.workspace == "honua://services/test"
    assert session.overwrite_output is True
    assert session.output_coordinate_system == 4326
    assert session.parallel_processing_factor == "75%"
    assert session.scratch_workspace == "honua://services/scratch"


def test_env_unknown_attribute_falls_into_extra_options() -> None:
    honua_arcpy.env.someExperimentalFlag = "yes"
    assert honua_arcpy.get_session().extra_client_options["someExperimentalFlag"] == "yes"


def test_env_reads_default_to_none_when_unset() -> None:
    assert honua_arcpy.env.workspace is None
    assert honua_arcpy.env.overwriteOutput is False
