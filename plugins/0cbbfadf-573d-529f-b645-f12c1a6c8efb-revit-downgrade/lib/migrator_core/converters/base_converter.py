# -*- coding: utf-8 -*-
"""
migrator_core.converters.base_converter
=======================================
Base interface definition for all element converters.
"""

class BaseConverter(object):
    """
    Standard lifecycle for converting a neutral ElementRecord
    into a Revit 2020 native or fallback element.
    """

    def analyze(self, record, context):
        """Pre-conversion analysis and checks."""
        pass

    def can_convert(self, record, context):
        """Returns True if this converter can handle the element record."""
        return False

    def convert(self, record, context):
        """
        Executes conversion.
        Returns target Revit Element or ElementId, or raises ElementConversionError.
        """
        raise NotImplementedError("Subclasses must implement convert()")

    def validate(self, record, target_element, context):
        """Post-creation validation (parameters, bounding box, location)."""
        pass
