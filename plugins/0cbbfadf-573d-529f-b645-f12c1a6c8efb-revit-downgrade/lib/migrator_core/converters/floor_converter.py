# -*- coding: utf-8 -*-
"""
migrator_core.converters.floor_converter
========================================
Converts Floor records into native Revit 2020 Floor elements.
"""

from ..compat import IS_REVIT, DB
from .base_converter import BaseConverter
from ..infra.extensible_storage import set_migration_metadata

class FloorConverter(BaseConverter):

    def can_convert(self, record, context):
        if getattr(record, "element_class", "") == "Floor":
            return True
        return getattr(record, "category_name", "") in ("Floors", "楼板")

    def convert(self, record, context):
        doc = context.doc
        if not IS_REVIT or not doc:
            return None

        # Resolve level
        level_id = context.get_target_level_id(record.level_id)
        level_elem = doc.GetElement(level_id) if level_id else None
        if not level_elem:
            col = DB.FilteredElementCollector(doc).OfClass(DB.Level)
            level_elem = col.FirstElement()

        # Floor Type
        floor_type_id = self._resolve_floor_type(doc, record)
        floor_type = doc.GetElement(floor_type_id) if floor_type_id else None

        # Build boundary curves
        curve_array = self._build_boundary(record)
        if not curve_array or curve_array.Size < 3:
            return None

        floor = None
        try:
            # Revit 2020: Document.Create.NewFloor(CurveArray, FloorType, Level, bool isStructural)
            floor = doc.Create.NewFloor(curve_array, floor_type, level_elem, False)
        except Exception:
            pass

        if floor:
            context.apply_parameters(floor, record.parameters)
            set_migration_metadata(floor, record.source_unique_id, context.package_id)
            t_id_int = floor.Id.IntegerValue if hasattr(floor.Id, "IntegerValue") else floor.Id.Value
            context.register_mapping(
                source_unique_id=record.source_unique_id,
                source_element_id=record.source_element_id,
                target_element_id=t_id_int,
                target_unique_id=floor.UniqueId
            )

        return floor

    def _build_boundary(self, record):
        ca = DB.CurveArray()
        loc_data = record.location_data or {}
        boundary = loc_data.get("boundary", [])
        if not boundary:
            # Construct from bounding box if explicit boundary not present
            bmin = record.bbox_min
            bmax = record.bbox_max
            z = bmin[2]
            p0 = DB.XYZ(bmin[0], bmin[1], z)
            p1 = DB.XYZ(bmax[0], bmin[1], z)
            p2 = DB.XYZ(bmax[0], bmax[1], z)
            p3 = DB.XYZ(bmin[0], bmax[1], z)
            ca.Append(DB.Line.CreateBound(p0, p1))
            ca.Append(DB.Line.CreateBound(p1, p2))
            ca.Append(DB.Line.CreateBound(p2, p3))
            ca.Append(DB.Line.CreateBound(p3, p0))
            return ca

        for i in range(len(boundary)):
            p_curr = DB.XYZ(boundary[i][0], boundary[i][1], boundary[i][2])
            next_idx = (i + 1) % len(boundary)
            p_next = DB.XYZ(boundary[next_idx][0], boundary[next_idx][1], boundary[next_idx][2])
            ca.Append(DB.Line.CreateBound(p_curr, p_next))

        return ca

    def _resolve_floor_type(self, doc, record):
        col = DB.FilteredElementCollector(doc).OfClass(DB.FloorType)
        first_id = None
        for ft in col:
            if not first_id:
                first_id = ft.Id
            if ft.Name == record.element_type_name:
                return ft.Id
        return first_id
