# -*- coding: utf-8 -*-
"""
migrator_core.scanner.family_scanner
====================================
Inspects families, distinguishing system, loadable, and in-place families,
and generates family recipes.
"""

from ..compat import IS_REVIT, DB
from ..models import FamilyRecord, FamilyTypeRecord, FamilyParameterDefinition

class FamilyScanner(object):
    """Scans all families in the project and extracts family recipes."""

    def __init__(self, doc):
        self.doc = doc

    def scan(self, progress_callback=None):
        family_records = []
        if not IS_REVIT or not self.doc:
            return family_records

        collector = DB.FilteredElementCollector(self.doc).OfClass(DB.Family)
        total_fams = collector.GetElementCount() if hasattr(collector, "GetElementCount") else 100
        count = 0
        for fam in collector:
            count += 1
            if not fam:
                continue
            if hasattr(fam, "IsValidObject") and not fam.IsValidObject:
                continue

            try:
                cat = fam.FamilyCategory
                if not cat:
                    continue
                # ONLY scan Model families! Skip Annotation tags, Room tags, Arrowheads, etc.
                if hasattr(cat, "CategoryType") and cat.CategoryType != DB.CategoryType.Model:
                    continue
            except Exception:
                continue

            try:
                fam_id = fam.Id.Value if hasattr(fam.Id, "Value") else fam.Id.IntegerValue
                fam_name = getattr(fam, "Name", "") or "Family"
            except Exception:
                continue

            if progress_callback and (count % 5 == 0 or count == total_fams):
                try:
                    progress_callback(count, total_fams, u"[族] {}".format(fam_name))
                except Exception:
                    pass

            try:
                cat_name = getattr(cat, "Name", "Generic Models") or "Generic Models"
                cat_id = cat.Id.Value if hasattr(cat.Id, "Value") else cat.Id.IntegerValue
                is_in_place = getattr(fam, "IsInPlace", False)
                is_editable = getattr(fam, "IsEditable", True)

                # Skip in-place families from symbol scanning
                if is_in_place:
                    record = FamilyRecord(
                        family_id=fam_id,
                        family_name=fam_name,
                        category_name=cat_name,
                        category_id=cat_id,
                        is_loadable=False,
                        is_in_place=True,
                        template_category=cat_name,
                        types=[]
                    )
                    family_records.append(record)
                    continue

                # Collect family types (symbols) safely
                types = []
                sym_ids = []
                try:
                    sym_ids = fam.GetFamilySymbolIds()
                except Exception:
                    sym_ids = []

                for sid in sym_ids:
                    try:
                        sym = self.doc.GetElement(sid)
                        if not sym or (hasattr(sym, "IsValidObject") and not sym.IsValidObject):
                            continue
                        s_id = sym.Id.Value if hasattr(sym.Id, "Value") else sym.Id.IntegerValue
                        s_name = getattr(sym, "Name", "") or ""
                        type_values = {}
                        # Extract type parameter values safely
                        try:
                            for p in sym.Parameters:
                                try:
                                    if not p or not p.Definition or p.IsReadOnly:
                                        continue
                                    p_name = p.Definition.Name
                                    st = p.StorageType
                                    val = None
                                    if st == DB.StorageType.Double:
                                        val = p.AsDouble()
                                    elif st == DB.StorageType.Integer:
                                        val = p.AsInteger()
                                    elif st == DB.StorageType.String:
                                        val = p.AsString()
                                    if val is not None:
                                        type_values[p_name] = val
                                except Exception:
                                    continue
                        except Exception:
                            pass

                        types.append(FamilyTypeRecord(name=s_name, type_id=s_id, values=type_values))
                    except Exception:
                        continue

                record = FamilyRecord(
                    family_id=fam_id,
                    family_name=fam_name,
                    category_name=cat_name,
                    category_id=cat_id,
                    is_loadable=True,
                    is_in_place=False,
                    template_category=cat_name,
                    types=types
                )
                family_records.append(record)

            except Exception:
                continue

        return family_records
