# -*- coding: utf-8 -*-
"""
migrator_core.converters.material_converter
===========================================
Converts Material records into Revit 2020 materials, restoring colors
and transparency.
"""

from ..compat import IS_REVIT, DB
from .base_converter import BaseConverter

class MaterialConverter(BaseConverter):

    def can_convert(self, record, context):
        return hasattr(record, "color_r")

    def convert(self, record, context):
        doc = context.doc
        if not IS_REVIT or not doc:
            return None

        # Check if material exists
        target_mat = None
        col = DB.FilteredElementCollector(doc).OfClass(DB.Material)
        for m in col:
            if m.Name == record.name:
                target_mat = m
                break

        if not target_mat:
            mat_id = DB.Material.Create(doc, record.name)
            target_mat = doc.GetElement(mat_id)

        # Set appearance / color
        try:
            target_mat.Color = DB.Color(
                int(record.color_r),
                int(record.color_g),
                int(record.color_b)
            )
            target_mat.Transparency = int(record.transparency)
            target_mat.Shininess = int(record.shininess)
            target_mat.Smoothness = int(record.smoothness)
        except Exception:
            pass

        t_id_int = target_mat.Id.IntegerValue if hasattr(target_mat.Id, "IntegerValue") else target_mat.Id.Value
        context.register_mapping(
            source_unique_id=str(record.source_id),
            source_element_id=record.source_id,
            target_element_id=t_id_int,
            target_unique_id=target_mat.UniqueId
        )

        return target_mat
