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


def test_env_unknown_attribute_falls_into_extra_env_options() -> None:
    """Unknown ``arcpy.env.*`` writes land in ``extra_env_options`` -- *not*
    ``extra_client_options`` -- so common legacy writes like
    ``arcpy.env.extent`` do not leak into the ``HonuaClient(**kwargs)``
    constructor (which has a closed keyword signature and would crash with
    ``TypeError`` before the first backend call)."""

    honua_arcpy.env.someExperimentalFlag = "yes"
    session = honua_arcpy.get_session()
    assert session.extra_env_options["someExperimentalFlag"] == "yes"
    assert honua_arcpy.env.someExperimentalFlag == "yes"
    # The legacy bag stays empty -- unknown env attrs must not be forwarded
    # to the SDK constructor.
    assert "someExperimentalFlag" not in session.extra_client_options


def test_env_unknown_attribute_does_not_break_client_construction() -> None:
    """``arcpy.env.extent`` and similar legacy writes must not crash
    ``_build_client``. Regression for the prior behaviour where the env
    proxy stashed unknown attrs in ``extra_client_options`` and the SDK
    constructor rejected them as unexpected keyword arguments."""

    honua_arcpy.configure(base_url="https://example.com", api_key="k")
    # Common legacy writes that arcpy scripts emit before the first backend
    # call. None of them should leak into the SDK constructor (which has a
    # closed keyword signature -- ``extent`` would raise ``TypeError``).
    honua_arcpy.env.extent = "0 0 100 100"
    honua_arcpy.env.MTolerance = 0.001
    honua_arcpy.env.geographicTransformations = "WGS_1984_(ITRF00)_To_NAD_1983"

    # Build the real HonuaClient. With the spillover separated, the SDK
    # constructor only sees ``base_url`` / ``api_key`` and the call succeeds.
    client = honua_arcpy.get_session().client()
    assert client is not None
    # The unknown env attrs are still recoverable from the session for
    # debug / migration tooling.
    session = honua_arcpy.get_session()
    assert session.extra_env_options["extent"] == "0 0 100 100"
    assert session.extra_env_options["MTolerance"] == 0.001
    # ``extra_client_options`` stays empty because no client kwargs were
    # supplied to ``configure(...)``.
    assert session.extra_client_options == {}


def test_env_reads_default_to_none_when_unset() -> None:
    assert honua_arcpy.env.workspace is None
    assert honua_arcpy.env.overwriteOutput is False
