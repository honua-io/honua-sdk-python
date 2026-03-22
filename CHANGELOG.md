# Changelog

All notable changes to the Honua Python SDK will be documented in this file.

## [0.0.2](https://github.com/honua-io/honua-sdk-python/compare/python-sdk-vv0.0.1...python-sdk-vv0.0.2) (2026-03-22)


### Features

* add async REST clients and GeoPandas integration ([94d4832](https://github.com/honua-io/honua-sdk-python/commit/94d48323bc0189cc9fee88d307c7cc435458028b))
* add Python compatibility baseline ([#10](https://github.com/honua-io/honua-sdk-python/issues/10)) ([#13](https://github.com/honua-io/honua-sdk-python/issues/13)) ([5a4964d](https://github.com/honua-io/honua-sdk-python/commit/5a4964db120882acaad8541d2532da405452f9a3))
* enhanced Python SDK gRPC capabilities for mobile integration ([c13aef4](https://github.com/honua-io/honua-sdk-python/commit/c13aef4e1770ce9e93240d0e9e51b013cd34ff6f)), closes [#359](https://github.com/honua-io/honua-sdk-python/issues/359)
* SDK publishing, geocoding client, and developer docs ([#7](https://github.com/honua-io/honua-sdk-python/issues/7)) ([90c2f85](https://github.com/honua-io/honua-sdk-python/commit/90c2f85c4ef27291a60cc7868b44ecb6e102a5d9))


### Bug Fixes

* harden client redirects and proto mapping ([8544478](https://github.com/honua-io/honua-sdk-python/commit/8544478a621c4a871831a14674e8e0e489ca255f))


### Documentation

* complete Python SDK publishing baseline ([ae9e48c](https://github.com/honua-io/honua-sdk-python/commit/ae9e48caa05d7d65bb251d6aa83fc08cfddb3dd3))
* update README with async clients, GeoPandas, and retry ([142d0c2](https://github.com/honua-io/honua-sdk-python/commit/142d0c200ab6681109e2f00a8d9f0c1bf40b8af9))

## [0.0.1a0] - Unreleased

### Added

- Core HTTP client (`HonuaClient`) for Honua Server REST API
- Feature query support with geometry and attribute filtering
- Optional gRPC transport via `honua-sdk[grpc]` extra
