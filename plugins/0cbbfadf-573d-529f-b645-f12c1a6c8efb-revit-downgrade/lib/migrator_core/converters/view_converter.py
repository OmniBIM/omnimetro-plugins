# -*- coding: utf-8 -*-
"""
migrator_core.converters.view_converter
======================================
Converts View and Sheet records into Revit 2020 views and drawing sheets.
"""

from ..compat import IS_REVIT, DB
from .base_converter import BaseConverter
from ..infra.extensible_storage import set_migration_metadata

class ViewConverter(BaseConverter):

    def can_convert(self, record, context):
        return hasattr(record, "view_type")

    def convert(self, record, context):
        doc = context.doc
        if not IS_REVIT or not doc:
            return None

        view_type = record.view_type
        target_view = None

        try:
            if "FloorPlan" in view_type:
                # Find FloorPlan ViewFamilyType
                vft_col = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
                vft_id = None
                for vft in vft_col:
                    if vft.ViewFamily == DB.ViewFamily.FloorPlan:
                        vft_id = vft.Id
                        break

                # Resolve associated level
                lvl_id = context.get_target_level_id(record.associated_level_id)
                if not lvl_id:
                    col = DB.FilteredElementCollector(doc).OfClass(DB.Level)
                    lvl = col.FirstElement()
                    lvl_id = lvl.Id if lvl else None

                if vft_id and lvl_id:
                    target_view = DB.ViewPlan.Create(doc, vft_id, lvl_id)

            elif "ThreeD" in view_type:
                vft_col = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
                vft_3d = None
                for vft in vft_col:
                    if vft.ViewFamily == DB.ViewFamily.ThreeDimensional:
                        vft_3d = vft.Id
                        break
                if vft_3d:
                    target_view = DB.View3D.CreateIsometric(doc, vft_3d)

            if target_view:
                try:
                    target_view.Name = record.name
                except Exception:
                    pass
                if record.scale and record.scale > 0:
                    target_view.Scale = int(record.scale)

                t_id_int = target_view.Id.IntegerValue if hasattr(target_view.Id, "IntegerValue") else target_view.Id.Value
                context.register_mapping(
                    source_unique_id=record.unique_id,
                    source_element_id=record.source_id,
                    target_element_id=t_id_int,
                    target_unique_id=target_view.UniqueId
                )

        except Exception:
            pass

        return target_view

class SheetConverter(BaseConverter):

    def can_convert(self, record, context):
        return hasattr(record, "sheet_number")

    def convert(self, record, context):
        doc = context.doc
        if not IS_REVIT or not doc:
            return None

        # Resolve title block
        tb_col = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks).WhereElementIsElementType()
        tb_id = DB.ElementId.InvalidElementId
        for tb in tb_col:
            tb_id = tb.Id
            break

        sheet = None
        try:
            sheet = DB.ViewSheet.Create(doc, tb_id)
            sheet.SheetNumber = record.sheet_number
            sheet.Name = record.sheet_name
        except Exception:
            pass

        if sheet:
            t_id_int = sheet.Id.IntegerValue if hasattr(sheet.Id, "IntegerValue") else sheet.Id.Value
            context.register_mapping(
                source_unique_id=record.unique_id,
                source_element_id=record.source_id,
                target_element_id=t_id_int,
                target_unique_id=sheet.UniqueId
            )

        return sheet
