# -*- coding: utf-8 -*-
"""
migrator_core
=============
Revit 2027 -> Revit 2020 BIM Migration Platform Core Package.
"""

from .constants import (
    SCHEMA_VERSION,
    TOOL_VERSION,
    MigrationLevel,
    Phase,
    ToleranceConfig,
    StorageType,
    ActionStatus
)
from .config import MigrationConfig, MigrationProfile
from .exceptions import (
    MigratorError,
    CriticalMigrationError,
    PackageCorruptionError,
    UnsupportedVersionError,
    ElementConversionError
)
from .importer_engine import Revit2020ImporterEngine, MigrationContext

__version__ = TOOL_VERSION
