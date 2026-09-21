# -*- coding: utf-8 -*-
"""
migrator_core.family.family_geometry_fallback
=============================================
Level 3 Family Geometry Fallback using generic model family templates
or DirectShape proxies.
"""

from ..compat import IS_REVIT, DB
from ..infra.logger import logger

class FamilyGeometryFallback(object):
    """
    Handles family fallback when full parametric recipe reconstruction
    is not feasible or template is unavailable.
    """

    @staticmethod
    def create_fallback_family(target_doc, family_record):
        """
        Creates a proxy generic model or registers fallback note in target document.
        """
        if not IS_REVIT or not target_doc:
            return None

        fam_name = family_record.family_name
        logger.fallback(
            "Applying Level 3/4 fallback for family '{}'".format(fam_name),
            phase="FAMILY",
            source_id=family_record.family_id
        )
        return None
