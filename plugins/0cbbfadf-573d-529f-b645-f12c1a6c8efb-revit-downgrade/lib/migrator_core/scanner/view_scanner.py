# -*- coding: utf-8 -*-
"""
migrator_core.scanner.view_scanner
==================================
Scans Revit views, view templates, sheets, and viewports.
Guaranteed safe against native crashes by excluding ViewSheet from FilteredElementCollector
and restricting view inspection to graphical view classes.
"""

from ..compat import IS_REVIT, DB
from ..models import ViewRecord, SheetRecord

class ViewScanner(object):
    """Extracts Views and Sheets from active Revit document."""

    def __init__(self, doc):
        self.doc = doc

    def scan(self, progress_callback=None):
        view_records = []
        sheet_records = []
        if not IS_REVIT or not self.doc:
            return view_records, sheet_records

        # Pre-build titleblock map globally without querying FilteredElementCollector(doc, sheet.Id)
        # IMPORTANT: Passing ViewSheet.Id into FilteredElementCollector(doc, viewId) triggers native crash!
        sheet_tb_map = {}
        try:
            tb_col = DB.FilteredElementCollector(self.doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks).WhereElementIsNotElementType()
            for tb in tb_col:
                try:
                    if hasattr(tb, "OwnerViewId") and tb.OwnerViewId and tb.OwnerViewId != DB.ElementId.InvalidElementId:
                        s_id = tb.OwnerViewId.IntegerValue if hasattr(tb.OwnerViewId, "IntegerValue") else tb.OwnerViewId.Value
                        sheet_tb_map[s_id] = getattr(tb, "Name", "") or ""
                except Exception:
                    pass
        except Exception:
            pass

        # Collect views safely
        try:
            collector = DB.FilteredElementCollector(self.doc).OfClass(DB.View).WhereElementIsNotElementType()
            all_views = list(collector)
        except Exception:
            all_views = []

        total_views = len(all_views)
        count = 0

        # Valid view classes that can be migrated
        GRAPHIC_VIEW_CLASSES = (DB.ViewPlan, DB.ViewSection, DB.View3D, DB.ViewDrafting)

        for v in all_views:
            count += 1
            if not v or not getattr(v, "IsValidObject", True):
                continue

            try:
                # Exclude view templates
                if hasattr(v, "IsTemplate") and v.IsTemplate:
                    continue

                # Exclude internal / browser views
                vt = str(getattr(v, "ViewType", ""))
                if vt in ("Internal", "ProjectBrowser", "SystemBrowser", "Undefined", "CostReport", "LoadsReport", "PresureLossReport"):
                    continue

                v_id = v.Id.IntegerValue if hasattr(v.Id, "IntegerValue") else v.Id.Value
                v_name = getattr(v, "Name", "") or "View"

                if progress_callback and (count % 3 == 0 or count == total_views):
                    try:
                        progress_callback(count, total_views, u"[视图/图纸] {}".format(v_name))
                    except Exception:
                        pass

                # Special handling for ViewSheet
                if isinstance(v, DB.ViewSheet):
                    tb_name = sheet_tb_map.get(v_id, "")
                    vps = []
                    try:
                        for vp_id in v.GetAllViewports():
                            try:
                                vp = self.doc.GetElement(vp_id)
                                if vp and getattr(vp, "IsValidObject", True):
                                    box_center = vp.GetBoxCenter()
                                    sub_vid = vp.ViewId.IntegerValue if hasattr(vp.ViewId, "IntegerValue") else vp.ViewId.Value
                                    vps.append({
                                        "view_id": sub_vid,
                                        "center": [box_center.X, box_center.Y, box_center.Z]
                                    })
                            except Exception:
                                pass
                    except Exception:
                        pass

                    sheet_records.append(SheetRecord(
                        source_id=v_id,
                        unique_id=getattr(v, "UniqueId", ""),
                        sheet_number=getattr(v, "SheetNumber", "") or "",
                        sheet_name=v_name,
                        titleblock_family=tb_name,
                        viewports=vps
                    ))

                # Handling for regular graphical model views
                elif isinstance(v, GRAPHIC_VIEW_CLASSES):
                    scale_val = 100
                    try:
                        scale_val = v.Scale if hasattr(v, "Scale") else 100
                    except Exception:
                        scale_val = 100

                    detail_val = "Coarse"
                    try:
                        detail_val = str(v.DetailLevel) if hasattr(v, "DetailLevel") else "Coarse"
                    except Exception:
                        detail_val = "Coarse"

                    disp_val = "Coordination"
                    try:
                        disp_val = str(v.Discipline) if hasattr(v, "Discipline") else "Coordination"
                    except Exception:
                        disp_val = "Coordination"

                    lvl_id = None
                    try:
                        if hasattr(v, "GenLevel") and v.GenLevel:
                            lvl_id = v.GenLevel.Id.IntegerValue if hasattr(v.GenLevel.Id, "IntegerValue") else v.GenLevel.Id.Value
                    except Exception:
                        lvl_id = None

                    crop_box = None
                    try:
                        if hasattr(v, "CropBoxActive") and v.CropBoxActive and hasattr(v, "CropBox"):
                            cb = v.CropBox
                            if cb and cb.Min and cb.Max:
                                crop_box = {
                                    "min": [cb.Min.X, cb.Min.Y, cb.Min.Z],
                                    "max": [cb.Max.X, cb.Max.Y, cb.Max.Z]
                                }
                    except Exception:
                        crop_box = None

                    view_records.append(ViewRecord(
                        source_id=v_id,
                        unique_id=getattr(v, "UniqueId", ""),
                        name=v_name,
                        view_type=vt,
                        scale=scale_val,
                        detail_level=detail_val,
                        discipline=disp_val,
                        crop_box=crop_box,
                        associated_level_id=lvl_id
                    ))

            except Exception:
                continue

        return view_records, sheet_records
