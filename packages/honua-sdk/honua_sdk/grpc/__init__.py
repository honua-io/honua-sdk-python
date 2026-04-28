"""Honua gRPC client and domain models."""
from __future__ import annotations

from honua_sdk.errors import HonuaGrpcError
from ._client import HonuaGrpcAsyncClient, HonuaGrpcClient, build_grpc_metadata
from ._models import (
    DistanceUnit,
    Extent,
    Feature,
    FeaturePage,
    FieldDefinition,
    FieldType,
    GeometryType,
    QueryFeaturesRequest,
    QueryFeaturesResponse,
    SpatialFilter,
    SpatialReference,
    SpatialRelationship,
    StatisticDefinition,
    StatisticType,
)

__all__ = [
    "DistanceUnit",
    "Extent",
    "Feature",
    "FeaturePage",
    "FieldDefinition",
    "FieldType",
    "GeometryType",
    "HonuaGrpcAsyncClient",
    "HonuaGrpcClient",
    "HonuaGrpcError",
    "QueryFeaturesRequest",
    "QueryFeaturesResponse",
    "SpatialFilter",
    "SpatialReference",
    "SpatialRelationship",
    "StatisticDefinition",
    "StatisticType",
    "build_grpc_metadata",
]
