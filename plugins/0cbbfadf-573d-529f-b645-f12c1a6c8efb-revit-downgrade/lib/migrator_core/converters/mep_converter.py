# -*- coding: utf-8 -*-
"""
migrator_core.converters.mep_converter
======================================
Converts MEP linear elements (Pipes, Ducts, Cable Trays, Conduits).
"""

from ..compat import IS_REVIT, DB
from .base_converter import BaseConverter
from ..infra.extensible_storage import set_migration_metadata

class MEPConverter(BaseConverter):

    MEP_CATEGORIES = set([
        "Pipes", "管道",
        "Ducts", "风管",
        "Cable Trays", "电缆桥架",
        "Conduits", "线管",
        "Flex Pipes", "软管",
        "Flex Ducts", "软风管"
    ])

    MEP_CLASSES = set([
        "Pipe", "Duct", "CableTray", "Conduit", "FlexPipe", "FlexDuct"
    ])

    def can_convert(self, record, context):
        if getattr(record, "element_class", "") in self.MEP_CLASSES:
            return True
        return getattr(record, "category_name", "") in self.MEP_CATEGORIES

    def convert(self, record, context):
        doc = context.doc
        if not IS_REVIT or not doc:
            return None

        loc_data = record.location_data or {}
        start = loc_data.get("start")
        end = loc_data.get("end")
        if not start or not end:
            return None

        p0 = DB.XYZ(start[0], start[1], start[2])
        p1 = DB.XYZ(end[0], end[1], end[2])

        level_id = context.get_target_level_id(record.level_id)
        if not level_id:
            col = DB.FilteredElementCollector(doc).OfClass(DB.Level)
            lvl = col.FirstElement()
            level_id = lvl.Id if lvl else DB.ElementId.InvalidElementId

        cat = record.category_name or ""
        el_class = record.element_class or ""
        element = None

        try:
            if el_class in ("Pipe", "FlexPipe") or cat in ("Pipes", "管道", "Flex Pipes", "软管"):
                # Find PipeType & PipingSystemType
                pt_col = DB.FilteredElementCollector(doc).OfClass(DB.Plumbing.PipeType)
                pipe_type = pt_col.FirstElement()
                st_col = DB.FilteredElementCollector(doc).OfClass(DB.Plumbing.PipingSystemType)
                sys_type = st_col.FirstElement()
                if pipe_type and sys_type:
                    element = DB.Plumbing.Pipe.Create(doc, sys_type.Id, pipe_type.Id, level_id, p0, p1)

            elif el_class in ("Duct", "FlexDuct") or cat in ("Ducts", "风管", "Flex Ducts", "软风管"):
                dt_col = DB.FilteredElementCollector(doc).OfClass(DB.Mechanical.DuctType)
                duct_type = dt_col.FirstElement()
                mst_col = DB.FilteredElementCollector(doc).OfClass(DB.Mechanical.MechanicalSystemType)
                sys_type = mst_col.FirstElement()
                if duct_type and sys_type:
                    element = DB.Mechanical.Duct.Create(doc, sys_type.Id, duct_type.Id, level_id, p0, p1)

            elif el_class == "CableTray" or cat in ("Cable Trays", "电缆桥架"):
                ct_col = DB.FilteredElementCollector(doc).OfClass(DB.Electrical.CableTrayType)
                ct_type = ct_col.FirstElement()
                if ct_type:
                    element = DB.Electrical.CableTray.Create(doc, ct_type.Id, p0, p1, level_id)

            elif el_class == "Conduit" or cat in ("Conduits", "线管"):
                cd_col = DB.FilteredElementCollector(doc).OfClass(DB.Electrical.ConduitType)
                cd_type = cd_col.FirstElement()
                if cd_type:
                    element = DB.Electrical.Conduit.Create(doc, cd_type.Id, p0, p1, level_id)

        except Exception:
            pass

        if element:
            context.apply_parameters(element, record.parameters)
            set_migration_metadata(element, record.source_unique_id, context.package_id)

            t_id_int = element.Id.IntegerValue if hasattr(element.Id, "IntegerValue") else element.Id.Value
            context.register_mapping(
                source_unique_id=record.source_unique_id,
                source_element_id=record.source_element_id,
                target_element_id=t_id_int,
                target_unique_id=element.UniqueId
            )

        return element
