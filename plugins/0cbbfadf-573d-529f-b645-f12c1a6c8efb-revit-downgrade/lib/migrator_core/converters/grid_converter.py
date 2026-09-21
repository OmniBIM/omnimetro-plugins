# -*- coding: utf-8 -*-
"""
migrator_core.converters.grid_converter
=======================================
Converts Grid records into native Revit 2020 Grid lines.
"""

from ..compat import IS_REVIT, DB
from .base_converter import BaseConverter

class GridConverter(BaseConverter):

    def can_convert(self, record, context):
        return record.category_name == "Grids" or hasattr(record, "curve_type")

    def convert(self, record, context):
        doc = context.doc
        if not IS_REVIT or not doc or not record.points or len(record.points) < 2:
            return None

        p0 = DB.XYZ(record.points[0][0], record.points[0][1], record.points[0][2])
        p1 = DB.XYZ(record.points[1][0], record.points[1][1], record.points[1][2])

        curve = None
        if record.curve_type == "Line":
            curve = DB.Line.CreateBound(p0, p1)
        elif record.curve_type == "Arc" and len(record.points) >= 3:
            pm = DB.XYZ(record.points[2][0], record.points[2][1], record.points[2][2])
            curve = DB.Arc.Create(p0, p1, pm)

        if not curve:
            curve = DB.Line.CreateBound(p0, p1)

        grid = DB.Grid.Create(doc, curve)
        try:
            grid.Name = record.name
        except Exception:
            try:
                grid.Name = "{}_migrated".format(record.name)
            except Exception:
                pass

        t_id_int = grid.Id.IntegerValue if hasattr(grid.Id, "IntegerValue") else grid.Id.Value
        context.register_mapping(
            source_unique_id=record.unique_id,
            source_element_id=record.source_id,
            target_element_id=t_id_int,
            target_unique_id=grid.UniqueId
        )

        return grid
