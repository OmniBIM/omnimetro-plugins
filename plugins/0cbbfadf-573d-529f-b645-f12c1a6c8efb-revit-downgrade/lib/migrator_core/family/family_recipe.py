# -*- coding: utf-8 -*-
"""
migrator_core.family.family_recipe
==================================
Family recipe processing and serialization.
"""

import json
from ..models import FamilyRecord, FamilyTypeRecord, FamilyParameterDefinition

class FamilyRecipe(object):
    """Encapsulates the instructions and recipes needed to reconstruct a family in Revit 2020."""

    @staticmethod
    def from_record(family_record):
        return family_record.to_dict()

    @staticmethod
    def to_record(recipe_dict):
        return FamilyRecord.from_dict(recipe_dict)

    @staticmethod
    def to_json(family_record, indent=2):
        return json.dumps(family_record.to_dict(), indent=indent)

    @staticmethod
    def from_json(json_str):
        data = json.loads(json_str)
        return FamilyRecord.from_dict(data)
