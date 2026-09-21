# -*- coding: utf-8 -*-
"""
migrator_core.converters.level_converter
========================================
Converts Level records into native Revit 2020 Level elements.
"""

from ..compat import IS_REVIT, DB
from .base_converter import BaseConverter
from ..constants import ToleranceConfig

class LevelConverter(BaseConverter):

    def can_convert(self, record, context):
        return record.category_name == "Levels" or hasattr(record, "elevation")

    def convert(self, record, context):
        doc = context.doc
        if not IS_REVIT or not doc:
            return None

        elevation = record.elevation
        target_level = None

        # Check if an existing level matches this elevation closely
        col = DB.FilteredElementCollector(doc).OfClass(DB.Level)
        for lvl in col:
            if abs(lvl.Elevation - elevation) < ToleranceConfig.POSITION:
                target_level = lvl
                break

        if not target_level:
            target_level = DB.Level.Create(doc, elevation)

        # Set or update name
        try:
            target_level.Name = record.name
        except Exception:
            # Handle duplicate names gracefully
            try:
                target_level.Name = "{}_migrated".format(record.name)
            except Exception:
                pass

        # Register mapping
        t_id_int = target_level.Id.IntegerValue if hasattr(target_level.Id, "IntegerValue") else target_level.Id.Value
        context.register_mapping(
            source_unique_id=record.unique_id,
            source_element_id=record.source_id,
            target_element_id=t_id_int,
            target_unique_id=target_level.UniqueId
        )

        return target_level
