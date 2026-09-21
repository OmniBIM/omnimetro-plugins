# -*- coding: utf-8 -*-
"""
migrator_core.package.package_reader
====================================
Reader and validator for .rvtmig intermediate migration packages.
"""

import os
import json
import zipfile
import shutil
import tempfile
from ..compat.db_compat import get_sqlite
from .manifest import PackageManifest
from .checksum import calculate_sha256
from ..exceptions import PackageCorruptionError, UnsupportedVersionError
from ..constants import SQLITE_DB_NAME, MANIFEST_FILE_NAME, SCHEMA_VERSION
from ..models import (
    ProjectRecord,
    LevelRecord,
    GridRecord,
    MaterialRecord,
    ElementRecord,
    ParameterRecord,
    FamilyRecord,
    FamilyTypeRecord,
    FamilyParameterDefinition,
    ViewRecord,
    SheetRecord
)

class PackageReader(object):
    """
    Validates, extracts, and exposes query interfaces for a .rvtmig package.
    """

    def __init__(self, package_path, verify_integrity=True):
        if not os.path.exists(package_path):
            raise IOError("Package file not found: {}".format(package_path))

        self.package_path = package_path
        self.extract_dir = tempfile.mkdtemp(prefix="rvtmig_read_")

        # Unpack
        with zipfile.ZipFile(package_path, "r") as zipf:
            zipf.extractall(self.extract_dir)

        # Read manifest
        manifest_path = os.path.join(self.extract_dir, MANIFEST_FILE_NAME)
        if not os.path.exists(manifest_path):
            self.close()
            raise PackageCorruptionError("Missing manifest.json in package archive")

        self.manifest = PackageManifest.load_from_file(manifest_path)

        # Check version compatibility
        if self.manifest.schema_version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            self.close()
            raise UnsupportedVersionError(
                "Incompatible package schema version: {}. Tool supports: {}".format(
                    self.manifest.schema_version, SCHEMA_VERSION
                )
            )

        # Verify integrity
        if verify_integrity and self.manifest.checksums:
            for rel_path, expected_sha in self.manifest.checksums.items():
                local_path = os.path.join(self.extract_dir, rel_path)
                if not os.path.exists(local_path):
                    self.close()
                    raise PackageCorruptionError("Missing package component: {}".format(rel_path))
                actual_sha = calculate_sha256(local_path)
                if actual_sha != expected_sha:
                    self.close()
                    raise PackageCorruptionError(
                        "Integrity checksum failed for: {}. Expected {}, got {}".format(
                            rel_path, expected_sha, actual_sha
                        )
                    )

        # Connect to SQLite
        self.sqlite_path = os.path.join(self.extract_dir, SQLITE_DB_NAME)
        if not os.path.exists(self.sqlite_path):
            self.close()
            raise PackageCorruptionError("Missing migration.sqlite inside package")

        sqlite = get_sqlite()
        self.conn = sqlite.connect(self.sqlite_path)

    def get_project_info(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT raw_data_json FROM project LIMIT 1")
        row = cursor.fetchone()
        if row and row[0]:
            return ProjectRecord.from_dict(json.loads(row[0]))
        return ProjectRecord()

    def get_links(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT source_id, link_name, path, transform_json FROM links")
        rows = cursor.fetchall()
        links = []
        for r in rows:
            links.append({
                "source_id": r[0],
                "link_name": r[1],
                "path": r[2],
                "transform": json.loads(r[3]) if r[3] else {}
            })
        return links

    def get_levels(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT source_id, unique_id, name, elevation FROM levels ORDER BY elevation ASC")
        rows = cursor.fetchall()
        return [LevelRecord(r[0], r[1], r[2], r[3]) for r in rows]

    def get_grids(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT source_id, unique_id, name, curve_type, points_json FROM grids ORDER BY name ASC")
        rows = cursor.fetchall()
        grids = []
        for r in rows:
            pts = json.loads(r[4]) if r[4] else []
            grids.append(GridRecord(r[0], r[1], r[2], r[3], pts))
        return grids

    def get_materials(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT source_id, name, color_r, color_g, color_b,
                   transparency, shininess, smoothness, appearance_name,
                   texture_filename, texture_asset_id
            FROM materials ORDER BY name ASC
        """)
        rows = cursor.fetchall()
        return [
            MaterialRecord(
                source_id=r[0], name=r[1], color_r=r[2], color_g=r[3], color_b=r[4],
                transparency=r[5], shininess=r[6], smoothness=r[7], appearance_name=r[8],
                texture_filename=r[9], texture_asset_id=r[10]
            )
            for r in rows
        ]

    def get_families(self, is_loadable_only=False):
        cursor = self.conn.cursor()
        sql = "SELECT raw_recipe_json FROM families"
        if is_loadable_only:
            sql += " WHERE is_loadable = 1"
        cursor.execute(sql)
        rows = cursor.fetchall()
        return [FamilyRecord.from_dict(json.loads(r[0])) for r in rows if r[0]]

    def get_elements_count(self, category_name=None):
        cursor = self.conn.cursor()
        if category_name:
            cursor.execute("SELECT COUNT(*) FROM elements WHERE category_name = ?", (category_name,))
        else:
            cursor.execute("SELECT COUNT(*) FROM elements")
        return cursor.fetchone()[0]

    def get_elements_by_category(self, category_name, limit=None, offset=None):
        cursor = self.conn.cursor()
        sql = "SELECT * FROM elements WHERE category_name = ?"
        params = [category_name]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
            if offset is not None:
                sql += " OFFSET ?"
                params.append(offset)
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        col_names = [d[0] for d in cursor.description]
        return [self._row_to_element(r, col_names) for r in rows]

    def get_all_elements(self, limit=None, offset=None):
        cursor = self.conn.cursor()
        sql = "SELECT * FROM elements ORDER BY id ASC"
        params = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
            if offset is not None:
                sql += " OFFSET ?"
                params.append(offset)
        cursor.execute(sql, tuple(params))
        col_names = [d[0] for d in cursor.description]
        return [self._row_to_element(r, col_names) for r in cursor.fetchall()]

    def _row_to_element(self, row, col_names):
        d = dict(zip(col_names, row))
        loc_data = json.loads(d.get("location_data_json") or "{}")
        extra_data = json.loads(d.get("extra_data_json") or "{}")
        transform = json.loads(d.get("transform_json")) if d.get("transform_json") else None

        # Fetch element parameters
        params = self.get_element_parameters(d["source_unique_id"])

        return ElementRecord(
            source_element_id=d.get("source_element_id"),
            source_unique_id=d.get("source_unique_id"),
            category_id=d.get("category_id"),
            category_name=d.get("category_name"),
            element_class=d.get("element_class"),
            element_type_id=d.get("element_type_id"),
            element_type_name=d.get("element_type_name"),
            family_id=d.get("family_id"),
            family_name=d.get("family_name"),
            level_id=d.get("level_id"),
            level_name=d.get("level_name"),
            workset_id=d.get("workset_id"),
            phase_created_id=d.get("phase_created_id"),
            phase_demolished_id=d.get("phase_demolished_id"),
            design_option_id=d.get("design_option_id"),
            group_id=d.get("group_id"),
            location_type=d.get("location_type"),
            location_data=loc_data,
            bbox_min=[d.get("bbox_min_x", 0.0), d.get("bbox_min_y", 0.0), d.get("bbox_min_z", 0.0)],
            bbox_max=[d.get("bbox_max_x", 0.0), d.get("bbox_max_y", 0.0), d.get("bbox_max_z", 0.0)],
            transform=transform,
            migration_level=d.get("migration_level"),
            migration_score=d.get("migration_score"),
            fallback_type=d.get("fallback_type"),
            status=d.get("status"),
            host_unique_id=d.get("host_unique_id"),
            parameters=params,
            geometry_asset_id=d.get("geometry_asset_id"),
            extra_data=extra_data
        )

    def get_element_parameters(self, source_unique_id):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT parameter_name, parameter_id, definition_name, storage_type,
                   value_string, value_double, value_int, value_element_source_id,
                   display_value, unit_type, is_instance, is_shared, shared_guid,
                   formula, read_only
            FROM element_parameters
            WHERE element_source_unique_id = ?
        """, (source_unique_id,))
        rows = cursor.fetchall()
        params = []
        for r in rows:
            params.append(ParameterRecord(
                name=r[0],
                param_id=r[1],
                definition_name=r[2],
                storage_type=r[3],
                value_string=r[4],
                value_double=r[5],
                value_int=r[6],
                value_element_source_id=r[7],
                display_value=r[8] or "",
                unit_type=r[9] or "",
                is_instance=bool(r[10]),
                is_shared=bool(r[11]),
                shared_guid=r[12],
                formula=r[13],
                read_only=bool(r[14])
            ))
        return params

    def get_views(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT source_id, unique_id, name, view_type, scale,
                   detail_level, discipline, crop_box_json,
                   view_template_id, associated_level_id
            FROM views
        """)
        rows = cursor.fetchall()
        views = []
        for r in rows:
            cb = json.loads(r[7]) if r[7] else None
            views.append(ViewRecord(
                source_id=r[0], unique_id=r[1], name=r[2], view_type=r[3], scale=r[4],
                detail_level=r[5], discipline=r[6], crop_box=cb,
                view_template_id=r[8], associated_level_id=r[9]
            ))
        return views

    def get_sheets(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT source_id, unique_id, sheet_number, sheet_name,
                   titleblock_family, viewports_json
            FROM sheets
        """)
        rows = cursor.fetchall()
        sheets = []
        for r in rows:
            vp = json.loads(r[5]) if r[5] else []
            sheets.append(SheetRecord(
                source_id=r[0], unique_id=r[1], sheet_number=r[2], sheet_name=r[3],
                titleblock_family=r[4], viewports=vp
            ))
        return sheets

    def record_element_mapping(self, source_unique_id, source_element_id, target_element_id, target_unique_id, status="SUCCESS"):
        """Records a successful migration mapping in SQLite."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO element_mapping (
                source_unique_id, source_element_id, target_element_id, target_unique_id, status
            ) VALUES (?, ?, ?, ?, ?)
        """, (source_unique_id, source_element_id, target_element_id, target_unique_id, status))
        self.conn.commit()

    def get_target_mapping(self, source_unique_id):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT target_element_id, target_unique_id, status
            FROM element_mapping WHERE source_unique_id = ?
        """, (source_unique_id,))
        return cursor.fetchone()

    def get_asset_file_path(self, rel_path):
        """Returns the extracted absolute path of an asset file."""
        return os.path.join(self.extract_dir, rel_path)

    def close(self):
        """Closes SQLite connection and deletes extracted temp directory."""
        if hasattr(self, "conn") and self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
        if hasattr(self, "extract_dir") and os.path.exists(self.extract_dir):
            try:
                shutil.rmtree(self.extract_dir)
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
