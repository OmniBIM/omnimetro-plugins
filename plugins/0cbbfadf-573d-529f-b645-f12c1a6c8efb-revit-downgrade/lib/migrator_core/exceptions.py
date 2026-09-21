# -*- coding: utf-8 -*-
"""
migrator_core.exceptions
========================
Custom exception hierarchy for the Revit 2027 -> 2020 Migration Platform.
"""

class MigratorError(Exception):
    """Base exception for all migrator errors."""
    def __init__(self, message, source_id=None, category=None):
        super(MigratorError, self).__init__(message)
        self.source_id = source_id
        self.category = category

class CriticalMigrationError(MigratorError):
    """Errors that prevent the entire migration process from continuing."""
    pass

class PackageCorruptionError(CriticalMigrationError):
    """Raised when the migration package (.rvtmig) is corrupt or invalid."""
    pass

class UnsupportedVersionError(CriticalMigrationError):
    """Raised when the package schema version is not supported."""
    pass

class ElementConversionError(MigratorError):
    """Raised when a single element fails conversion. Should trigger fallback."""
    def __init__(self, message, source_id=None, category=None, inner_exc=None):
        super(ElementConversionError, self).__init__(message, source_id, category)
        self.inner_exc = inner_exc

class GeometryExtractionError(MigratorError):
    """Raised when geometry extraction fails for an element."""
    pass

class FamilyRebuildError(MigratorError):
    """Raised when family reconstruction fails."""
    pass

class CancellationError(MigratorError):
    """Raised when migration is cleanly canceled by the user."""
    pass
