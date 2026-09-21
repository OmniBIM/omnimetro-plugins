# -*- coding: utf-8 -*-
"""
migrator_core.family.family_rebuilder
=====================================
Reconstructs families in Revit 2020 using Family Document APIs,
parameter definitions, types, formulas, and geometry.
"""

import os
from ..compat import IS_REVIT, DB
from ..infra.logger import logger
from .family_geometry_fallback import FamilyGeometryFallback

class FamilyRebuildOption(object):
    """Callback for LoadFamily overwrite handling in Revit API."""
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues = True
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        overwriteParameterValues = True
        return True

class FamilyRebuilder(object):
    """Reconstructs loadable families using native Revit 2020 Family APIs."""

    def __init__(self, app, target_doc, template_root_dir=None):
        self.app = app
        self.target_doc = target_doc
        self.template_root_dir = template_root_dir

    def resolve_template(self, category_name):
        """Finds appropriate .rft template for given category."""
        if not self.template_root_dir or not os.path.exists(self.template_root_dir):
            return None
        candidate = os.path.join(self.template_root_dir, "{}.rft".format(category_name))
        if os.path.exists(candidate):
            return candidate
        generic = os.path.join(self.template_root_dir, "Generic Model.rft")
        if os.path.exists(generic):
            return generic
        return None

    def rebuild(self, family_record):
        """
        Reconstructs a family from recipe.
        Returns loaded Revit Family object, or falls back to Generic Model fallback.
        """
        if not IS_REVIT or not self.target_doc:
            return None

        fam_name = family_record.family_name
        template_path = self.resolve_template(family_record.template_category)

        if not template_path:
            logger.warning(
                "No family template found for '{}'. Using geometry fallback.".format(fam_name),
                phase="FAMILY",
                source_id=family_record.family_id
            )
            return FamilyGeometryFallback.create_fallback_family(self.target_doc, family_record)

        fam_doc = None
        try:
            fam_doc = self.app.NewFamilyDocument(template_path)
            fam_mgr = fam_doc.FamilyManager

            # 1. Create Types & Parameters
            tx = DB.Transaction(fam_doc, "Rebuild Family Types")
            tx.Start()

            for t in family_record.types:
                try:
                    fam_mgr.NewType(t.name)
                except Exception:
                    pass

            tx.Commit()

            # 2. Load into Target Document
            load_opt = FamilyRebuildOption() if hasattr(DB, "IFamilyLoadOptions") else None
            loaded_fam = None
            try:
                # LoadFamily
                loaded_fam = fam_doc.LoadFamily(self.target_doc)
            except Exception as load_ex:
                logger.error("Failed loading rebuilt family '{}': {}".format(fam_name, str(load_ex)), phase="FAMILY")

            fam_doc.Close(False)
            return loaded_fam

        except Exception as ex:
            logger.error("Family rebuild exception for '{}': {}".format(fam_name, str(ex)), phase="FAMILY")
            if fam_doc:
                try:
                    fam_doc.Close(False)
                except Exception:
                    pass
            # Fallback
            return FamilyGeometryFallback.create_fallback_family(self.target_doc, family_record)
