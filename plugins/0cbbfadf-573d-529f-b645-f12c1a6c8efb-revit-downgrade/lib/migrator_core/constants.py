# -*- coding: utf-8 -*-
"""
migrator_core.constants
=======================
Global constants, enumeration-like mappings, tolerance definitions,
and schema versioning for Revit 2027 -> Revit 2020 BIM Migration Platform.
"""

# Schema & Tool Version
SCHEMA_VERSION = "1.0.0"
TOOL_VERSION = "0.1.0"
DEFAULT_SOURCE_VERSION = "2027"
DEFAULT_TARGET_VERSION = "2020"

# 5-Level Migration Strategy
class MigrationLevel(object):
    NATIVE = 1                   # Level 1: Native Revit object rebuild (Wall, Floor, Level, etc.)
    FAMILY_REBUILD = 2           # Level 2: Family recipe reconstruction into loadable RFA
    FAMILY_GEOMETRY = 3          # Level 3: Family geometry fallback into generic model family
    DIRECT_SHAPE = 4             # Level 4: Project direct shape / SAT / mesh geometry fallback
    SKIP = 5                     # Level 5: Unsupported or user-skipped, logged to report

    NAMES = {
        NATIVE: "Native Rebuild",
        FAMILY_REBUILD: "Family Reconstruction",
        FAMILY_GEOMETRY: "Family Geometry Fallback",
        DIRECT_SHAPE: "DirectShape Fallback",
        SKIP: "Skipped / Unsupported"
    }

# Scoring values
MIGRATION_SCORES = {
    MigrationLevel.NATIVE: 100,
    MigrationLevel.FAMILY_REBUILD: 80,
    MigrationLevel.FAMILY_GEOMETRY: 70,
    MigrationLevel.DIRECT_SHAPE: 60,
    MigrationLevel.SKIP: 0
}

# Reconstruction Phases (Strict Dependency Order)
class Phase(object):
    PROJECT_INIT = 0     # ProjectInfo, Units, Location, Phases, Worksets, Materials
    DATUMS = 1           # Levels, Grids, Reference Planes
    TYPES = 2            # System Types, Loaded Family Symbols
    HOSTS = 3            # Walls, Floors, Roofs, Ceilings, Structural Columns/Beams
    HOSTED = 4           # Doors, Windows, Fixtures, Hosted Equipment
    MEP = 5              # Pipes, Ducts, Cable Trays, Conduits, Fittings
    SPECIAL = 6          # Rooms, Spaces, Areas, Groups, Assemblies
    VIEWS = 7            # FloorPlans, 3D, Sections, Elevations, Schedules, ViewTemplates
    SHEETS = 8           # Sheets, Titleblocks, Viewports, ScheduleInstances
    ANNOTATIONS = 9      # Dimensions, Tags, Detail Lines, Text, Filled Regions

    NAMES = {
        PROJECT_INIT: "Phase 0: Project Initialization",
        DATUMS: "Phase 1: Datums (Levels & Grids)",
        TYPES: "Phase 2: Types & Symbols",
        HOSTS: "Phase 3: Host Elements (Walls, Floors, Roofs)",
        HOSTED: "Phase 4: Hosted Elements (Doors, Windows)",
        MEP: "Phase 5: MEP Systems & Elements",
        SPECIAL: "Phase 6: Rooms & Special Elements",
        VIEWS: "Phase 7: Views & Schedules",
        SHEETS: "Phase 8: Sheets & Viewports",
        ANNOTATIONS: "Phase 9: Annotations & Details"
    }

# Tolerances
class ToleranceConfig(object):
    POSITION = 1e-5       # feet
    ANGLE = 1e-4          # radians
    GEOMETRY = 1e-4       # general geometry precision
    VOLUME = 1e-3         # cubic feet
    AREA = 1e-3           # square feet

# Storage Types (Revit Parameter StorageType)
class StorageType(object):
    NONE = "None"
    INTEGER = "Integer"
    DOUBLE = "Double"
    STRING = "String"
    ELEMENT_ID = "ElementId"

# Action Statuses
class ActionStatus(object):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    FALLBACK = "FALLBACK"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    CRITICAL = "CRITICAL"

# Default File Names & Extensions
PACKAGE_EXTENSION = ".rvtmig"
SQLITE_DB_NAME = "migration.sqlite"
MANIFEST_FILE_NAME = "manifest.json"
SHARED_PARAMS_FILENAME = "MigrationSharedParameters.txt"

# Default batch configuration
DEFAULT_BATCH_SIZE = 1000
