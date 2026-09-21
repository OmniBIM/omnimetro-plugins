# -*- coding: utf-8 -*-
"""
migrator_core.converters.registry
=================================
Central registry dispatching records to specialized converters.
"""

class ConverterRegistry(object):
    """
    Registry mapping categories and element types to BaseConverter implementations.
    """
    _converters = {}
    _class_converters = {}
    _fallback_converter = None

    @classmethod
    def register(cls, category_name, converter_cls):
        cls._converters[category_name] = converter_cls

    @classmethod
    def register_class(cls, class_name, converter_cls):
        cls._class_converters[class_name] = converter_cls

    @classmethod
    def register_fallback(cls, converter_cls):
        cls._fallback_converter = converter_cls

    @classmethod
    def get_converter(cls, record, context=None):
        el_class = getattr(record, "element_class", "") or ""
        cat = getattr(record, "category_name", "") or ""
        fam_name = getattr(record, "family_name", "") or ""

        # 1. By class name first (.NET class is language-independent)
        if el_class in cls._class_converters:
            return cls._class_converters[el_class]()

        # 2. By category name (supports both English and Chinese)
        if cat in cls._converters:
            conv_cls = cls._converters[cat]
            return conv_cls()

        # 3. If it is a loadable family instance or has family_name, dispatch to FamilyInstanceConverter
        if (el_class == "FamilyInstance" or fam_name) and "InPlace" not in el_class and "InPlace" not in fam_name:
            from .family_instance_converter import FamilyInstanceConverter
            return FamilyInstanceConverter()

        # 4. Fallback to direct shape
        if cls._fallback_converter:
            return cls._fallback_converter()

        return None
