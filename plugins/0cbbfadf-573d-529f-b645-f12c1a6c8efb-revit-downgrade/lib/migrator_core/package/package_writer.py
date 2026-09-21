# -*- coding: utf-8 -*-
"""
migrator_core.package.package_writer
====================================
Writer for creating the .rvtmig intermediate package (ZIP with SQLite & assets).
"""

import os
import json
import zipfile
import shutil
import tempfile
from .sqlite_schema import create_all_tables
from .checksum import calculate_sha256, AssetStore
from .manifest import PackageManifest
from ..constants import SQLITE_DB_NAME, MANIFEST_FILE_NAME, PACKAGE_EXTENSION
from ..compat.db_compat import get_sqlite

class PackageWriter(object):
    """
    Streams extracted model records into a SQLite database, saves assets,
    calculates checksums, and compiles everything into a final .rvtmig archive.
    """

    def __init__(self, output_dir, package_filename=None, manifest=None):
        self.output_dir = output_dir
        self.temp_dir = tempfile.mkdtemp(prefix="rvtmig_build_")
        self.sqlite_path = os.path.join(self.temp_dir, SQLITE_DB_NAME)
        self.manifest = manifest or PackageManifest()
        self.package_filename = package_filename
        if not self.package_filename:
            base_title = self.manifest.source_document_title or "Migration"
            self.package_filename = "{}{}".format(base_title, PACKAGE_EXTENSION)
        elif not self.package_filename.endswith(PACKAGE_EXTENSION):
            self.package_filename += PACKAGE_EXTENSION

        # SQLite connection via cross-engine adapter
        sqlite = get_sqlite()
        self.conn = sqlite.connect(self.sqlite_path)
        create_all_tables(self.conn)

        # Asset store
        self.asset_store = AssetStore(os.path.join(self.temp_dir, "assets"))

    def write_project_info(self, project_record):
        cursor = self.conn.cursor()
        orig = project_record.internal_origin
        bp = project_record.project_base_point
        sp = project_record.survey_point
        cursor.execute("""
            INSERT INTO project (
                title, file_path, revit_version, units,
                internal_origin_x, internal_origin_y, internal_origin_z,
                base_point_x, base_point_y, base_point_z,
                survey_point_x, survey_point_y, survey_point_z,
                true_north, raw_data_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_record.title,
            project_record.file_path,
            project_record.revit_version,
            project_record.units,
            orig[0] if len(orig) > 0 else 0.0,
            orig[1] if len(orig) > 1 else 0.0,
            orig[2] if len(orig) > 2 else 0.0,
            bp[0] if len(bp) > 0 else 0.0,
            bp[1] if len(bp) > 1 else 0.0,
            bp[2] if len(bp) > 2 else 0.0,
            sp[0] if len(sp) > 0 else 0.0,
            sp[1] if len(sp) > 1 else 0.0,
            sp[2] if len(sp) > 2 else 0.0,
            project_record.true_north,
            json.dumps(project_record.to_dict())
        ))

        # Write links
        links = getattr(project_record, "links", []) or []
        for lk in links:
            cursor.execute("""
                INSERT INTO links (source_id, link_name, path, transform_json)
                VALUES (?, ?, ?, ?)
            """, (
                lk.get("source_id", -1),
                lk.get("link_name", ""),
                lk.get("path", ""),
                json.dumps(lk.get("transform", {}))
            ))
        if links:
            self.manifest.contains_links = True

        self.conn.commit()

    def write_levels(self, level_records):
        cursor = self.conn.cursor()
        for lvl in level_records:
            cursor.execute("""
                INSERT OR REPLACE INTO levels (source_id, unique_id, name, elevation, raw_data_json)
                VALUES (?, ?, ?, ?, ?)
            """, (lvl.source_id, lvl.unique_id, lvl.name, lvl.elevation, json.dumps(lvl.to_dict())))
        self.conn.commit()

    def write_grids(self, grid_records):
        cursor = self.conn.cursor()
        for g in grid_records:
            cursor.execute("""
                INSERT OR REPLACE INTO grids (source_id, unique_id, name, curve_type, points_json)
                VALUES (?, ?, ?, ?, ?)
            """, (g.source_id, g.unique_id, g.name, g.curve_type, json.dumps(g.points)))
        self.conn.commit()

    def write_materials(self, material_records, progress_callback=None):
        cursor = self.conn.cursor()
        total = len(material_records)
        for idx, m in enumerate(material_records):
            if progress_callback:
                try:
                    progress_callback(idx + 1, total, getattr(m, "name", "材质"))
                except Exception:
                    pass
            cursor.execute("""
                INSERT OR REPLACE INTO materials (
                    source_id, name, color_r, color_g, color_b,
                    transparency, shininess, smoothness,
                    appearance_name, texture_filename, texture_asset_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                m.source_id, m.name, m.color_r, m.color_g, m.color_b,
                m.transparency, m.shininess, m.smoothness,
                m.appearance_name, m.texture_filename, m.texture_asset_id
            ))
        self.conn.commit()

    def write_elements_batch(self, element_records, progress_callback=None, cancellation_token=None):
        """Streams a batch of elements and their parameters into SQLite."""
        cursor = self.conn.cursor()
        total = len(element_records)
        for idx, el in enumerate(element_records):
            if cancellation_token and cancellation_token.is_cancellation_requested:
                break
            if progress_callback:
                try:
                    desc = getattr(el, "category_name", "") or getattr(el, "element_class", "构件")
                    progress_callback(idx + 1, total, desc)
                except Exception:
                    pass
            bmin = el.bbox_min or [0.0, 0.0, 0.0]
            bmax = el.bbox_max or [0.0, 0.0, 0.0]
            cursor.execute("""
                INSERT OR REPLACE INTO elements (
                    source_element_id, source_unique_id, category_id, category_name,
                    element_class, element_type_id, element_type_name, family_id,
                    family_name, level_id, level_name, workset_id,
                    phase_created_id, phase_demolished_id, design_option_id, group_id,
                    location_type, location_data_json,
                    bbox_min_x, bbox_min_y, bbox_min_z,
                    bbox_max_x, bbox_max_y, bbox_max_z,
                    transform_json, migration_level, migration_score,
                    fallback_type, status, host_unique_id,
                    geometry_asset_id, extra_data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                el.source_element_id, el.source_unique_id, el.category_id, el.category_name,
                el.element_class, el.element_type_id, el.element_type_name, el.family_id,
                el.family_name, el.level_id, el.level_name, el.workset_id,
                el.phase_created_id, el.phase_demolished_id, el.design_option_id, el.group_id,
                el.location_type, json.dumps(el.location_data),
                bmin[0], bmin[1], bmin[2],
                bmax[0], bmax[1], bmax[2],
                json.dumps(el.transform) if el.transform else None,
                el.migration_level, el.migration_score,
                el.fallback_type, el.status, el.host_unique_id,
                el.geometry_asset_id, json.dumps(el.extra_data)
            ))

            # Parameters
            for p in el.parameters:
                cursor.execute("""
                    INSERT INTO element_parameters (
                        element_source_unique_id, parameter_name, parameter_id,
                        definition_name, storage_type, value_string,
                        value_double, value_int, value_element_source_id,
                        display_value, unit_type, is_instance,
                        is_shared, shared_guid, formula, read_only
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    el.source_unique_id, p.name, p.param_id,
                    p.definition_name, p.storage_type, p.value_string,
                    p.value_double, p.value_int, p.value_element_source_id,
                    p.display_value, p.unit_type, 1 if p.is_instance else 0,
                    1 if p.is_shared else 0, p.shared_guid, p.formula, 1 if p.read_only else 0
                ))

            # Host relationship
            if el.host_unique_id:
                cursor.execute("""
                    INSERT INTO element_relationships (source_unique_id, target_unique_id, relation_type)
                    VALUES (?, ?, ?)
                """, (el.source_unique_id, el.host_unique_id, "HostedBy"))

        self.conn.commit()

    def write_families(self, family_records, progress_callback=None):
        cursor = self.conn.cursor()
        total = len(family_records)
        for idx, f in enumerate(family_records):
            if progress_callback:
                try:
                    progress_callback(idx + 1, total, getattr(f, "family_name", "族"))
                except Exception:
                    pass
            cursor.execute("""
                INSERT OR REPLACE INTO families (
                    family_id, family_name, category_name, category_id,
                    is_loadable, is_in_place, template_category,
                    geometry_asset_id, preview_asset_id, raw_recipe_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f.family_id, f.family_name, f.category_name, f.category_id,
                1 if f.is_loadable else 0, 1 if f.is_in_place else 0,
                f.template_category, f.geometry_asset_id, f.preview_asset_id,
                json.dumps(f.to_dict())
            ))
            # Types
            for t in f.types:
                cursor.execute("""
                    INSERT INTO family_types (family_name, type_name, source_type_id, parameters_json)
                    VALUES (?, ?, ?, ?)
                """, (f.family_name, t.name, t.type_id, json.dumps(t.values)))
            # Parameters
            for p in f.parameters:
                cursor.execute("""
                    INSERT INTO family_parameters (
                        family_name, parameter_name, storage_type, is_instance,
                        formula, is_shared, guid
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    f.family_name, p.name, p.storage_type,
                    1 if p.is_instance else 0, p.formula,
                    1 if p.is_shared else 0, p.guid
                ))
        self.conn.commit()

    def write_views(self, view_records, progress_callback=None):
        cursor = self.conn.cursor()
        total = len(view_records)
        for idx, v in enumerate(view_records):
            if progress_callback:
                try:
                    progress_callback(idx + 1, total, getattr(v, "name", "视图"))
                except Exception:
                    pass
            cursor.execute("""
                INSERT OR REPLACE INTO views (
                    source_id, unique_id, name, view_type, scale,
                    detail_level, discipline, crop_box_json,
                    view_template_id, associated_level_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                v.source_id, v.unique_id, v.name, v.view_type, v.scale,
                v.detail_level, v.discipline, json.dumps(v.crop_box) if v.crop_box else None,
                v.view_template_id, v.associated_level_id
            ))
        self.conn.commit()

    def write_sheets(self, sheet_records, progress_callback=None):
        cursor = self.conn.cursor()
        total = len(sheet_records)
        for idx, s in enumerate(sheet_records):
            if progress_callback:
                try:
                    progress_callback(idx + 1, total, getattr(s, "sheet_number", "图纸"))
                except Exception:
                    pass
            cursor.execute("""
                INSERT OR REPLACE INTO sheets (
                    source_id, unique_id, sheet_number, sheet_name,
                    titleblock_family, viewports_json
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                s.source_id, s.unique_id, s.sheet_number, s.sheet_name,
                s.titleblock_family, json.dumps(s.viewports)
            ))
        self.conn.commit()

    def write_statistics(self, stats_dict):
        cursor = self.conn.cursor()
        for k, v in stats_dict.items():
            cursor.execute("""
                INSERT OR REPLACE INTO migration_statistics (key, value_json)
                VALUES (?, ?)
            """, (k, json.dumps(v)))
        self.conn.commit()
        self.manifest.stats = stats_dict

    def finalize(self, progress_callback=None):
        """
        Closes SQLite connection, computes checksums, writes manifest,
        packages into final .rvtmig ZIP container, and cleans up temp folder.
        """
        self.conn.close()

        if progress_callback:
            try:
                progress_callback(1, 10, u"正在计算 SQLite 数据库校验和...")
            except Exception:
                pass

        # Compute SQLite checksum
        sqlite_sha = calculate_sha256(self.sqlite_path)
        self.manifest.checksums[SQLITE_DB_NAME] = sqlite_sha

        # Compute asset checksums
        assets_root = os.path.join(self.temp_dir, "assets")
        if os.path.exists(assets_root):
            asset_files = []
            for root, _, files in os.walk(assets_root):
                for f in files:
                    asset_files.append(os.path.join(root, f))
            tot_a = len(asset_files)
            for i, full_p in enumerate(asset_files):
                rel_p = os.path.relpath(full_p, self.temp_dir).replace("\\", "/")
                self.manifest.checksums[rel_p] = calculate_sha256(full_p)
                if progress_callback:
                    try:
                        progress_callback(i + 1, max(1, tot_a), u"校验资产文件: {}".format(os.path.basename(full_p)))
                    except Exception:
                        pass

        # Write manifest.json
        if progress_callback:
            try:
                progress_callback(3, 10, u"正在生成迁移包清单 manifest.json...")
            except Exception:
                pass
        manifest_path = os.path.join(self.temp_dir, MANIFEST_FILE_NAME)
        self.manifest.save_to_file(manifest_path)

        # Create output ZIP package
        if not os.path.exists(self.output_dir):
            try:
                os.makedirs(self.output_dir)
            except Exception:
                pass

        all_zip_files = []
        for root, _, files in os.walk(self.temp_dir):
            for f in files:
                all_zip_files.append(os.path.join(root, f))

        tot_files = len(all_zip_files)
        final_pkg_path = os.path.join(self.output_dir, self.package_filename)
        with zipfile.ZipFile(final_pkg_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for idx, full_p in enumerate(all_zip_files):
                arcname = os.path.relpath(full_p, self.temp_dir)
                if progress_callback:
                    try:
                        progress_callback(idx + 1, max(1, tot_files), u"正在压缩打包: {}".format(arcname))
                    except Exception:
                        pass
                zipf.write(full_p, arcname)

        # Cleanup temp directory
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass

        return final_pkg_path
