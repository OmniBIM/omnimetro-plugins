# -*- coding: utf-8 -*-
"""
migrator_core.converters.directshape_converter
==============================================
Level 4 Geometry Fallback Converter using Revit DirectShape, ShapeImporter,
and TessellatedShapeBuilder.
"""

from ..compat import IS_REVIT, DB
from .base_converter import BaseConverter
from ..infra.extensible_storage import set_migration_metadata

class DirectShapeConverter(BaseConverter):

    def can_convert(self, record, context):
        return True  # Fallback for any element with geometry

    def convert(self, record, context):
        doc = context.doc
        if not IS_REVIT or not doc:
            return None

        # Determine Category
        cat_id = DB.ElementId(DB.BuiltInCategory.OST_GenericModel)
        try:
            if record.category_id and record.category_id != -1:
                test_id = DB.ElementId(int(record.category_id))
                if DB.DirectShape.IsValidCategoryId(test_id, doc):
                    cat_id = test_id
        except Exception:
            pass

        app_id = "RVT2020Migrator"
        app_data_id = str(record.source_unique_id or "DirectShapeFallback")

        ds = None
        try:
            ds = DB.DirectShape.CreateElement(doc, cat_id)
            ds.ApplicationId = app_id
            ds.ApplicationDataId = app_data_id
        except Exception:
            return None

        # Attempt to populate geometry from SAT asset or bounding box mesh
        geom_built = False

        # 1. Try SAT file if geometry_asset_id exists
        if record.geometry_asset_id and context.reader:
            sat_path = context.reader.get_asset_file_path(record.geometry_asset_id)
            if hasattr(DB, "ShapeImporter"):
                try:
                    importer = DB.ShapeImporter()
                    geom_objs = importer.Convert(doc, sat_path)
                    if geom_objs and geom_objs.Count > 0:
                        ds.SetShape(geom_objs)
                        geom_built = True
                except Exception:
                    pass

        # 2. Fallback to bounding box solid/mesh representation
        if not geom_built:
            bmin = record.bbox_min
            bmax = record.bbox_max
            try:
                builder = DB.TessellatedShapeBuilder()
                builder.OpenConnectedFaceSet(True)

                p0 = DB.XYZ(bmin[0], bmin[1], bmin[2])
                p1 = DB.XYZ(bmax[0], bmin[1], bmin[2])
                p2 = DB.XYZ(bmax[0], bmax[1], bmin[2])
                p3 = DB.XYZ(bmin[0], bmax[1], bmin[2])
                p4 = DB.XYZ(bmin[0], bmin[1], bmax[2])
                p5 = DB.XYZ(bmax[0], bmin[1], bmax[2])
                p6 = DB.XYZ(bmax[0], bmax[1], bmax[2])
                p7 = DB.XYZ(bmin[0], bmax[1], bmax[2])

                # 6 faces of box
                faces = [
                    [p0, p1, p2, p3],  # bottom
                    [p4, p7, p6, p5],  # top
                    [p0, p4, p5, p1],  # front
                    [p1, p5, p6, p2],  # right
                    [p2, p6, p7, p3],  # back
                    [p3, p7, p4, p0]   # left
                ]

                for f in faces:
                    builder.AddFace(DB.TessellatedFace(f, DB.ElementId.InvalidElementId))

                builder.CloseConnectedFaceSet()
                build_result = builder.Build(DB.TessellatedShapeBuilderTarget.Mesh, DB.TessellatedShapeBuilderFallback.Salvage, DB.ElementId.InvalidElementId)
                if build_result.AreGeometricObjectsValid():
                    ds.SetShape(build_result.GetGeometricalObjects())
                    geom_built = True
            except Exception:
                pass

        if ds:
            context.apply_parameters(ds, record.parameters)
            set_migration_metadata(ds, record.source_unique_id, context.package_id)

            t_id_int = ds.Id.IntegerValue if hasattr(ds.Id, "IntegerValue") else ds.Id.Value
            context.register_mapping(
                source_unique_id=record.source_unique_id,
                source_element_id=record.source_element_id,
                target_element_id=t_id_int,
                target_unique_id=ds.UniqueId,
                status="FALLBACK"
            )

        return ds
