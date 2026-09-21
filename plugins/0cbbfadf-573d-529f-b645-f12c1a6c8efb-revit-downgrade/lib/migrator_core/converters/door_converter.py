# -*- coding: utf-8 -*-
"""
migrator_core.converters.door_converter
=======================================
Converts Door records, resolving host walls and family symbols.
"""

from ..compat import IS_REVIT, DB
from .base_converter import BaseConverter
from ..infra.extensible_storage import set_migration_metadata

class DoorConverter(BaseConverter):

    def can_convert(self, record, context):
        return getattr(record, "category_name", "") in ("Doors", "门")

    def convert(self, record, context):
        doc = context.doc
        if not IS_REVIT or not doc:
            return None

        loc_data = record.location_data or {}
        pt_coords = loc_data.get("pt", [0.0, 0.0, 0.0])
        point = DB.XYZ(pt_coords[0], pt_coords[1], pt_coords[2])

        # Resolve level
        level_id = context.get_target_level_id(record.level_id)
        level_elem = doc.GetElement(level_id) if level_id else None

        # Resolve symbol
        symbol = self._resolve_symbol(doc, record)
        if not symbol:
            return None

        if not symbol.IsActive:
            symbol.Activate()

        # Resolve host wall
        host_elem = None
        if record.host_unique_id:
            host_elem = context.get_target_element_by_source_uid(record.host_unique_id)

        instance = None
        try:
            if host_elem and isinstance(host_elem, DB.Wall):
                instance = doc.Create.NewFamilyInstance(point, symbol, host_elem, level_elem, DB.Structure.StructuralType.NonStructural)
            elif level_elem:
                instance = doc.Create.NewFamilyInstance(point, symbol, level_elem, DB.Structure.StructuralType.NonStructural)
            else:
                instance = doc.Create.NewFamilyInstance(point, symbol, DB.Structure.StructuralType.NonStructural)
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
        col = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).OfCategory(DB.BuiltInCategory.OST_Doors)
        first_sym = None
        for sym in col:
            if not first_sym:
                first_sym = sym
            if sym.Name == target_name:
                return sym
            if fam_name and hasattr(sym, "FamilyName") and sym.FamilyName == fam_name:
                return sym
        return first_sym
