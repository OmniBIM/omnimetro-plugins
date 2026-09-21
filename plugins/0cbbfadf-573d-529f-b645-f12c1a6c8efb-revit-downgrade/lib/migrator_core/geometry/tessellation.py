# -*- coding: utf-8 -*-
"""
migrator_core.geometry.tessellation
===================================
Constructs mesh geometry via TessellatedShapeBuilder.
"""

from ..compat import IS_REVIT, DB

class TessellationHelper(object):

    @staticmethod
    def build_box_mesh(bbox_min, bbox_max):
        """Builds a closed 6-sided box mesh from bounding coordinates."""
        if not IS_REVIT:
            return None

        builder = DB.TessellatedShapeBuilder()
        builder.OpenConnectedFaceSet(True)

        p0 = DB.XYZ(bbox_min[0], bbox_min[1], bbox_min[2])
        p1 = DB.XYZ(bbox_max[0], bbox_min[1], bbox_min[2])
        p2 = DB.XYZ(bbox_max[0], bbox_max[1], bbox_min[2])
        p3 = DB.XYZ(bbox_min[0], bbox_max[1], bbox_min[2])
        p4 = DB.XYZ(bbox_min[0], bbox_min[1], bbox_max[2])
        p5 = DB.XYZ(bbox_max[0], bbox_min[1], bbox_max[2])
        p6 = DB.XYZ(bbox_max[0], bbox_max[1], bbox_max[2])
        p7 = DB.XYZ(bbox_min[0], bbox_max[1], bbox_max[2])

        faces = [
            [p0, p1, p2, p3],
            [p4, p7, p6, p5],
            [p0, p4, p5, p1],
            [p1, p5, p6, p2],
            [p2, p6, p7, p3],
            [p3, p7, p4, p0]
        ]

        for f in faces:
            builder.AddFace(DB.TessellatedFace(f, DB.ElementId.InvalidElementId))

        builder.CloseConnectedFaceSet()
        res = builder.Build(
            DB.TessellatedShapeBuilderTarget.Mesh,
            DB.TessellatedShapeBuilderFallback.Salvage,
            DB.ElementId.InvalidElementId
        )
        if res.AreGeometricObjectsValid():
            return res.GetGeometricalObjects()
        return None
