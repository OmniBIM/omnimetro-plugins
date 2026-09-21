# -*- coding: utf-8 -*-
"""
migrator_core.models.migration_model
====================================
High-level records for Project, Levels, Grids, Views, Sheets,
and Migration Statistics.
"""

import time

class ProjectRecord(object):
    """Encapsulates document metadata, locations, and units."""
    def __init__(
        self,
        title="Project",
        file_path="",
        revit_version="2027",
        units="revit_internal",
        internal_origin=None,
        project_base_point=None,
        survey_point=None,
        true_north=0.0,
        phases=None,
        worksets=None,
        design_options=None,
        links=None
    ):
        self.title = title
        self.file_path = file_path
        self.revit_version = revit_version
        self.units = units
        self.internal_origin = internal_origin or [0.0, 0.0, 0.0]
        self.project_base_point = project_base_point or [0.0, 0.0, 0.0]
        self.survey_point = survey_point or [0.0, 0.0, 0.0]
        self.true_north = true_north
        self.phases = phases or []
        self.worksets = worksets or []
        self.design_options = design_options or []
        self.links = links or []

    def to_dict(self):
        return {
            "title": self.title,
            "file_path": self.file_path,
            "revit_version": self.revit_version,
            "units": self.units,
            "internal_origin": self.internal_origin,
            "project_base_point": self.project_base_point,
            "survey_point": self.survey_point,
            "true_north": self.true_north,
            "phases": self.phases,
            "worksets": self.worksets,
            "design_options": self.design_options,
            "links": self.links
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            title=data.get("title", "Project"),
            file_path=data.get("file_path", ""),
            revit_version=data.get("revit_version", "2027"),
            units=data.get("units", "revit_internal"),
            internal_origin=data.get("internal_origin", [0.0, 0.0, 0.0]),
            project_base_point=data.get("project_base_point", [0.0, 0.0, 0.0]),
            survey_point=data.get("survey_point", [0.0, 0.0, 0.0]),
            true_north=data.get("true_north", 0.0),
            phases=data.get("phases", []),
            worksets=data.get("worksets", []),
            design_options=data.get("design_options", []),
            links=data.get("links", [])
        )

class LevelRecord(object):
    """Encapsulates a Level datum."""
    def __init__(self, source_id=None, unique_id="", name="", elevation=0.0):
        self.source_id = source_id
        self.unique_id = unique_id
        self.name = name
        self.elevation = elevation  # internal feet

    def to_dict(self):
        return {
            "source_id": self.source_id,
            "unique_id": self.unique_id,
            "name": self.name,
            "elevation": self.elevation
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            source_id=data.get("source_id"),
            unique_id=data.get("unique_id", ""),
            name=data.get("name", ""),
            elevation=data.get("elevation", 0.0)
        )

class GridRecord(object):
    """Encapsulates a Grid line datum."""
    def __init__(self, source_id=None, unique_id="", name="", curve_type="Line", points=None):
        self.source_id = source_id
        self.unique_id = unique_id
        self.name = name
        self.curve_type = curve_type
        self.points = points or []

    def to_dict(self):
        return {
            "source_id": self.source_id,
            "unique_id": self.unique_id,
            "name": self.name,
            "curve_type": self.curve_type,
            "points": self.points
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            source_id=data.get("source_id"),
            unique_id=data.get("unique_id", ""),
            name=data.get("name", ""),
            curve_type=data.get("curve_type", "Line"),
            points=data.get("points", [])
        )

