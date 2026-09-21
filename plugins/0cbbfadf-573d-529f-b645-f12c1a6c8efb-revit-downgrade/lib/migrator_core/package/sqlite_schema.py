# -*- coding: utf-8 -*-
"""
migrator_core.package.sqlite_schema
===================================
SQLite DDL schemas and indices for the neutral BIM migration package.
Includes all 28 tables defined in the specification.
"""

SCHEMA_SQL = """
-- 1. Project Info
CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    file_path TEXT,
    revit_version TEXT,
    units TEXT,
    internal_origin_x REAL,
    internal_origin_y REAL,
    internal_origin_z REAL,
    base_point_x REAL,
    base_point_y REAL,
    base_point_z REAL,
    survey_point_x REAL,
    survey_point_y REAL,
    survey_point_z REAL,
    true_north REAL,
    raw_data_json TEXT
);

-- 2. Levels
CREATE TABLE IF NOT EXISTS levels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    unique_id TEXT UNIQUE,
    name TEXT,
    elevation REAL,
    raw_data_json TEXT
);

-- 3. Grids
CREATE TABLE IF NOT EXISTS grids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    unique_id TEXT UNIQUE,
    name TEXT,
    curve_type TEXT,
    points_json TEXT
);

-- 4. Categories
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER,
    name TEXT UNIQUE,
    can_native_rebuild INTEGER,
    need_family INTEGER,
    need_geometry_fallback INTEGER,
    unsupported INTEGER
);

-- 5. Elements
CREATE TABLE IF NOT EXISTS elements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_element_id INTEGER,
    source_unique_id TEXT UNIQUE,
    category_id INTEGER,
    category_name TEXT,
    element_class TEXT,
    element_type_id INTEGER,
    element_type_name TEXT,
    family_id INTEGER,
    family_name TEXT,
    level_id INTEGER,
    level_name TEXT,
    workset_id INTEGER,
    phase_created_id INTEGER,
    phase_demolished_id INTEGER,
    design_option_id INTEGER,
    group_id INTEGER,
    location_type TEXT,
    location_data_json TEXT,
    bbox_min_x REAL,
    bbox_min_y REAL,
    bbox_min_z REAL,
    bbox_max_x REAL,
    bbox_max_y REAL,
    bbox_max_z REAL,
    transform_json TEXT,
    migration_level INTEGER,
    migration_score INTEGER,
    fallback_type TEXT,
    status TEXT,
    host_unique_id TEXT,
    geometry_asset_id TEXT,
    extra_data_json TEXT
);

-- 6. Element Parameters
CREATE TABLE IF NOT EXISTS element_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    element_source_unique_id TEXT,
    parameter_name TEXT,
    parameter_id INTEGER,
    definition_name TEXT,
    storage_type TEXT,
    value_string TEXT,
    value_double REAL,
    value_int INTEGER,
    value_element_source_id INTEGER,
    display_value TEXT,
    unit_type TEXT,
    is_instance INTEGER,
    is_shared INTEGER,
    shared_guid TEXT,
    formula TEXT,
    read_only INTEGER
);

-- 7. Element Relationships
CREATE TABLE IF NOT EXISTS element_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_unique_id TEXT,
    target_unique_id TEXT,
    relation_type TEXT
);

-- 8. Element Geometry
CREATE TABLE IF NOT EXISTS element_geometry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_unique_id TEXT UNIQUE,
    asset_id TEXT,
    format TEXT,
    volume REAL,
    surface_area REAL,
    vertex_count INTEGER,
    face_count INTEGER
);

-- 9. Element Types
CREATE TABLE IF NOT EXISTS element_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type_id INTEGER,
    unique_id TEXT UNIQUE,
    name TEXT,
    category_name TEXT,
    family_name TEXT,
    parameters_json TEXT
);

-- 10. Families
CREATE TABLE IF NOT EXISTS families (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER,
    family_name TEXT UNIQUE,
    category_name TEXT,
    category_id INTEGER,
    is_loadable INTEGER,
    is_in_place INTEGER,
    template_category TEXT,
    geometry_asset_id TEXT,
    preview_asset_id TEXT,
    raw_recipe_json TEXT
);

-- 11. Family Types
CREATE TABLE IF NOT EXISTS family_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_name TEXT,
    type_name TEXT,
    source_type_id INTEGER,
    parameters_json TEXT
);

-- 12. Family Parameters
CREATE TABLE IF NOT EXISTS family_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_name TEXT,
    parameter_name TEXT,
    storage_type TEXT,
    is_instance INTEGER,
    formula TEXT,
    is_shared INTEGER,
    guid TEXT
);

-- 13. Family Geometry
CREATE TABLE IF NOT EXISTS family_geometry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_name TEXT,
    form_type TEXT,
    form_data_json TEXT
);

-- 14. Family Nested
CREATE TABLE IF NOT EXISTS family_nested (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_family_name TEXT,
    child_family_name TEXT
);

-- 15. Materials
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    name TEXT UNIQUE,
    color_r INTEGER,
    color_g INTEGER,
    color_b INTEGER,
    transparency INTEGER,
    shininess INTEGER,
    smoothness INTEGER,
    appearance_name TEXT,
    texture_filename TEXT,
    texture_asset_id TEXT
);

-- 16. Material Assets
CREATE TABLE IF NOT EXISTS material_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_name TEXT,
    asset_type TEXT,
    asset_data_json TEXT
);

-- 17. Shared Parameters
CREATE TABLE IF NOT EXISTS shared_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT UNIQUE,
    name TEXT,
    data_type TEXT,
    parameter_group TEXT,
    is_instance INTEGER,
    categories_json TEXT
);

-- 18. Views
CREATE TABLE IF NOT EXISTS views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    unique_id TEXT UNIQUE,
    name TEXT,
    view_type TEXT,
    scale INTEGER,
    detail_level TEXT,
    discipline TEXT,
    crop_box_json TEXT,
    view_template_id INTEGER,
    associated_level_id INTEGER
);

-- 19. View Templates
CREATE TABLE IF NOT EXISTS view_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    name TEXT UNIQUE,
    settings_json TEXT
);

-- 20. Sheets
CREATE TABLE IF NOT EXISTS sheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    unique_id TEXT UNIQUE,
    sheet_number TEXT,
    sheet_name TEXT,
    titleblock_family TEXT,
    viewports_json TEXT
);

-- 21. Schedules
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    unique_id TEXT UNIQUE,
    name TEXT,
    category_name TEXT,
    definition_json TEXT
);

-- 22. Links
CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    link_name TEXT,
    path TEXT,
    transform_json TEXT
);

-- 23. Worksets
CREATE TABLE IF NOT EXISTS worksets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    name TEXT UNIQUE,
    kind TEXT
);

-- 24. Phases
CREATE TABLE IF NOT EXISTS phases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    name TEXT,
    sequence INTEGER
);

-- 25. Design Options
CREATE TABLE IF NOT EXISTS design_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    name TEXT,
    is_primary INTEGER,
    option_set_name TEXT
);

-- 26. Migration Actions
CREATE TABLE IF NOT EXISTS migration_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT,
    source_id TEXT,
    action_type TEXT,
    target_id TEXT,
    status TEXT,
    message TEXT,
    timestamp TEXT
);

-- 27. Migration Errors
CREATE TABLE IF NOT EXISTS migration_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT,
    category TEXT,
    phase TEXT,
    message TEXT,
    stacktrace TEXT,
    fallback TEXT,
    timestamp TEXT
);

-- 28. Migration Statistics
CREATE TABLE IF NOT EXISTS migration_statistics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE,
    value_json TEXT
);

-- 29. Element Mapping (Tracking source -> target mappings)
CREATE TABLE IF NOT EXISTS element_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_unique_id TEXT UNIQUE,
    source_element_id INTEGER,
    target_element_id INTEGER,
    target_unique_id TEXT,
    status TEXT
);

-- Indices for rapid query performance
CREATE INDEX IF NOT EXISTS idx_elements_uid ON elements(source_unique_id);
CREATE INDEX IF NOT EXISTS idx_elements_cat ON elements(category_name);
CREATE INDEX IF NOT EXISTS idx_elements_lvl ON elements(level_id);
CREATE INDEX IF NOT EXISTS idx_elements_type ON elements(element_type_id);
CREATE INDEX IF NOT EXISTS idx_elements_fam ON elements(family_id);
CREATE INDEX IF NOT EXISTS idx_params_uid ON element_parameters(element_source_unique_id);
CREATE INDEX IF NOT EXISTS idx_rel_source ON element_relationships(source_unique_id);
CREATE INDEX IF NOT EXISTS idx_rel_target ON element_relationships(target_unique_id);
CREATE INDEX IF NOT EXISTS idx_mapping_uid ON element_mapping(source_unique_id);
"""

def create_all_tables(conn):
    """Executes the DDL schema on an active sqlite3 Connection."""
    cursor = conn.cursor()
    cursor.executescript(SCHEMA_SQL)
    conn.commit()
