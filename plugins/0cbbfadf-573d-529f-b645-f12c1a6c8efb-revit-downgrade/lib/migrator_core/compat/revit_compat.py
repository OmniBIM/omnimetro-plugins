# -*- coding: utf-8 -*-
"""
migrator_core.compat.revit_compat
=================================
Compatibility adapter bridging Revit 2027 (.NET 10 / ForgeTypeId)
and Revit 2020 (.NET 4.8 / DisplayUnitType / ParameterType).
Safe to import in mock/testing environments where Autodesk.Revit.DB is not present.
"""

import sys

# Attempt Revit API imports safely
try:
    import clr
    clr.AddReference('RevitAPI')
    clr.AddReference('RevitAPIUI')
    import Autodesk.Revit.DB as DB
    import Autodesk.Revit.UI as UI
    IS_REVIT = True
except Exception:
    DB = None
    UI = None
    IS_REVIT = False

class RevitVersionAdapter(object):
    """Encapsulates version-specific Revit API behaviors."""

    def __init__(self, doc=None):
        self.doc = doc
        self.version_str = "UNKNOWN"
        self.version_int = 2020
        if IS_REVIT and doc:
            try:
                self.version_str = doc.Application.VersionNumber
                self.version_int = int(self.version_str)
            except Exception:
                self.version_int = 2020

    @property
    def is_2027_or_newer(self):
        return self.version_int >= 2027

    @property
    def is_2020(self):
        return self.version_int == 2020

    def get_parameter_storage_type(self, param):
        """Returns string representation of Parameter StorageType."""
        if not IS_REVIT or not param:
            return "String"
        st = param.StorageType
        if st == DB.StorageType.Integer:
            return "Integer"
        elif st == DB.StorageType.Double:
            return "Double"
        elif st == DB.StorageType.String:
            return "String"
        elif st == DB.StorageType.ElementId:
            return "ElementId"
        return "None"

    def get_parameter_value(self, param):
        """Safely extracts value based on StorageType."""
        if not IS_REVIT or not param:
            return None
        st = param.StorageType
        if st == DB.StorageType.Integer:
            return param.AsInteger()
        elif st == DB.StorageType.Double:
            return param.AsDouble()
        elif st == DB.StorageType.String:
            return param.AsString()
        elif st == DB.StorageType.ElementId:
            eid = param.AsElementId()
            if eid:
                return eid.IntegerValue if hasattr(eid, "IntegerValue") else eid.Value
            return -1
        return None

    def set_parameter_value(self, param, value):
        """Safely sets parameter value respecting StorageType."""
        if not IS_REVIT or not param or param.IsReadOnly or value is None:
            return False
        try:
            st = param.StorageType
            if st == DB.StorageType.Integer:
                param.Set(int(value))
            elif st == DB.StorageType.Double:
                param.Set(float(value))
            elif st == DB.StorageType.String:
                param.Set(str(value))
            elif st == DB.StorageType.ElementId:
                int_val = int(value)
                eid = DB.ElementId(int_val)
                param.Set(eid)
            return True
        except Exception:
            return False

    def get_parameter_group_name(self, definition):
        """Retrieves parameter group name handling ForgeTypeId vs BuiltInParameterGroup."""
        if not IS_REVIT or not definition:
            return "PG_DATA"
        try:
            if hasattr(definition, "GetGroupTypeId"):
                # Revit 2024+ ForgeTypeId
                forge_type = definition.GetGroupTypeId()
                if forge_type and hasattr(forge_type, "TypeId"):
                    return forge_type.TypeId
            elif hasattr(definition, "ParameterGroup"):
                # Revit 2020 BuiltInParameterGroup
                return str(definition.ParameterGroup)
        except Exception:
            pass
        return "PG_DATA"

    def create_element_id(self, int_val):
        """Constructs an ElementId compatible with current Revit version."""
        if not IS_REVIT or int_val is None:
            return None
        try:
            # In Revit 2024+, ElementId constructor takes Int64, 2020 takes Int32
            return DB.ElementId(int(int_val))
        except Exception:
            return None

    def get_element_id_int(self, element_id):
        """Retrieves integer value of ElementId."""
        if not element_id:
            return -1
        if hasattr(element_id, "Value"):
            return element_id.Value
        elif hasattr(element_id, "IntegerValue"):
            return element_id.IntegerValue
        return int(element_id)

    def get_failure_messages(self, failures_accessor):
        """Extracts text messages from FailuresAccessor during transaction failure."""
        messages = []
        if not IS_REVIT or not failures_accessor:
            return messages
        try:
            failure_msgs = failures_accessor.GetFailureMessages()
            for msg in failure_msgs:
                desc = msg.GetDescriptionText()
                severity = msg.GetSeverity()
                messages.append("{}: {}".format(severity, desc))
        except Exception:
            pass
        return messages