class ViewRecord(object):
    """Encapsulates a Revit View."""
    def __init__(
        self,
        source_id=None,
        unique_id="",
        name="",
        view_type="FloorPlan",
        scale=100,
        detail_level="Coarse",
        discipline="Coordination",
        crop_box=None,
        view_template_id=None,
        associated_level_id=None
    ):
        self.source_id = source_id
        self.unique_id = unique_id
        self.name = name
        self.view_type = view_type
        self.scale = scale
        self.detail_level = detail_level
        self.discipline = discipline
        self.crop_box = crop_box
        self.view_template_id = view_template_id
        self.associated_level_id = associated_level_id

    def to_dict(self):
        return {
            "source_id": self.source_id,
            "unique_id": self.unique_id,
            "name": self.name,
            "view_type": self.view_type,
            "scale": self.scale,
            "detail_level": self.detail_level,
            "discipline": self.discipline,
            "crop_box": self.crop_box,
            "view_template_id": self.view_template_id,
            "associated_level_id": self.associated_level_id
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            source_id=data.get("source_id"),
            unique_id=data.get("unique_id", ""),
            name=data.get("name", ""),
            view_type=data.get("view_type", "FloorPlan"),
            scale=data.get("scale", 100),
            detail_level=data.get("detail_level", "Coarse"),
            discipline=data.get("discipline", "Coordination"),
            crop_box=data.get("crop_box"),
            view_template_id=data.get("view_template_id"),
            associated_level_id=data.get("associated_level_id")
        )

class SheetRecord(object):
    """Encapsulates a Sheet and its placed viewports."""
    def __init__(
        self,
        source_id=None,
        unique_id="",
        sheet_number="A101",
        sheet_name="Unnamed",
        titleblock_family="",
        viewports=None
    ):
        self.source_id = source_id
        self.unique_id = unique_id
        self.sheet_number = sheet_number
        self.sheet_name = sheet_name
        self.titleblock_family = titleblock_family
        self.viewports = viewports or []

    def to_dict(self):
        return {
            "source_id": self.source_id,
            "unique_id": self.unique_id,
            "sheet_number": self.sheet_number,
            "sheet_name": self.sheet_name,
            "titleblock_family": self.titleblock_family,
            "viewports": self.viewports
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            source_id=data.get("source_id"),
            unique_id=data.get("unique_id", ""),
            sheet_number=data.get("sheet_number", "A101"),
            sheet_name=data.get("sheet_name", "Unnamed"),
            titleblock_family=data.get("titleblock_family", ""),
            viewports=data.get("viewports", [])
        )

class MigrationActionRecord(object):
    """Tracks a single migration operation for validation and audit."""
    def __init__(self, action_id=None, source_id=None, action_type="", target_id=None, status="SUCCESS", message=""):
        self.action_id = action_id
        self.source_id = source_id
        self.action_type = action_type
        self.target_id = target_id
        self.status = status
        self.message = message
        self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self):
        return {
            "action_id": self.action_id,
            "source_id": self.source_id,
            "action_type": self.action_type,
            "target_id": self.target_id,
            "status": self.status,
            "message": self.message,
            "timestamp": self.timestamp
        }

class MigrationErrorRecord(object):
    """Tracks detailed failure or skip reasons for any object."""
    def __init__(self, error_id=None, source_id=None, category="", phase="UNKNOWN", message="", stacktrace="", fallback=""):
        self.error_id = error_id
        self.source_id = source_id
        self.category = category
        self.phase = phase
        self.message = message
        self.stacktrace = stacktrace
        self.fallback = fallback
        self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self):
        return {
            "error_id": self.error_id,
            "source_id": self.source_id,
            "category": self.category,
            "phase": self.phase,
            "message": self.message,
            "stacktrace": self.stacktrace,
            "fallback": self.fallback,
            "timestamp": self.timestamp
        }

class MigrationStats(object):
    """Aggregated statistics for scanning and migration outcomes."""
    def __init__(self):
        self.total_elements = 0
        self.native_count = 0
        self.family_count = 0
        self.geometry_count = 0
        self.skipped_count = 0
        self.failed_count = 0
        self.warnings_count = 0

    @property
    def coverage_percent(self):
        if self.total_elements == 0:
            return 100.0
        migratable = self.native_count + self.family_count + self.geometry_count
        return round((float(migratable) / float(self.total_elements)) * 100.0, 2)

    def to_dict(self):
        return {
            "total_elements": self.total_elements,
            "native_count": self.native_count,
            "family_count": self.family_count,
            "geometry_count": self.geometry_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "warnings_count": self.warnings_count,
            "coverage_percent": self.coverage_percent
        }
