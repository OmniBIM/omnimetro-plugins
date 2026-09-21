# -*- coding: utf-8 -*-
"""
migrator_core.models.family_record
==================================
Family definition and recipe models for loadable, system, and fallback families.
"""

class FamilyTypeRecord(object):
    """Encapsulates a single Family Type with its name and parameter values."""
    def __init__(self, name="", type_id=None, values=None):
        self.name = name
        self.type_id = type_id
        self.values = values or {}

    def to_dict(self):
        return {
            "name": self.name,
            "type_id": self.type_id,
            "values": self.values
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data.get("name", ""),
            type_id=data.get("type_id"),
            values=data.get("values", {})
        )

class FamilyParameterDefinition(object):
    """Encapsulates a parameter definition inside a family."""
    def __init__(self, name="", storage_type="String", is_instance=False, formula=None, is_shared=False, guid=None):
        self.name = name
        self.storage_type = storage_type
        self.is_instance = is_instance
        self.formula = formula
        self.is_shared = is_shared
        self.guid = guid

    def to_dict(self):
        return {
            "name": self.name,
            "storage_type": self.storage_type,
            "is_instance": self.is_instance,
            "formula": self.formula,
            "is_shared": self.is_shared,
            "guid": self.guid
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data.get("name", ""),
            storage_type=data.get("storage_type", "String"),
            is_instance=data.get("is_instance", False),
            formula=data.get("formula"),
            is_shared=data.get("is_shared", False),
            guid=data.get("guid")
        )

class FamilyRecord(object):
    """Complete representation of a Family Recipe for reconstruction."""
    def __init__(
        self,
        family_id=None,
        family_name="",
        category_name="",
        category_id=None,
        is_loadable=True,
        is_in_place=False,
        template_category="",
        parameters=None,
        types=None,
        forms=None,
        reference_planes=None,
        nested_families=None,
        geometry_asset_id=None,
        preview_asset_id=None
    ):
        self.family_id = family_id
        self.family_name = family_name
        self.category_name = category_name
        self.category_id = category_id
        self.is_loadable = is_loadable
        self.is_in_place = is_in_place
        self.template_category = template_category or category_name
        self.parameters = parameters or []
        self.types = types or []
        self.forms = forms or []
        self.reference_planes = reference_planes or []
        self.nested_families = nested_families or []
        self.geometry_asset_id = geometry_asset_id
        self.preview_asset_id = preview_asset_id

    def to_dict(self):
        return {
            "family_id": self.family_id,
            "family_name": self.family_name,
            "category_name": self.category_name,
            "category_id": self.category_id,
            "is_loadable": self.is_loadable,
            "is_in_place": self.is_in_place,
            "template_category": self.template_category,
            "parameters": [p.to_dict() for p in self.parameters],
            "types": [t.to_dict() for t in self.types],
            "forms": self.forms,
            "reference_planes": self.reference_planes,
            "nested_families": self.nested_families,
            "geometry_asset_id": self.geometry_asset_id,
            "preview_asset_id": self.preview_asset_id
        }

    @classmethod
    def from_dict(cls, data):
        params = [FamilyParameterDefinition.from_dict(p) for p in data.get("parameters", [])]
        types = [FamilyTypeRecord.from_dict(t) for t in data.get("types", [])]
        return cls(
            family_id=data.get("family_id"),
            family_name=data.get("family_name", ""),
            category_name=data.get("category_name", ""),
            category_id=data.get("category_id"),
            is_loadable=data.get("is_loadable", True),
            is_in_place=data.get("is_in_place", False),
            template_category=data.get("template_category", ""),
            parameters=params,
            types=types,
            forms=data.get("forms", []),
            reference_planes=data.get("reference_planes", []),
            nested_families=data.get("nested_families", []),
            geometry_asset_id=data.get("geometry_asset_id"),
            preview_asset_id=data.get("preview_asset_id")
        )
