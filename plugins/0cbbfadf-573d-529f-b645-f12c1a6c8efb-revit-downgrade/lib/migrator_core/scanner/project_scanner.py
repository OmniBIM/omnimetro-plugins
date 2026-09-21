# -*- coding: utf-8 -*-
"""
migrator_core.scanner.project_scanner
=====================================
Scans Revit ProjectInfo, coordinate points, phases, worksets, and units.
"""

from ..compat import IS_REVIT, DB
from ..models import ProjectRecord

class ProjectScanner(object):
    """Extracts project-level metadata from active Revit document."""

    def __init__(self, doc):
        self.doc = doc

    def scan(self):
        if not IS_REVIT or not self.doc:
            return ProjectRecord()

        title = self.doc.Title or "Unnamed_Project"
        path = self.doc.PathName or ""
        version = "2027"
        try:
            version = self.doc.Application.VersionNumber
        except Exception:
            pass

        # Coordinate base points
        base_pt = [0.0, 0.0, 0.0]
        survey_pt = [0.0, 0.0, 0.0]
        true_north = 0.0

        try:
            col = DB.FilteredElementCollector(self.doc).OfCategory(DB.BuiltInCategory.OST_ProjectBasePoint)
            bp_elem = col.FirstElement()
            if bp_elem:
                ew = bp_elem.get_Parameter(DB.BuiltInParameter.BASEPOINT_EASTWEST_PARAM).AsDouble()
                ns = bp_elem.get_Parameter(DB.BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM).AsDouble()
                elev = bp_elem.get_Parameter(DB.BuiltInParameter.BASEPOINT_ELEVATION_PARAM).AsDouble()
                base_pt = [ew, ns, elev]
                tn_param = bp_elem.get_Parameter(DB.BuiltInParameter.BASEPOINT_ANGLETON_PARAM)
                if tn_param:
                    true_north = tn_param.AsDouble()
        except Exception:
            pass

        try:
            col = DB.FilteredElementCollector(self.doc).OfCategory(DB.BuiltInCategory.OST_SharedBasePoint)
            sp_elem = col.FirstElement()
            if sp_elem:
                ew = sp_elem.get_Parameter(DB.BuiltInParameter.BASEPOINT_EASTWEST_PARAM).AsDouble()
                ns = sp_elem.get_Parameter(DB.BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM).AsDouble()
                elev = sp_elem.get_Parameter(DB.BuiltInParameter.BASEPOINT_ELEVATION_PARAM).AsDouble()
                survey_pt = [ew, ns, elev]
        except Exception:
            pass

        # Phases
        phases = []
        try:
            for p in self.doc.Phases:
                phases.append({"id": p.Id.IntegerValue if hasattr(p.Id, "IntegerValue") else p.Id.Value, "name": p.Name})
        except Exception:
            pass

        # Worksets
        worksets = []
        try:
            if self.doc.IsWorkshared:
                col = DB.FilteredWorksetCollector(self.doc).OfKind(DB.WorksetKind.UserWorkset)
                for w in col:
                    worksets.append({"id": w.Id.IntegerValue, "name": w.Name})
        except Exception:
            pass

        # Revit Links (Preserve link metadata without converting linked models)
        links = []
        try:
            link_col = DB.FilteredElementCollector(self.doc).OfClass(DB.RevitLinkInstance)
            for link_inst in link_col:
                try:
                    link_id = link_inst.Id.Value if hasattr(link_inst.Id, "Value") else link_inst.Id.IntegerValue
                    link_name = getattr(link_inst, "Name", "") or ""
                    link_type_id = link_inst.GetTypeId()
                    link_type = self.doc.GetElement(link_type_id) if link_type_id else None
                    link_path = ""
                    if link_type:
                        try:
                            ext_ref = link_type.GetExternalFileReference()
                            if ext_ref:
                                model_path = ext_ref.GetPath()
                                if model_path and hasattr(DB, "ModelPathUtils"):
                                    link_path = DB.ModelPathUtils.ConvertModelPathToUserVisiblePath(model_path)
                        except Exception:
                            pass
                        if not link_path and hasattr(link_type, "Name"):
                            link_path = getattr(link_type, "Name", "") or ""

                    tf_data = {}
                    try:
                        tf = link_inst.GetTotalTransform() if hasattr(link_inst, "GetTotalTransform") else None
                        if tf:
                            origin = tf.Origin
                            basis_x = tf.BasisX
                            basis_y = tf.BasisY
                            basis_z = tf.BasisZ
                            tf_data = {
                                "origin": [origin.X, origin.Y, origin.Z],
                                "basis_x": [basis_x.X, basis_x.Y, basis_x.Z],
                                "basis_y": [basis_y.X, basis_y.Y, basis_y.Z],
                                "basis_z": [basis_z.X, basis_z.Y, basis_z.Z],
                                "scale": tf.Scale if hasattr(tf, "Scale") else 1.0
                            }
                    except Exception:
                        pass

                    links.append({
                        "source_id": link_id,
                        "link_name": link_name,
                        "path": link_path,
                        "transform": tf_data
                    })
                except Exception:
                    continue
        except Exception:
            pass

        return ProjectRecord(
            title=title,
            file_path=path,
            revit_version=version,
            units="revit_internal",
            internal_origin=[0.0, 0.0, 0.0],
            project_base_point=base_pt,
            survey_point=survey_pt,
            true_north=true_north,
            phases=phases,
            worksets=worksets,
            links=links
        )
