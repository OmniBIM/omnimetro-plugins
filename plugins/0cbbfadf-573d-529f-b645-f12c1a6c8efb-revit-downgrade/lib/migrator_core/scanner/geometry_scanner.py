# -*- coding: utf-8 -*-
"""
migrator_core.scanner.geometry_scanner
======================================
Extracts bounding boxes, geometric solids, volume, and surface area from Revit elements.
"""

from ..compat import IS_REVIT, DB

SAFE_BBOX_CLASSES = set([
    "FamilyInstance",
    "Wall", "Floor", "Ceiling", "RoofBase", "FootPrintRoof", "ExtrusionRoof",
    "Pipe", "Duct", "CableTray", "Conduit", "FlexPipe", "FlexDuct",
    "DirectShape", "ImportInstance", "Part",
    "Stairs", "Railing", "Toposolid", "TopographySurface",
    "ModelLine", "ModelArc", "ModelEllipse", "ModelHermiteSpline", "ModelNurbSpline"
])

class GeometryScanner(object):
    """Inspects geometric representations and metrics of Revit elements."""

    @staticmethod
    def get_bounding_box(element):
        """Returns [min_x, min_y, min_z], [max_x, max_y, max_z]."""
        if not IS_REVIT or not element:
            return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        try:
            el_class = element.GetType().Name
            if el_class not in SAFE_BBOX_CLASSES:
                return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            if hasattr(element, "get_BoundingBox"):
                bbox = element.get_BoundingBox(None)
                if bbox and bbox.Min and bbox.Max:
                    return [bbox.Min.X, bbox.Min.Y, bbox.Min.Z], [bbox.Max.X, bbox.Max.Y, bbox.Max.Z]
        except Exception:
            pass
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]

    @staticmethod
    def calculate_solid_metrics(element):
        """Computes total volume (cu ft) and surface area (sq ft) of element solids."""
        if not IS_REVIT or not element:
            return 0.0, 0.0
        total_vol = 0.0
        total_area = 0.0
        try:
            opt = DB.Options()
            opt.DetailLevel = DB.ViewDetailLevel.Fine
            opt.ComputeReferences = False
            geom = element.get_Geometry(opt)
            if geom:
                for obj in geom:
                    if isinstance(obj, DB.Solid) and obj.Volume > 1e-6:
                        total_vol += obj.Volume
                        total_area += obj.SurfaceArea
                    elif isinstance(obj, DB.GeometryInstance):
                        inst_geom = obj.GetInstanceGeometry()
                        if inst_geom:
                            for inst_obj in inst_geom:
                                if isinstance(inst_obj, DB.Solid) and inst_obj.Volume > 1e-6:
                                    total_vol += inst_obj.Volume
                                    total_area += inst_obj.SurfaceArea
        except Exception:
            pass
        return total_vol, total_area
