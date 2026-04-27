"""Protocol client examples for Honua Server."""

from __future__ import annotations

from honua_sdk import HonuaClient


def main() -> None:
    with HonuaClient("https://your-honua-server.com") as client:
        services = client.list_services()
        print(f"Services: {len(services.get('services', []))}")

        feature_set = client.feature_server("parcels").query(0, where="1=1", out_fields=["OBJECTID"])
        print(f"FeatureServer features: {len(feature_set.get('features', []))}")

        map_bytes = client.ogc_maps().collection_map("parcels", bbox=[-180, -90, 180, 90])
        print(f"OGC map bytes: {len(map_bytes)}")

        stac_items = client.stac().items("imagery")
        print(f"STAC items: {len(stac_items.get('features', []))}")

        wfs_xml = client.wfs().get_feature(type_names="parcels")
        print(f"WFS response characters: {len(wfs_xml)}")

        odata = client.odata().features(layer_id=0)
        print(f"OData rows: {len(odata.get('value', []))}")


if __name__ == "__main__":
    main()
