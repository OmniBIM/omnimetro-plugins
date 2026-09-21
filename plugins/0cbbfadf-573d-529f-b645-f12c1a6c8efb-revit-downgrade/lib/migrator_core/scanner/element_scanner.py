# -*- coding: utf-8 -*-
"""
migrator_core.scanner.element_scanner
=====================================
Scans all BIM model instances, extracting locations, geometries,
parameters, host relationships, and datums (Levels & Grids).
"""

from ..compat import IS_REVIT, DB, RevitVersionAdapter
from ..models import ElementRecord, ParameterRecord, LevelRecord, GridRecord
from .geometry_scanner import GeometryScanner
from ..constants import MigrationLevel, ActionStatus

class ElementScanner(object):
    """Iterates through active Revit document elements and produces ElementRecords."""

    def __init__(self, doc):
        self.doc = doc
        self.adapter = RevitVersionAdapter(doc)

    def scan_datums(self, progress_callback=None):
        """Extracts Levels and Grids."""
        levels = []
        grids = []
        if not IS_REVIT or not self.doc:
            return levels, grids

        # Levels
        lvl_col = DB.FilteredElementCollector(self.doc).OfClass(DB.Level)
        lvl_count = lvl_col.GetElementCount() if hasattr(lvl_col, "GetElementCount") else 10
        cur_l = 0
        for lvl in lvl_col:
            cur_l += 1
            try:
                l_id = lvl.Id.IntegerValue if hasattr(lvl.Id, "IntegerValue") else lvl.Id.Value
                if progress_callback:
                    progress_callback(cur_l, lvl_count, u"[标高] {}".format(lvl.Name or ""))
                levels.append(LevelRecord(
                    source_id=l_id,
                    unique_id=lvl.UniqueId,
                    name=lvl.Name,
                    elevation=lvl.Elevation
                ))
            except Exception:
                continue

        # Grids
        grid_col = DB.FilteredElementCollector(self.doc).OfClass(DB.Grid)
        grid_count = grid_col.GetElementCount() if hasattr(grid_col, "GetElementCount") else 10
        cur_g = 0
        for g in grid_col:
            cur_g += 1
            try:
                g_id = g.Id.IntegerValue if hasattr(g.Id, "IntegerValue") else g.Id.Value
                if progress_callback:
                    progress_callback(cur_g, grid_count, u"[轴网] {}".format(g.Name or ""))
                curve = g.Curve
                pts = []
                c_type = "Line"
                if isinstance(curve, DB.Line):
                    c_type = "Line"
                    p0 = curve.GetEndPoint(0)
                    p1 = curve.GetEndPoint(1)
                    pts = [[p0.X, p0.Y, p0.Z], [p1.X, p1.Y, p1.Z]]
                elif isinstance(curve, DB.Arc):
                    c_type = "Arc"
                    p0 = curve.GetEndPoint(0)
                    p1 = curve.GetEndPoint(1)
                    pm = curve.Evaluate(0.5, True)
                    pts = [[p0.X, p0.Y, p0.Z], [p1.X, p1.Y, p1.Z], [pm.X, pm.Y, pm.Z]]

                grids.append(GridRecord(
                    source_id=g_id,
                    unique_id=g.UniqueId,
                    name=g.Name,
                    curve_type=c_type,
                    points=pts
                ))
            except Exception:
                continue

        return levels, grids

    def scan_elements(self, progress_callback=None):
        """Extracts all physical model elements."""
        elements = []
        if not IS_REVIT or not self.doc:
            return elements

        collector = DB.FilteredElementCollector(self.doc).WhereElementIsNotElementType()
        if hasattr(collector, "WhereElementIsViewIndependent"):
            try:
                collector = collector.WhereElementIsViewIndependent()
            except Exception:
                pass

        # Exclude non-model categories
        excluded_cats = [
            DB.BuiltInCategory.OST_Views,
            DB.BuiltInCategory.OST_Materials,
            DB.BuiltInCategory.OST_Levels,
            DB.BuiltInCategory.OST_Grids,
            DB.BuiltInCategory.OST_Cameras,
            DB.BuiltInCategory.OST_ProjectBasePoint,
            DB.BuiltInCategory.OST_SharedBasePoint,
            DB.BuiltInCategory.OST_ProjectInformation,
            DB.BuiltInCategory.OST_Sheets,
            DB.BuiltInCategory.OST_Schedules,
            DB.BuiltInCategory.OST_PipingSystem,
            DB.BuiltInCategory.OST_DuctSystem,
            DB.BuiltInCategory.OST_ElectricalCircuit,
            DB.BuiltInCategory.OST_RvtLinks,
        ]
        excluded_cat_ids = set()
        for c in excluded_cats:
            try:
                excluded_cat_ids.add(int(c))
            except Exception:
                pass

        # Classes that are guaranteed physical and safe to query for get_BoundingBox(None)
        SAFE_BBOX_CLASSES = set([
            "FamilyInstance",
            "Wall", "Floor", "Ceiling", "RoofBase", "FootPrintRoof", "ExtrusionRoof",
            "Pipe", "Duct", "CableTray", "Conduit", "FlexPipe", "FlexDuct",
            "DirectShape", "ImportInstance", "Part",
            "Stairs", "Railing", "Toposolid", "TopographySurface",
            "ModelLine", "ModelArc", "ModelEllipse", "ModelHermiteSpline", "ModelNurbSpline"
        ])

        # Classes that are logical/system/annotation/datum objects and must NOT be queried for geometry
        SKIPPED_CLASSES = set([
            "MEPSystem", "PipingSystem", "DuctSystem", "ElectricalSystem",
            "MechanicalSystem", "ElectricalCircuit", "RoutingPreferenceRule",
            "RevitLinkInstance", "RevitLinkType", "ExternalFileReference",
            "Sketch", "SketchPlane", "SketchBase",
            "View", "View3D", "ViewPlan", "ViewSection", "ViewDrafting", "ViewSchedule", "ViewSheet",
            "DatumPlane", "Level", "Grid", "ReferencePlane", "ReferencePoint",
            "Group", "GroupType", "AssemblyType",
            "Material", "GraphicsStyle", "LinePatternElement", "FillPatternElement",
            "BasePoint", "ProjectLocation", "ProjectInfo", "PrintSetup",
            "Phase", "DesignOption", "ParameterFilterElement", "FilterElement",
            "SpatialElementCalculationPoint", "SpatialElementBoundarySubface",
            "AnalyticalMember", "AnalyticalPanel", "AnalyticalNode", "AnalyticalModel",
            "StructureSettings", "WorksetSettings",
            "ArrowEditor", "Control", "BoundarySegment",
            "IndependentTag", "RoomTag", "SpaceTag", "AreaTag",
        ])

        total_est = collector.GetElementCount() if hasattr(collector, "GetElementCount") else 1000
        count = 0

        for elem in collector:
            count += 1
            if not elem:
                continue
            if hasattr(elem, "IsValidObject") and not elem.IsValidObject:
                continue

            try:
                el_class = elem.GetType().Name
            except Exception:
                continue

            if el_class in SKIPPED_CLASSES:
                continue

            try:
                cat = elem.Category
                if not cat:
                    continue
            except Exception:
                continue

            # Exclude non-model category types (Annotations, Analytical, Internal, etc.)
            try:
                if hasattr(cat, "CategoryType") and cat.CategoryType != DB.CategoryType.Model:
                    continue
            except Exception:
                continue

            # Exclude specific non-physical categories by integer ID
            try:
                c_id_val = cat.Id.Value if hasattr(cat.Id, "Value") else cat.Id.IntegerValue
                if c_id_val in excluded_cat_ids:
                    continue
            except Exception:
                continue

            # Safely verify location or geometry
            loc = None
            try:
                loc = elem.Location
            except Exception:
                loc = None

            bmin = [0.0, 0.0, 0.0]
            bmax = [0.0, 0.0, 0.0]
            has_geom = False
            if loc is not None:
                has_geom = True

            # Safely query bounding box ONLY for recognized physical 3D elements
            # NEVER query get_BoundingBox(None) on SpatialElement (Room/Space/Area) - causes PlanTopologyUtil native crash!
            if el_class in SAFE_BBOX_CLASSES:
                try:
                    if hasattr(elem, "get_BoundingBox"):
                        bbox = elem.get_BoundingBox(None)
                        if bbox and bbox.Min and bbox.Max:
                            bmin = [bbox.Min.X, bbox.Min.Y, bbox.Min.Z]
                            bmax = [bbox.Max.X, bbox.Max.Y, bbox.Max.Z]
                            has_geom = True
                except Exception:
                    pass

            if not has_geom:
                continue

            if progress_callback and (count % 5 == 0 or count == total_est):
                try:
                    c_name = getattr(cat, "Name", "Element") or "Element"
                    e_name = getattr(elem, "Name", "") or ""
                    e_id = elem.Id.Value if hasattr(elem.Id, "Value") else elem.Id.IntegerValue
                    item_desc = u"[{}] {} (Id: {})".format(c_name, e_name, e_id)
                except Exception:
                    item_desc = u"[Element] Id: {}".format(count)
                progress_callback(count, total_est, item_desc)

            try:
                el_id = elem.Id.Value if hasattr(elem.Id, "Value") else elem.Id.IntegerValue
                cat_name = getattr(cat, "Name", "Generic Models") or "Generic Models"
                cat_id = cat.Id.Value if hasattr(cat.Id, "Value") else cat.Id.IntegerValue

                # Type & Family info
                type_id_int = -1
                type_name = ""
                fam_name = ""
                try:
                    type_id = elem.GetTypeId()
                    if type_id and type_id != DB.ElementId.InvalidElementId:
                        type_id_int = type_id.Value if hasattr(type_id, "Value") else type_id.IntegerValue
                        type_elem = self.doc.GetElement(type_id)
                        if type_elem:
                            type_name = getattr(type_elem, "Name", "") or ""
                            if hasattr(type_elem, "FamilyName"):
                                fam_name = type_elem.FamilyName or ""
                            elif hasattr(type_elem, "Family") and type_elem.Family:
                                fam_name = type_elem.Family.Name or ""
                except Exception:
                    pass

                if not fam_name:
                    fam_name = type_name or cat_name

                # Level info
                level_id_int = None
                level_name = ""
                try:
                    if hasattr(elem, "LevelId") and elem.LevelId != DB.ElementId.InvalidElementId:
                        level_id_int = elem.LevelId.Value if hasattr(elem.LevelId, "Value") else elem.LevelId.IntegerValue
                        lvl_elem = self.doc.GetElement(elem.LevelId)
                        if lvl_elem:
                            level_name = getattr(lvl_elem, "Name", "") or ""
                except Exception:
                    pass

                # Host info
                host_uid = None
                try:
                    if hasattr(elem, "Host") and elem.Host:
                        host_uid = elem.Host.UniqueId
                except Exception:
                    pass

                # Location data
                loc_type = "None"
                loc_data = {}
                try:
                    if isinstance(loc, DB.LocationPoint):
                        loc_type = "Point"
                        pt = loc.Point
                        rot = getattr(loc, "Rotation", 0.0)
                        loc_data = {
                            "pt": [pt.X, pt.Y, pt.Z],
                            "rotation": rot
                        }
                        if hasattr(elem, "FacingOrientation"):
                            fo = elem.FacingOrientation
                            loc_data["facing"] = [fo.X, fo.Y, fo.Z]
                        if hasattr(elem, "HandOrientation"):
                            ho = elem.HandOrientation
                            loc_data["hand"] = [ho.X, ho.Y, ho.Z]

                    elif isinstance(loc, DB.LocationCurve):
                        loc_type = "Curve"
                        c = loc.Curve
                        if isinstance(c, DB.Line):
                            p0 = c.GetEndPoint(0)
                            p1 = c.GetEndPoint(1)
                            loc_data = {
                                "curve_type": "Line",
                                "start": [p0.X, p0.Y, p0.Z],
                                "end": [p1.X, p1.Y, p1.Z]
                            }
                        elif isinstance(c, DB.Arc):
                            p0 = c.GetEndPoint(0)
                            p1 = c.GetEndPoint(1)
                            pm = c.Evaluate(0.5, True)
                            loc_data = {
                                "curve_type": "Arc",
                                "start": [p0.X, p0.Y, p0.Z],
                                "end": [p1.X, p1.Y, p1.Z],
                                "mid": [pm.X, pm.Y, pm.Z]
                            }
                except Exception:
                    pass

                # Parameters
                param_records = []
                try:
                    for p in elem.Parameters:
                        try:
                            if not p.Definition:
                                continue
                            p_name = p.Definition.Name
                            st = self.adapter.get_parameter_storage_type(p)
                            val_str = p.AsString() if st == "String" else None
                            val_dbl = p.AsDouble() if st == "Double" else None
                            val_int = p.AsInteger() if st == "Integer" else None
                            val_eid = None
                            if st == "ElementId":
                                eid = p.AsElementId()
                                if eid:
                                    val_eid = eid.Value if hasattr(eid, "Value") else eid.IntegerValue

                            is_shared = getattr(p, "IsShared", False)
                            guid_str = None
                            if is_shared and hasattr(p, "GUID"):
                                try:
                                    guid_str = str(p.GUID)
                                except Exception:
                                    guid_str = None

                            disp_val = ""
                            try:
                                disp_val = p.AsValueString() or ""
                            except Exception:
                                disp_val = ""

                            param_records.append(ParameterRecord(
                                name=p_name,
                                storage_type=st,
                                value_string=val_str,
                                value_double=val_dbl,
                                value_int=val_int,
                                value_element_source_id=val_eid,
                                display_value=disp_val,
                                is_instance=not is_shared,
                                is_shared=is_shared,
                                shared_guid=guid_str,
                                read_only=p.IsReadOnly
                            ))
                        except Exception:
                            continue
                except Exception:
                    pass

                # Extra data for walls, pipes, ducts
                extra = {}
                try:
                    if isinstance(elem, DB.Wall):
                        extra["is_flipped"] = getattr(elem, "Flipped", False)
                        extra["wall_type_name"] = type_name
                        h_param = elem.get_Parameter(DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM)
                        if h_param:
                            extra["height"] = h_param.AsDouble()
                    elif hasattr(DB, "Plumbing") and isinstance(elem, DB.Plumbing.Pipe):
                        dp = elem.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
                        if dp:
                            extra["diameter"] = dp.AsDouble()
                    elif hasattr(DB, "Mechanical") and isinstance(elem, DB.Mechanical.Duct):
                        wp = elem.get_Parameter(DB.BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
                        hp = elem.get_Parameter(DB.BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
                        if wp:
                            extra["width"] = wp.AsDouble()
                        if hp:
                            extra["height"] = hp.AsDouble()
                except Exception:
                    pass

                elements.append(ElementRecord(
                    source_element_id=el_id,
                    source_unique_id=elem.UniqueId,
                    category_id=cat_id,
                    category_name=cat_name,
                    element_class=el_class,
                    element_type_id=type_id_int,
                    element_type_name=type_name,
                    family_name=fam_name,
                    level_id=level_id_int,
                    level_name=level_name,
                    location_type=loc_type,
                    location_data=loc_data,
                    bbox_min=bmin,
                    bbox_max=bmax,
                    host_unique_id=host_uid,
                    parameters=param_records,
                    extra_data=extra
                ))

            except Exception:
                continue

        return elements
