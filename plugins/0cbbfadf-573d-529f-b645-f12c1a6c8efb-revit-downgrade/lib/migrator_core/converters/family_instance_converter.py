# -*- coding: utf-8 -*-
"""
migrator_core.converters.family_instance_converter
==================================================
Converts loadable family instances (Columns, Framing, Furniture, Equipment,
Generic Models).
"""

from ..compat import IS_REVIT, DB
from .base_converter import BaseConverter
from ..infra.extensible_storage import set_migration_metadata

class FamilyInstanceConverter(BaseConverter):

    def can_convert(self, record, context):
        return True  # Handles any family instance or general placement

    def convert(self, record, context):
        doc = context.doc
        if not IS_REVIT or not doc:
            return None

        loc_type = record.location_type
        loc_data = record.location_data or {}

        # Resolve level
        level_id = context.get_target_level_id(record.level_id)
        level_elem = doc.GetElement(level_id) if level_id else None

        # Resolve symbol
        symbol = self._resolve_symbol(doc, record)
        if not symbol:
            return None

        if not symbol.IsActive:
            symbol.Activate()

        structural_type = DB.Structure.StructuralType.NonStructural
        if "Column" in record.category_name:
            structural_type = DB.Structure.StructuralType.Column
        elif "Framing" in record.category_name:
            structural_type = DB.Structure.StructuralType.Beam

        instance = None

        if loc_type == "Curve" and "start" in loc_data and "end" in loc_data:
            # Curve placement (e.g. Beams)
            p0 = DB.XYZ(loc_data["start"][0], loc_data["start"][1], loc_data["start"][2])
            p1 = DB.XYZ(loc_data["end"][0], loc_data["end"][1], loc_data["end"][2])
            curve = DB.Line.CreateBound(p0, p1)
            try:
                instance = doc.Create.NewFamilyInstance(curve, symbol, level_elem, structural_type)
            except Exception:
                pass
        else:
            # Point placement
            pt_coords = loc_data.get("pt", [0.0, 0.0, 0.0])
            point = DB.XYZ(pt_coords[0], pt_coords[1], pt_coords[2])
            try:
                if level_elem:
                    instance = doc.Create.NewFamilyInstance(point, symbol, level_elem, structural_type)
                else:
                    instance = doc.Create.NewFamilyInstance(point, symbol, structural_type)
            except Exception:
                pass

        if instance:
            context.apply_parameters(instance, record.parameters)
            set_migration_metadata(instance, record.source_unique_id, context.package_id)

            t_id_int = instance.Id.IntegerValue if hasattr(instance.Id, "IntegerValue") else instance.Id.Value
            context.register_mapping(
                source_unique_id=record.source_unique_id,
                source_element_id=record.source_element_id,
                target_element_id=t_id_int,
                target_unique_id=instance.UniqueId
            )

        return instance

    def _resolve_symbol(self, doc, record):
        target_name = record.element_type_name
        fam_name = record.family_name
        col = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)
        first_match = None
        for sym in col:
            if sym.Name == target_name:
                return sym
            if fam_name and hasattr(sym, "FamilyName") and sym.FamilyName == fam_name:
                first_match = sym
        return first_match
