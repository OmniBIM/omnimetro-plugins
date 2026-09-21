# -*- coding: utf-8 -*-
"""
migrator_core.package.manifest
==============================
Manifest metadata definition and validation for .rvtmig packages.
"""

import json
import uuid
import datetime
from ..constants import SCHEMA_VERSION, TOOL_VERSION, DEFAULT_SOURCE_VERSION, DEFAULT_TARGET_VERSION

class PackageManifest(object):
    """Encapsulates package identity, compatibility versions, and content flags."""

    def __init__(
        self,
        package_id=None,
        schema_version=SCHEMA_VERSION,
        tool_version=TOOL_VERSION,
        source_revit_version=DEFAULT_SOURCE_VERSION,
        target_revit_version=DEFAULT_TARGET_VERSION,
        source_document_title="",
        source_document_path="",
        units="revit_internal",
        coordinate_system="revit_internal_origin",
        contains_families=True,
        contains_geometry_fallback=True,
        contains_views=True,
        contains_sheets=True,
        contains_links=False,
        checksums=None,
        stats=None
    ):
        self.package_id = package_id or str(uuid.uuid4())
        self.schema_version = schema_version
        self.tool_version = tool_version
        self.source_revit_version = str(source_revit_version)
        self.target_revit_version = str(target_revit_version)
        self.source_document_title = source_document_title
        self.source_document_path = source_document_path
        self.created_utc = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        self.units = units
        self.coordinate_system = coordinate_system
        self.contains_families = contains_families
        self.contains_geometry_fallback = contains_geometry_fallback
        self.contains_views = contains_views
        self.contains_sheets = contains_sheets
        self.contains_links = contains_links
        self.checksums = checksums or {}
        self.stats = stats or {}

    def to_dict(self):
        return {
            "package_id": self.package_id,
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "source_revit_version": self.source_revit_version,
            "target_revit_version": self.target_revit_version,
            "source_document_title": self.source_document_title,
            "source_document_path": self.source_document_path,
            "created_utc": self.created_utc,
            "units": self.units,
            "coordinate_system": self.coordinate_system,
            "contains_families": self.contains_families,
            "contains_geometry_fallback": self.contains_geometry_fallback,
            "contains_views": self.contains_views,
            "contains_sheets": self.contains_sheets,
            "contains_links": self.contains_links,
            "checksums": self.checksums,
            "stats": self.stats
        }

    @classmethod
    def from_dict(cls, data):
        manifest = cls(
            package_id=data.get("package_id"),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            tool_version=data.get("tool_version", TOOL_VERSION),
            source_revit_version=data.get("source_revit_version", DEFAULT_SOURCE_VERSION),
            target_revit_version=data.get("target_revit_version", DEFAULT_TARGET_VERSION),
            source_document_title=data.get("source_document_title", ""),
            source_document_path=data.get("source_document_path", ""),
            units=data.get("units", "revit_internal"),
            coordinate_system=data.get("coordinate_system", "revit_internal_origin"),
            contains_families=data.get("contains_families", True),
            contains_geometry_fallback=data.get("contains_geometry_fallback", True),
            contains_views=data.get("contains_views", True),
            contains_sheets=data.get("contains_sheets", True),
            contains_links=data.get("contains_links", False),
            checksums=data.get("checksums", {}),
            stats=data.get("stats", {})
        )
        if "created_utc" in data:
            manifest.created_utc = data["created_utc"]
        return manifest

    def save_to_file(self, file_path):
        with open(file_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load_from_file(cls, file_path):
        with open(file_path, "r") as f:
            data = json.load(f)
            return cls.from_dict(data)
