# -*- coding: utf-8 -*-
"""
migrator_core.models.element_record
===================================
Element representation for extracted Revit instances and model objects.
"""

from ..constants import MigrationLevel, ActionStatus
from .parameter_record import ParameterRecord

class ElementRecord(object):
    """Encapsulates a single BIM element record independent of Revit API."""

    def __init__(
        self,
        source_element_id=None,
        source_unique_id="",
        category_id=None,
        category_name="",
        element_class="",
        element_type_id=None,
        element_type_name="",
        family_id=None,
        family_name="",
        level_id=None,
        level_name="",
        workset_id=None,
        phase_created_id=None,
        phase_demolished_id=None,
        design_option_id=None,
        group_id=None,
        location_type="",
        location_data=None,
        bbox_min=None,
        bbox_max=None,
        transform=None,
        migration_level=MigrationLevel.NATIVE,
        migration_score=100,
        fallback_type=None,
        status=ActionStatus.PENDING,
        host_unique_id=None,
        parameters=None,
        geometry_asset_id=None,
        extra_data=None,
        source_id=None
    ):
        self.source_element_id = source_element_id if source_element_id is not None else source_id
        self.source_unique_id = source_unique_id
        self.category_id = category_id
        self.category_name = category_name
        self.element_class = element_class
        self.element_type_id = element_type_id
        self.element_type_name = element_type_name
        self.family_id = family_id
        self.family_name = family_name
        self.level_id = level_id
        self.level_name = level_name
        self.workset_id = workset_id
        self.phase_created_id = phase_created_id
        self.phase_demolished_id = phase_demolished_id
        self.design_option_id = design_option_id
        self.group_id = group_id
        self.location_type = location_type
        self.location_data = location_data or {}
        self.bbox_min = bbox_min or [0.0, 0.0, 0.0]
        self.bbox_max = bbox_max or [0.0, 0.0, 0.0]
        self.transform = transform
        self.migration_level = migration_level
        self.migration_score = migration_score
        self.fallback_type = fallback_type
        self.status = status
        self.host_unique_id = host_unique_id
        self.parameters = parameters or []
        self.geometry_asset_id = geometry_asset_id
        self.extra_data = extra_data or {}

    @property
    def source_id(self):
        return self.source_element_id

    @source_id.setter
    def source_id(self, value):
        self.source_element_id = value

    def get_parameter(self, name):
        for p in self.parameters:
            if p.name == name:
                return p
        return None

    def get_parameter_value(self, name, default=None):
        p = self.get_parameter(name)
        if p:
            val = p.get_raw_value()
            if val is not None:
                return val
        return default

    def to_dict(self):
        return {
            "source_element_id": self.source_element_id,
            "source_id": self.source_element_id,
            "source_unique_id": self.source_unique_id,
            "category_id": self.category_id,
            "category_name": self.category_name,
            "element_class": self.element_class,
            "element_type_id": self.element_type_id,
            "element_type_name": self.element_type_name,
            "family_id": self.family_id,
            "family_name": self.family_name,
            "level_id": self.level_id,
            "level_name": self.level_name,
            "workset_id": self.workset_id,
            "phase_created_id": self.phase_created_id,
            "phase_demolished_id": self.phase_demolished_id,
            "design_option_id": self.design_option_id,
            "group_id": self.group_id,
            "location_type": self.location_type,
            "location_data": self.location_data,
            "bbox_min": self.bbox_min,
            "bbox_max": self.bbox_max,
            "transform": self.transform,
            "migration_level": self.migration_level,
            "migration_score": self.migration_score,
            "fallback_type": self.fallback_type,
            "status": self.status,
            "host_unique_id": self.host_unique_id,
            "parameters": [p.to_dict() for p in self.parameters],
            "geometry_asset_id": self.geometry_asset_id,
            "extra_data": self.extra_data
        }

    @classmethod
    def from_dict(cls, data):
        params = [ParameterRecord.from_dict(p) for p in data.get("parameters", [])]
        return cls(
            source_element_id=data.get("source_element_id") if data.get("source_element_id") is not None else data.get("source_id"),
            source_unique_id=data.get("source_unique_id", ""),
            category_id=data.get("category_id"),
            category_name=data.get("category_name", ""),
            element_class=data.get("element_class", ""),
            element_type_id=data.get("element_type_id"),
            element_type_name=data.get("element_type_name", ""),
            family_id=data.get("family_id"),
            family_name=data.get("family_name", ""),
            level_id=data.get("level_id"),
            level_name=data.get("level_name", ""),
            workset_id=data.get("workset_id"),
            phase_created_id=data.get("phase_created_id"),
            phase_demolished_id=data.get("phase_demolished_id"),
            design_option_id=data.get("design_option_id"),
            group_id=data.get("group_id"),
            location_type=data.get("location_type", ""),
            location_data=data.get("location_data", {}),
            bbox_min=data.get("bbox_min", [0.0, 0.0, 0.0]),
            bbox_max=data.get("bbox_max", [0.0, 0.0, 0.0]),
            transform=data.get("transform"),
            migration_level=data.get("migration_level", MigrationLevel.NATIVE),
            migration_score=data.get("migration_score", 100),
            fallback_type=data.get("fallback_type"),
            status=data.get("status", ActionStatus.PENDING),
            host_unique_id=data.get("host_unique_id"),
            parameters=params,
            geometry_asset_id=data.get("geometry_asset_id"),
            extra_data=data.get("extra_data", {})
        )
