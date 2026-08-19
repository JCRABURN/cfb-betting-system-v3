"""Fail-closed production-readiness controls for CFB Betting System V3."""

from operations.config import (
    ACTIVE_CONFIGURATION_VERSION,
    ACTIVE_FEATURE_SCHEMA_VERSION,
    ACTIVE_MODEL_NAME,
    ACTIVE_MODEL_VERSION,
    EXPECTED_REPOSITORY,
    PRODUCTION_OPERATIONS,
    ProductionSettings,
    load_production_settings,
)
from operations.preflight import (
    PreflightCheck,
    ProductionPreflightReport,
    run_production_preflight,
)

__all__ = [
    "ACTIVE_CONFIGURATION_VERSION",
    "ACTIVE_FEATURE_SCHEMA_VERSION",
    "ACTIVE_MODEL_NAME",
    "ACTIVE_MODEL_VERSION",
    "EXPECTED_REPOSITORY",
    "PRODUCTION_OPERATIONS",
    "PreflightCheck",
    "ProductionPreflightReport",
    "ProductionSettings",
    "load_production_settings",
    "run_production_preflight",
]
