# -*- coding: utf-8 -*-
"""
migrator_core.scanner.material_scanner
======================================
Scans Revit materials, colors, transparency, and texture asset paths.
"""

from ..compat import IS_REVIT, DB
from ..models import MaterialRecord

class MaterialScanner(object):
    """Extracts material records from the active Revit document."""

    def __init__(self, doc):
        self.doc = doc

    def scan(self, progress_callback=None):
        records = []
        if not IS_REVIT or not self.doc:
            return records

        collector = DB.FilteredElementCollector(self.doc).OfClass(DB.Material)
        total_mats = collector.GetElementCount() if hasattr(collector, "GetElementCount") else 100
        count = 0
        for mat in collector:
            count += 1
            if progress_callback and (count % 5 == 0 or count == total_mats):
                m_name = mat.Name or "Material"
                progress_callback(count, total_mats, u"[材质] {}".format(m_name))
            try:
                src_id = mat.Id.IntegerValue if hasattr(mat.Id, "IntegerValue") else mat.Id.Value
                name = mat.Name
                color = mat.Color
                r = color.Red if color else 128
                g = color.Green if color else 128
                b = color.Blue if color else 128
                transparency = mat.Transparency
                shininess = mat.Shininess
                smoothness = mat.Smoothness

                # Appearance asset name
                app_name = ""
                try:
                    if mat.AppearanceAssetId != DB.ElementId.InvalidElementId:
                        asset_elem = self.doc.GetElement(mat.AppearanceAssetId)
                        if asset_elem:
                            app_name = asset_elem.Name
                except Exception:
                    pass

                records.append(MaterialRecord(
                    source_id=src_id,
                    name=name,
                    color_r=r,
                    color_g=g,
                    color_b=b,
                    transparency=transparency,
                    shininess=shininess,
                    smoothness=smoothness,
                    appearance_name=app_name
                ))
            except Exception:
                continue

        return records
