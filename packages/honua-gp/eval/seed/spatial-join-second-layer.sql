-- honua-gp ephemeral-server-smoke: second-layer fixture for analytics.spatial-join.
--
-- The canonical client-compat seed (honua-server tests/seed/client-compat-v1.sql)
-- registers exactly one layer (layer_id 0 in service `test_service`). honua-server's
-- analytics.spatial-join process rejects a self-join at catalog validation
-- ("joinLayerId must differ from the target layerId"), so the SpatialJoin eval
-- scripts need a SECOND, distinct layer to point their join_features at.
--
-- This idempotent snippet registers layer_id 1 in `test_service` backed by the
-- shared `features` table (layer_id-partitioned, exactly like layer 0) and adds a
-- few Point features that coincide with layer-0 points so both the INTERSECT and
-- WITHIN_A_DISTANCE ("100 Meters") joins return matches. It is applied against the
-- seeded postgres AFTER the canonical seed by the ephemeral-server-smoke job.
--
-- issue: honua-io/honua-sdk-python#157

INSERT INTO honua.layers (
    layer_id, layer_name, description, table_name,
    geometry_type, srid, extent, default_visibility
)
VALUES (
    1, 'Join Layer', 'Second layer so analytics.spatial-join has a distinct join target',
    'features', 'Point', 4326,
    ST_MakeEnvelope(-122.5, 37.7, -122.35, 37.84, 4326), true
)
ON CONFLICT (layer_id) DO UPDATE SET
    layer_name = EXCLUDED.layer_name,
    description = EXCLUDED.description,
    table_name = EXCLUDED.table_name,
    geometry_type = EXCLUDED.geometry_type,
    srid = EXCLUDED.srid,
    extent = EXCLUDED.extent,
    default_visibility = EXCLUDED.default_visibility;

UPDATE honua.layers
SET metadata = jsonb_build_object('accessPolicy', jsonb_build_object('allowAnonymous', true))
WHERE layer_id = 1;

INSERT INTO honua.layer_fields (
    layer_id, field_name, field_type, field_order,
    max_length, nullable, default_value, description
)
VALUES
    (1, 'objectid', 'Integer', 0, NULL, false, NULL, 'Object ID'),
    (1, 'zone', 'String', 1, 64, true, NULL, 'Zone label')
ON CONFLICT (layer_id, field_name) DO NOTHING;

INSERT INTO honua.service_layers (service_name, layer_id, layer_order)
VALUES ('test_service', 1, 1)
ON CONFLICT (service_name, layer_id) DO NOTHING;

-- Points coincident with layer-0 seed points (alpha/gamma/eta) so INTERSECT and
-- WITHIN_A_DISTANCE joins both yield matches. Guarded so re-applying the snippet
-- does not duplicate the join features.
INSERT INTO features (layer_id, geometry, attributes)
SELECT
    1,
    ST_SetSRID(ST_GeomFromText(wkt), 4326),
    jsonb_build_object('zone', zone)
FROM (
    VALUES
        ('POINT(-122.4900 37.7100)', 'zone-a'),
        ('POINT(-122.4600 37.7300)', 'zone-b'),
        ('POINT(-122.4000 37.7700)', 'zone-c')
) AS seed(wkt, zone)
WHERE NOT EXISTS (SELECT 1 FROM features WHERE layer_id = 1);
