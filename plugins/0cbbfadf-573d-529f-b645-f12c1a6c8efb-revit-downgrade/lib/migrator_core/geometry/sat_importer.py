# -*- coding: utf-8 -*-
"""
migrator_core.geometry.sat_importer
===================================
Imports 3D SAT files into Revit 2020 geometry objects.
"""

from ..compat import IS_REVIT, DB

class SATImporter(object):
    """Converts 3D SAT files into Revit GeometryObjects."""

    @staticmethod
    def import_sat_geometry(doc, sat_file_path):
        """
        Uses Revit API ShapeImporter to convert SAT file into GeometryObject array.
        """
        if not IS_REVIT or not doc or not sat_file_path:
            return None

        if hasattr(DB, "ShapeImporter"):
            try:
                importer = DB.ShapeImporter()
                geom_objects = importer.Convert(doc, sat_file_path)
                return geom_objects
            except Exception:
                pass
        return None
