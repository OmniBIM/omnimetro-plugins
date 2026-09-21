# -*- coding: utf-8 -*-
"""
migrator_core.geometry.sat_exporter
===================================
Exports element geometry to 3D ACIS (.sat) files via Revit API.
"""

import os
from ..compat import IS_REVIT, DB

class SATExporter(object):
    """Exports 3D SAT files for geometric fallback exchange."""

    @staticmethod
    def export_element_sat(doc, element, output_folder, filename=None):
        """
        Exports a single element to a .sat file.
        Returns the absolute path of the generated .sat file or None.
        """
        if not IS_REVIT or not doc or not element:
            return None

        if not os.path.exists(output_folder):
            try:
                os.makedirs(output_folder)
            except Exception:
                pass

        if not filename:
            filename = "{}.sat".format(element.UniqueId)
        elif not filename.endswith(".sat"):
            filename += ".sat"

        # Create a 3D view specifically for export or use active 3D view
        view_3d = None
        col = DB.FilteredElementCollector(doc).OfClass(DB.View3D)
        for v in col:
            if not v.IsTemplate:
                view_3d = v
                break

        if not view_3d:
            return None

        try:
            element_set = DB.ElementIdSet() if hasattr(DB, "ElementIdSet") else System.Collections.Generic.List[DB.ElementId]()
            element_set.Add(element.Id)

            opt = DB.SATExportOptions()
            base_name = os.path.splitext(filename)[0]
            success = doc.Export(output_folder, base_name, view_3d, opt)
            target_path = os.path.join(output_folder, filename)
            if os.path.exists(target_path):
                return target_path
        except Exception:
            pass

        return None
