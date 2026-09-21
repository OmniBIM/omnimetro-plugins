# -*- coding: utf-8 -*-
"""
migrator_core.models.parameter_record
=====================================
Parameter representations for storing and reconstructing Revit element parameters.
"""

from ..constants import StorageType

class ParameterRecord(object):
    """Encapsulates a single parameter extracted from a Revit element."""

    def __init__(
        self,
        name="",
        storage_type=StorageType.NONE,
        value_string=None,
        value_double=None,
        value_int=None,
        value_element_source_id=None,
        display_value="",
        unit_type="",
        is_instance=True,
        is_shared=False,
        shared_guid=None,
        formula=None,
        read_only=False,
        param_id=None,
        definition_name=""
    ):
        self.name = name
        self.storage_type = storage_type
        self.value_string = value_string
        self.value_double = value_double
        self.value_int = value_int
        self.value_element_source_id = value_element_source_id
        self.display_value = display_value
        self.unit_type = unit_type
        self.is_instance = is_instance
        self.is_shared = is_shared
        self.shared_guid = shared_guid
        self.formula = formula
        self.read_only = read_only
        self.param_id = param_id
        self.definition_name = definition_name or name

    def get_raw_value(self):
        if self.storage_type == StorageType.STRING:
            return self.value_string
        elif self.storage_type == StorageType.DOUBLE:
            return self.value_double
        elif self.storage_type == StorageType.INTEGER:
            return self.value_int
        elif self.storage_type == StorageType.ELEMENT_ID:
            return self.value_element_source_id
        return None

    def to_dict(self):
        return {
            "name": self.name,
            "param_id": self.param_id,
            "definition_name": self.definition_name,
            "storage_type": self.storage_type,
            "value_string": self.value_string,
            "value_double": self.value_double,
            "value_int": self.value_int,
            "value_element_source_id": self.value_element_source_id,
            "display_value": self.display_value,
            "unit_type": self.unit_type,
            "is_instance": self.is_instance,
            "is_shared": self.is_shared,
            "shared_guid": self.shared_guid,
            "formula": self.formula,
            "read_only": self.read_only
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data.get("name", ""),
            storage_type=data.get("storage_type", StorageType.NONE),
            value_string=data.get("value_string"),
            value_double=data.get("value_double"),
            value_int=data.get("value_int"),
            value_element_source_id=data.get("value_element_source_id"),
            display_value=data.get("display_value", ""),
            unit_type=data.get("unit_type", ""),
            is_instance=data.get("is_instance", True),
            is_shared=data.get("is_shared", False),
            shared_guid=data.get("shared_guid"),
            formula=data.get("formula"),
            read_only=data.get("read_only", False),
            param_id=data.get("param_id"),
            definition_name=data.get("definition_name", "")
        )
