"""discover_tables must decode the shapes the admin tables endpoint actually returns."""

from honua_admin._models import ColumnInfo, TableDiscoveryResponse


def test_column_without_max_length_decodes():
    column = ColumnInfo.from_dict(
        {
            "name": "objectid",
            "dataType": "bigint",
            "isNullable": False,
            "isPrimaryKey": True,
        }
    )
    assert column.max_length is None
    assert column.name == "objectid"
    assert column.is_primary_key is True


def test_table_discovery_omits_optional_geometry_and_column_length():
    # Integer, text, geometry, jsonb and timestamp columns omit maxLength.
    # A non-spatial table also omits geometryColumn, geometryType, srid and estimatedRows.
    payload = {
        "tables": [
            {
                "schema": "public",
                "table": "notes",
                "columns": [
                    {"name": "objectid", "dataType": "bigint", "isNullable": False, "isPrimaryKey": True},
                    {"name": "body", "dataType": "text", "isNullable": True, "isPrimaryKey": False},
                    {"name": "created", "dataType": "timestamp", "isNullable": True, "isPrimaryKey": False},
                    {"name": "props", "dataType": "jsonb", "isNullable": True, "isPrimaryKey": False},
                ],
            },
            {
                "schema": "public",
                "table": "parcels",
                "geometryColumn": "shape",
                "geometryType": "Polygon",
                "srid": 3857,
                "estimatedRows": 12,
                "columns": [
                    {
                        "name": "shape",
                        "dataType": "geometry",
                        "isNullable": True,
                        "isPrimaryKey": False,
                    },
                    {
                        "name": "name",
                        "dataType": "varchar",
                        "isNullable": True,
                        "isPrimaryKey": False,
                        "maxLength": 64,
                    },
                ],
            },
        ]
    }
    discovered = TableDiscoveryResponse.from_dict(payload)
    notes = discovered.tables[0]
    assert notes.geometry_column is None
    assert notes.geometry_type is None
    assert notes.srid is None
    assert notes.estimated_rows is None
    assert [column.max_length for column in notes.columns] == [None, None, None, None]
    parcels = discovered.tables[1]
    assert parcels.geometry_column == "shape"
    assert parcels.srid == 3857
    assert parcels.columns[1].max_length == 64
