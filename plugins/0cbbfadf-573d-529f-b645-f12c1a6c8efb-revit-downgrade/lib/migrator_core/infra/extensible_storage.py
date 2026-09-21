# -*- coding: utf-8 -*-
"""
migrator_core.infra.extensible_storage
======================================
ExtensibleStorage helper to embed source unique ID and migration package ID
into reconstructed Revit 2020 elements for traceability and resume capability.
"""

import uuid
from ..compat import IS_REVIT, DB

# Stable GUID for Migration Metadata Schema
MIGRATION_SCHEMA_GUID = "c7d2e3f4-5b6a-4c8d-9e0f-1a2b3c4d5e6f"

_schema_cache = None

def _get_or_create_schema():
    global _schema_cache
    if not IS_REVIT or not DB:
        return None
    if _schema_cache:
        return _schema_cache

    try:
        schema_guid = System.Guid(MIGRATION_SCHEMA_GUID)
    except Exception:
        # IronPython / clr System.Guid
        import System
        schema_guid = System.Guid(MIGRATION_SCHEMA_GUID)

    existing = DB.ExtensibleStorage.Schema.Lookup(schema_guid)
    if existing:
        _schema_cache = existing
        return existing

    try:
        builder = DB.ExtensibleStorage.SchemaBuilder(schema_guid)
        builder.SetSchemaName("RVT2020MigrationMetadata")
        builder.SetDocumentation("Tracks origin source element UID and package ID across Revit versions")
        builder.SetReadAccessLevel(DB.ExtensibleStorage.AccessLevel.Public)
        builder.SetWriteAccessLevel(DB.ExtensibleStorage.AccessLevel.Public)

        field_src = builder.AddSimpleField("SourceUniqueId", System.String)
        field_pkg = builder.AddSimpleField("PackageId", System.String)
        _schema_cache = builder.Finish()
        return _schema_cache
    except Exception:
        return None

def set_migration_metadata(element, source_unique_id, package_id):
    """Embeds origin source UID and package ID onto the target Revit element."""
    if not IS_REVIT or not element:
        return False
    try:
        schema = _get_or_create_schema()
        if not schema:
            return False
        entity = DB.ExtensibleStorage.Entity(schema)
        entity.Set("SourceUniqueId", str(source_unique_id or ""))
        entity.Set("PackageId", str(package_id or ""))
        element.SetEntity(entity)
        return True
    except Exception:
        return False

def get_migration_metadata(element):
    """Retrieves origin source UID and package ID from a target element."""
    if not IS_REVIT or not element:
        return None
    try:
        schema = _get_or_create_schema()
        if not schema:
            return None
        entity = element.GetEntity(schema)
        if not entity.IsValid():
            return None
        src_uid = entity.Get[System.String]("SourceUniqueId")
        pkg_id = entity.Get[System.String]("PackageId")
        return {"source_unique_id": src_uid, "package_id": pkg_id}
    except Exception:
        return None
