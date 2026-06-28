# Changelog

## [0.1.8](https://github.com/honua-io/honua-sdk-python/compare/python-sdk-v0.1.7...python-sdk-v0.1.8) (2026-06-28)


### Bug Fixes

* **grpc,retry:** refresh gRPC auth per call; release pooled conn during backoff ([#144](https://github.com/honua-io/honua-sdk-python/issues/144)) ([ed265f4](https://github.com/honua-io/honua-sdk-python/commit/ed265f470fc3cde0287cad9b4f8e82bb32225daa))

## [0.1.7](https://github.com/honua-io/honua-sdk-python/compare/python-sdk-v0.1.6...python-sdk-v0.1.7) (2026-06-28)


### Bug Fixes

* **query:** honour max_pages=None as unbounded and re-wind GeoJSON spatial-filter rings ([#145](https://github.com/honua-io/honua-sdk-python/issues/145)) ([cb1d97b](https://github.com/honua-io/honua-sdk-python/commit/cb1d97be9734a878871cae67dc18e4f2ae14e1c5))
* **sdk:** harden core client transport, async auth, and de-duplicate geocoding ([#141](https://github.com/honua-io/honua-sdk-python/issues/141)) ([fc85d18](https://github.com/honua-io/honua-sdk-python/commit/fc85d18ca5c0356542ce6cbf84447505a69d203d)), closes [#125](https://github.com/honua-io/honua-sdk-python/issues/125) [#126](https://github.com/honua-io/honua-sdk-python/issues/126) [#129](https://github.com/honua-io/honua-sdk-python/issues/129)


### Performance

* **sdk:** fix conversion, pagination-memory, and transport-reuse lifecycle issues ([#142](https://github.com/honua-io/honua-sdk-python/issues/142)) ([52db7f9](https://github.com/honua-io/honua-sdk-python/commit/52db7f924c52994a6a32036df7c67219442b2806)), closes [#131](https://github.com/honua-io/honua-sdk-python/issues/131)

## [0.1.6](https://github.com/honua-io/honua-sdk-python/compare/python-sdk-v0.1.5...python-sdk-v0.1.6) (2026-06-27)


### Features

* **honua-sdk:** geometry/schema/cursor parity for GP authoring ([#119](https://github.com/honua-io/honua-sdk-python/issues/119)) ([4a0d490](https://github.com/honua-io/honua-sdk-python/commit/4a0d490e28e55fbed9c8c1fbf8a8db2588fcc450))


### Bug Fixes

* correct GP interop CRS/ring-winding/job-id handling ([#137](https://github.com/honua-io/honua-sdk-python/issues/137)) ([#140](https://github.com/honua-io/honua-sdk-python/issues/140)) ([3c88dc5](https://github.com/honua-io/honua-sdk-python/commit/3c88dc5715fa3e10ebb4d0669ce31155b4f0d9d1))
* round-1 audit fixes — geocoding base path, limit=0 crash, gRPC M-only geometry, conformance probes, license text ([#138](https://github.com/honua-io/honua-sdk-python/issues/138)) ([e4644c8](https://github.com/honua-io/honua-sdk-python/commit/e4644c837cb66b54867278d284de7205f7de9bcf))

## [0.1.5](https://github.com/honua-io/honua-sdk-python/compare/python-sdk-v0.1.4...python-sdk-v0.1.5) (2026-06-27)


### Features

* **migration:** expand arcpy codemod coverage + .atbx ModelBuilder + GP-service translation ([#100](https://github.com/honua-io/honua-sdk-python/issues/100)) ([ed84a72](https://github.com/honua-io/honua-sdk-python/commit/ed84a72e35e4349289392dd072d3e1a8dd43c1cb))


### Bug Fixes

* **sdk:** close auth credential leak on scheme downgrade and preserve base_url path prefix ([#134](https://github.com/honua-io/honua-sdk-python/issues/134)) ([eb0d3a6](https://github.com/honua-io/honua-sdk-python/commit/eb0d3a6236aec7b569abb74c377d29aa60b2ec6d))
* **sdk:** emit spec-mandatory params for STAC/WMS/WMTS typed helpers ([#135](https://github.com/honua-io/honua-sdk-python/issues/135)) ([c9da466](https://github.com/honua-io/honua-sdk-python/commit/c9da4667ad0f0d563cecf5b9cb7dbe967246ac88)), closes [#127](https://github.com/honua-io/honua-sdk-python/issues/127)
* **sdk:** retry, geocoding, and parsing robustness fixes ([#109](https://github.com/honua-io/honua-sdk-python/issues/109)) ([5285190](https://github.com/honua-io/honua-sdk-python/commit/52851904dbdb291b2d1533dc438e6d369606ffb0))
* **sdk:** surface GeoServices error envelopes and correct query total_count ([#133](https://github.com/honua-io/honua-sdk-python/issues/133)) ([44ff5ee](https://github.com/honua-io/honua-sdk-python/commit/44ff5ee1b0969b0210ed5644f21fd2570f928ee9)), closes [#122](https://github.com/honua-io/honua-sdk-python/issues/122) [#128](https://github.com/honua-io/honua-sdk-python/issues/128)

## [0.1.4](https://github.com/honua-io/honua-sdk-python/compare/python-sdk-v0.1.3...python-sdk-v0.1.4) (2026-06-10)


### Features

* **sdk-python:** add 3D Tiles tileset fetch + offline scene packaging ([#93](https://github.com/honua-io/honua-sdk-python/issues/93)) ([44b64a6](https://github.com/honua-io/honua-sdk-python/commit/44b64a6e20ac608bcac13fb01828f28261a0020a)), closes [#1198](https://github.com/honua-io/honua-sdk-python/issues/1198)

## [0.1.3](https://github.com/honua-io/honua-sdk-python/compare/python-sdk-v0.1.2...python-sdk-v0.1.3) (2026-05-31)


### Features

* **migration:** expand arcpy tool coverage slice ([#82](https://github.com/honua-io/honua-sdk-python/issues/82)) ([#86](https://github.com/honua-io/honua-sdk-python/issues/86)) ([41d4270](https://github.com/honua-io/honua-sdk-python/commit/41d427088969350f731f89e296955cd83e5ea403))

## [0.1.2](https://github.com/honua-io/honua-sdk-python/compare/python-sdk-v0.1.1...python-sdk-v0.1.2) (2026-05-31)


### Features

* **cli:** add honua CLI (services/layers/style apply) for SDK parity with JS ([#76](https://github.com/honua-io/honua-sdk-python/issues/76)) ([1a04f03](https://github.com/honua-io/honua-sdk-python/commit/1a04f036dc3b36ffba18f2ba86c69c6fff479c5c))
* Demo: geospatial ETL pipeline and analyst notebook for Python SDK ([#14](https://github.com/honua-io/honua-sdk-python/issues/14)) ([ec132a2](https://github.com/honua-io/honua-sdk-python/commit/ec132a286cd136f869873f300c57c219eaf4ee22))
* Python SDK notebooks/examples and staging integration tests (#honua-sdk-python-3) ([e1fdd84](https://github.com/honua-io/honua-sdk-python/commit/e1fdd84cf5001c79780a412b20fb7a6eef8dd5d0))
* **scenes:** Python scene + elevation + offline-package clients (honua-server[#1198](https://github.com/honua-io/honua-sdk-python/issues/1198)) ([#71](https://github.com/honua-io/honua-sdk-python/issues/71)) ([6a518c1](https://github.com/honua-io/honua-sdk-python/commit/6a518c1f703623283d7c08349917b67f343054f4))
* **sdk:** reconcile ArcPy codemod hardening + GP/workflow clients onto trunk + reconciled server ([#75](https://github.com/honua-io/honua-sdk-python/issues/75)) ([934dada](https://github.com/honua-io/honua-sdk-python/commit/934dadad2b143dc8d66d3637c441b96cf3f1fc43))

## [0.1.1](https://github.com/honua-io/honua-sdk-python/compare/python-sdk-v0.1.0...python-sdk-v0.1.1) (2026-04-28)


### Features

* Demo: geospatial ETL pipeline and analyst notebook for Python SDK ([#14](https://github.com/honua-io/honua-sdk-python/issues/14)) ([ec132a2](https://github.com/honua-io/honua-sdk-python/commit/ec132a286cd136f869873f300c57c219eaf4ee22))
* Python SDK notebooks/examples and staging integration tests (#honua-sdk-python-3) ([e1fdd84](https://github.com/honua-io/honua-sdk-python/commit/e1fdd84cf5001c79780a412b20fb7a6eef8dd5d0))

## [0.1.0](https://github.com/honua-io/honua-sdk-python/compare/python-sdk-v0.0.2...python-sdk-v0.1.0) (2026-04-28)


### Features

* add unified feature query API across FeatureServer, OGC API Features, STAC, and OData ([#42](https://github.com/honua-io/honua-sdk-python/pull/42))
* add protocol iterators, public protocol typing helpers, OData query helpers, and WMS/WMTS response metadata wrappers ([#41](https://github.com/honua-io/honua-sdk-python/pull/41))
* add SDK/admin compatibility gate, protocol factory snapshots, and CI release gates ([#28](https://github.com/honua-io/honua-sdk-python/pull/28))
* add typed core endpoint helpers, refreshable auth providers, expanded protocol clients, and protocol smoke coverage ([#23](https://github.com/honua-io/honua-sdk-python/pull/23), [#24](https://github.com/honua-io/honua-sdk-python/pull/24), [#26](https://github.com/honua-io/honua-sdk-python/pull/26), [#27](https://github.com/honua-io/honua-sdk-python/pull/27), [#40](https://github.com/honua-io/honua-sdk-python/pull/40))


### Bug Fixes

* fix SDK review findings before the 0.1.0 packaging pass ([#29](https://github.com/honua-io/honua-sdk-python/pull/29))

## [0.0.2](https://github.com/honua-io/honua-sdk-python/compare/python-sdk-v0.0.1...python-sdk-v0.0.2) (2026-04-25)


### Features

* Demo: geospatial ETL pipeline and analyst notebook for Python SDK ([#14](https://github.com/honua-io/honua-sdk-python/issues/14)) ([ec132a2](https://github.com/honua-io/honua-sdk-python/commit/ec132a286cd136f869873f300c57c219eaf4ee22))
* Python SDK notebooks/examples and staging integration tests (#honua-sdk-python-3) ([e1fdd84](https://github.com/honua-io/honua-sdk-python/commit/e1fdd84cf5001c79780a412b20fb7a6eef8dd5d0))
