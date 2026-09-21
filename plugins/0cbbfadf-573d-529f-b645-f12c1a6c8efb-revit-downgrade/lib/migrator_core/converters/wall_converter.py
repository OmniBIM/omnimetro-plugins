# -*- coding: utf-8 -*-
"""
migrator_core.converters.wall_converter
=======================================
Converts Wall records into native Revit 2020 Wall elements.
"""

from ..compat import IS_REVIT, DB
from .base_converter import BaseConverter
from ..infra.extensible_storage import set_migration_metadata

class WallConverter(BaseConverter):

    def can_convert(self, record, context):
        if getattr(record, "element_class", "") == "Wall":
            return True
        return getattr(record, "category_name", "") in ("Walls", "墙", "墙体")

    def convert(self, record, context):
        doc = context.doc
        if not IS_REVIT or not doc:
            return None

        loc_data = record.location_data or {}
        curve = self._create_curve(loc_data)
        if not curve:
            return None

        # Level
        level_id = context.get_target_level_id(record.level_id)
        if not level_id:
            # Fallback to first level
            col = DB.FilteredElementCollector(doc).OfClass(DB.Level)
            lvl = col.FirstElement()
            level_id = lvl.Id if lvl else DB.ElementId.InvalidElementId

        # Wall Type
        wall_type_id = self._resolve_wall_type(doc, record)

        height = float(record.extra_data.get("height", 10.0))
        offset = 0.0
        flipped = bool(record.extra_data.get("is_flipped", False))
        structural = False

        wall = DB.Wall.Create(doc, curve, wall_type_id, level_id, height, offset, flipped, structural)

        # Restore parameters
        if wall:
            context.apply_parameters(wall, record.parameters)
            set_migration_metadata(wall, record.source_unique_id, context.package_id)

            t_id_int = wall.Id.IntegerValue if hasattr(wall.Id, "IntegerValue") else wall.Id.Value
            context.register_mapping(
                source_unique_id=record.source_unique_id,
                source_element_id=record.source_element_id,
                target_element_id=t_id_int,
                target_unique_id=wall.UniqueId
            )

        return wall

    def _create_curve(self, loc_data):
        c_type = loc_data.get("curve_type", "Line")
        start = loc_data.get("start")
        end = loc_data.get("end")
        if not start or not end:
            return None

        p0 = DB.XYZ(start[0], start[1], start[2])
        p1 = DB.XYZ(end[0], end[1], end[2])

        if c_type == "Arc" and "mid" in loc_data:
            mid = loc_data["mid"]
            pm = DB.XYZ(mid[0], mid[1], mid[2])
            try:
                return DB.Arc.Create(p0, p1, pm)
            except Exception:
                return DB.Line.CreateBound(p0, p1)
        return DB.Line.CreateBound(p0, p1)

    def _resolve_wall_type(self, doc, record):
        target_name = record.element_type_name or record.extra_data.get("wall_type_name", "")
        col = DB.FilteredElementCollector(doc).OfClass(DB.WallType)
        first_wt = None
        for wt in col:
            if not first_wt:
                first_wt = wt.Id
            if wt.Name == target_name:
                return wt.Id
        return first_wt or DB.ElementId.InvalidElementId
