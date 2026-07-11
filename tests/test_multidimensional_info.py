"""Tests for parsing the ImageServer ``multidimensionalInfo`` response.

The fixture below mirrors the exact wire shape confirmed against
honua-server's ``ImageServerMultidimensionalInfoBuilder`` /
``ImageServerModels.cs`` (``ImageServerMultidimensionalInfo`` /
``ImageServerMultidimensionalVariable`` / ``ImageServerMultidimensionalDimension``):

* A ``StdTime`` axis: regular, ``dimensionSize`` small enough (<= 10,000) that
  the server enumerates ``values`` (epoch milliseconds), unit ``"ISO8601"``.
* A ``StdZ`` axis: regular, with a non-ISO ``unit`` (e.g. ``"Meters"``).
* A generic/custom axis (an ensemble-member-style dimension the builder does
  not special-case as time/vertical): extent-only, no synthesized ``values``,
  no ``unit`` -- the server omits those keys entirely (``JsonIgnoreCondition
  .WhenWritingNull``) rather than emitting JSON ``null``.

This is metadata-only: dimension/variable discovery. It is a separate concern
from pixel sampling (``getSamples``), which -- since honua-server#1869 closed
via honua-server#1939 -- can now return a real sampled value for a pinned
slice when the layer has a servable Zarr store; see
``honua_sdk.raster.parse_multidimensional_info``'s docstring for the current,
accurate scope split.
"""

from __future__ import annotations

from honua_sdk.raster import (
    MultidimensionalDimension,
    MultidimensionalVariable,
    parse_multidimensional_info,
)

# A representative multidimensionalInfo response envelope, as returned by
# GET .../ImageServer/multidimensionalInfo (wrapped under "multidimensionalInfo").
_ENVELOPE = {
    "multidimensionalInfo": {
        "variables": [
            {
                "name": "water_temp",
                "description": "Sea water potential temperature",
                "unit": "degC",
                "dimensions": [
                    {
                        "name": "StdTime",
                        "unit": "ISO8601",
                        "extent": [1577836800000.0, 1580515200000.0],
                        "values": [1577836800000.0, 1579046400000.0, 1580515200000.0],
                        "hasRegularIntervals": True,
                        "dimensionSize": 3,
                    },
                    {
                        "name": "StdZ",
                        "unit": "Meters",
                        "extent": [0.0, 500.0],
                        "values": [0.0, 250.0, 500.0],
                        "hasRegularIntervals": True,
                        "dimensionSize": 3,
                    },
                    {
                        "name": "ensemble_member",
                        "hasRegularIntervals": False,
                        "dimensionSize": 12,
                    },
                ],
            },
            {
                "name": "salinity",
                "unit": "psu",
                "dimensions": [
                    {
                        "name": "StdTime",
                        "unit": "ISO8601",
                        "extent": [1577836800000.0, 1580515200000.0],
                        "values": None,
                        "hasRegularIntervals": False,
                        "dimensionSize": 25000,
                    },
                ],
            },
        ],
    },
}


def test_parse_multidimensional_info_wrapped_envelope() -> None:
    variables = parse_multidimensional_info(_ENVELOPE)
    assert len(variables) == 2
    assert all(isinstance(v, MultidimensionalVariable) for v in variables)


def test_parse_multidimensional_info_unwrapped_document() -> None:
    # Also accepts the inner document directly (no "multidimensionalInfo" wrapper),
    # so it composes regardless of how the raw wire method returns the body.
    unwrapped = parse_multidimensional_info(_ENVELOPE["multidimensionalInfo"])
    assert len(unwrapped) == 2


def test_variable_fields() -> None:
    water_temp, salinity = parse_multidimensional_info(_ENVELOPE)

    assert water_temp.name == "water_temp"
    assert water_temp.description == "Sea water potential temperature"
    assert water_temp.unit == "degC"
    assert len(water_temp.dimensions) == 3

    assert salinity.name == "salinity"
    assert salinity.description is None
    assert salinity.unit == "psu"


def test_regular_time_dimension_carries_enumerated_values() -> None:
    water_temp = parse_multidimensional_info(_ENVELOPE)[0]
    std_time = water_temp.dimensions[0]

    assert isinstance(std_time, MultidimensionalDimension)
    assert std_time.name == "StdTime"
    assert std_time.unit == "ISO8601"
    assert std_time.extent == (1577836800000.0, 1580515200000.0)
    assert std_time.values == (1577836800000.0, 1579046400000.0, 1580515200000.0)
    assert std_time.has_regular_intervals is True
    assert std_time.dimension_size == 3


def test_regular_vertical_dimension_units() -> None:
    water_temp = parse_multidimensional_info(_ENVELOPE)[0]
    std_z = water_temp.dimensions[1]

    assert std_z.name == "StdZ"
    assert std_z.unit == "Meters"
    assert std_z.extent == (0.0, 500.0)
    assert std_z.values == (0.0, 250.0, 500.0)
    assert std_z.dimension_size == 3


def test_generic_dimension_has_no_extent_or_values_when_omitted() -> None:
    # The generic "ensemble_member" axis in the fixture omits unit/extent/values
    # entirely (as the server does for non-time/vertical axes with no synthesized
    # extent) -- these all parse to None, matching MultidimensionalCoverageDimension
    # (name, Size only) with no CF-derived extent to report.
    water_temp = parse_multidimensional_info(_ENVELOPE)[0]
    ensemble = water_temp.dimensions[2]

    assert ensemble.name == "ensemble_member"
    assert ensemble.unit is None
    assert ensemble.extent is None
    assert ensemble.values is None
    assert ensemble.has_regular_intervals is False
    assert ensemble.dimension_size == 12


def test_irregular_or_oversized_dimension_has_extent_but_no_values() -> None:
    # dimensionSize 25_000 exceeds the server's 10_000 enumeration cap
    # (ImageServerMultidimensionalInfoBuilder.EnumerateRegularValues), so the
    # server surfaces extent-only with a null "values" -- confirm that parses
    # to None rather than an (incorrect) empty tuple.
    salinity = parse_multidimensional_info(_ENVELOPE)[1]
    std_time = salinity.dimensions[0]

    assert std_time.extent == (1577836800000.0, 1580515200000.0)
    assert std_time.values is None
    assert std_time.has_regular_intervals is False
    assert std_time.dimension_size == 25000


def test_parse_multidimensional_info_empty_document() -> None:
    assert parse_multidimensional_info({"multidimensionalInfo": {"variables": []}}) == ()
    assert parse_multidimensional_info({"variables": []}) == ()


def test_parse_multidimensional_info_missing_variables_key() -> None:
    # A malformed/unexpected document (no "variables" at all) degrades to an
    # empty tuple rather than raising, matching the tolerant-parsing style used
    # elsewhere in this SDK (e.g. GeoprocessingJob.from_status_info).
    assert parse_multidimensional_info({}) == ()
