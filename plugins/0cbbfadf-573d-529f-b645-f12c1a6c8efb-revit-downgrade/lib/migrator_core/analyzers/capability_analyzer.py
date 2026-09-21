# -*- coding: utf-8 -*-
"""
migrator_core.analyzers.capability_analyzer
===========================================
Analyzes BIM element migrability, assigns 5-level scoring,
and generates the pre-migration Category Matrix and Risk Analysis.
"""

from ..constants import MigrationLevel, MIGRATION_SCORES

# Categories that Revit can natively create via API (Bilingual English/Chinese)
NATIVE_CATEGORIES = {
    # MEP Linear System Families
    "Pipes", "管道",
    "Ducts", "风管",
    "Cable Trays", "电缆桥架",
    "Conduits", "线管",
    "Flex Pipes", "软管",
    "Flex Ducts", "软风管",
    # Architectural & Structural System Families
    "Walls", "墙", "墙体",
    "Floors", "楼板",
    "Roofs", "屋顶",
    "Ceilings", "天花板",
    # Datums & Spatial
    "Levels", "标高",
    "Grids", "轴网",
    "Rooms", "房间",
    "Spaces", "空间",
    "Areas", "面积"
}

# .NET classes that are inherently Level 1 Native System Elements (language-independent)
NATIVE_CLASSES = {
    "Pipe", "Duct", "CableTray", "Conduit", "FlexPipe", "FlexDuct",
    "Wall", "Floor", "Ceiling", "RoofBase", "FootPrintRoof", "ExtrusionRoof",
    "Room", "Space", "Area", "ModelLine", "ModelArc"
}

# Categories that are typically loadable family instances (Bilingual English/Chinese)
FAMILY_CATEGORIES = {
    # MEP Fittings & Accessories
    "Duct Fittings", "风管管件",
    "Duct Accessories", "风管附件",
    "Pipe Fittings", "管件", "管道配件",
    "Pipe Accessories", "管道附件",
    "Cable Tray Fittings", "电缆桥架配件",
    "Conduit Fittings", "线管配件",
    "Air Terminals", "风口", "风道末端",
    "Sprinklers", "喷淋头",
    # MEP Equipment & Fixtures
    "Mechanical Equipment", "机械设备",
    "Electrical Equipment", "电气设备",
    "Electrical Fixtures", "电气装置",
    "Lighting Fixtures", "照明设备", "照明灯具",
    "Plumbing Fixtures", "卫浴装置",
    "Fire Alarm Devices", "火警设备",
    "Security Devices", "安全设备",
    "Communication Devices", "通讯设备",
    "Data Devices", "数据设备",
    # Architectural & Structural Loadable Families
    "Doors", "门",
    "Windows", "窗",
    "Structural Columns", "结构柱",
    "Structural Framing", "结构框架",
    "Furniture", "家具",
    "Furniture Systems", "家具系统",
    "Specialty Equipment", "专用设备",
    "Generic Models", "常规模型",
    "Detail Items", "详图项目",
    "Railings", "栏杆扶手",
    "Planting", "植物",
    "Site", "场地"
}

class RowItem(dict):
    """Dict subclass supporting dot-attribute access for WPF DataGrid binding."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            return ""

    def __setattr__(self, name, value):
        self[name] = value


class CategoryMatrixRow(object):
    def __init__(self, category_name):
        self.category_name = category_name
        self.total_count = 0
        self.native_count = 0
        self.family_count = 0
        self.geometry_count = 0
        self.unsupported_count = 0
        self.risk = "Low"
        self.remarks = ""

    @property
    def Category(self):
        return self.category_name

    @property
    def Count(self):
        return self.total_count

    @property
    def Native(self):
        return self.native_count

    @property
    def Family(self):
        return self.family_count

    @property
    def Geometry(self):
        return self.geometry_count

    @property
    def Unsupported(self):
        return self.unsupported_count

    @property
    def Risk(self):
        return self.risk

    @property
    def Remarks(self):
        return self.remarks

    def to_dict(self):
        return RowItem({
            "category": self.category_name,
            "count": self.total_count,
            "native": self.native_count,
            "family": self.family_count,
            "geometry": self.geometry_count,
            "unsupported": self.unsupported_count,
            "risk": self.risk,
            "remarks": self.remarks,
            "Category": self.category_name,
            "Count": self.total_count,
            "Native": self.native_count,
            "Family": self.family_count,
            "Geometry": self.geometry_count,
            "Unsupported": self.unsupported_count,
            "Risk": self.risk,
            "Remarks": self.remarks
        })

class CapabilityAnalyzer(object):
    """
    Assesses model elements before migration, classifying each into
    a 5-level migration strategy and reporting potential fidelity risks.
    """

    @classmethod
    def evaluate_element(cls, element_record):
        """
        Assigns migration_level and migration_score to an ElementRecord.
        Priority:
        1. In-place families -> Level 3/4 DirectShape Fallback
        2. System Families (Pipes, Ducts, CableTrays, Conduits, Walls, Floors) -> Level 1 Native
        3. Loadable Families (Fittings, Equipment, Valves, Fixtures, Doors, Windows) -> Level 2 Family Rebuild
        4. Generic mesh / unrecognized items -> Level 3/4 DirectShape Fallback
        """
        cat = element_record.category_name or ""
        el_class = element_record.element_class or ""
        fam_name = element_record.family_name or ""

        # 1. In-place families default to DirectShape / Geometry fallback
        if "InPlace" in el_class or "InPlace" in fam_name:
            element_record.migration_level = MigrationLevel.DIRECT_SHAPE
            element_record.migration_score = MIGRATION_SCORES[MigrationLevel.DIRECT_SHAPE]
            element_record.fallback_type = "DirectShape Fallback"
            return

        # 2. Level 1: Native System Families (identified by Class Name OR Category Name)
        if el_class in NATIVE_CLASSES or cat in NATIVE_CATEGORIES:
            element_record.migration_level = MigrationLevel.NATIVE
            element_record.migration_score = MIGRATION_SCORES[MigrationLevel.NATIVE]
            element_record.fallback_type = None
            return

        # 3. Level 2: Loadable Families (Fittings, Equipment, Fixtures, Terminals, Valves, Doors, etc.)
        if el_class == "FamilyInstance" or fam_name or cat in FAMILY_CATEGORIES:
            element_record.migration_level = MigrationLevel.FAMILY_REBUILD
            element_record.migration_score = MIGRATION_SCORES[MigrationLevel.FAMILY_REBUILD]
            element_record.fallback_type = "Family Reconstruction"
            return

        # 4. Fallback for unclassified custom meshes or direct shapes
        element_record.migration_level = MigrationLevel.DIRECT_SHAPE
        element_record.migration_score = MIGRATION_SCORES[MigrationLevel.DIRECT_SHAPE]
        element_record.fallback_type = "DirectShape Fallback"

    @classmethod
    def analyze_model(cls, elements, families=None, progress_callback=None):
        """
        Analyzes a full list of ElementRecords.
        Returns (matrix_rows, stats_dict, risks_list).
        """
        matrix_map = {}
        total = len(elements)
        native = 0
        fam_rebuild = 0
        geom_fallback = 0
        unsupported = 0
        risks = []

        in_place_count = 0
        count = 0

        for el in elements:
            count += 1
            if progress_callback and (count % 25 == 0 or count == total):
                try:
                    el_id = getattr(el, "source_element_id", None) or getattr(el, "source_id", None) or count
                    cat_name = getattr(el, "category_name", None) or u"构件"
                    progress_callback(count, total, u"[可行性分析] {} (Id: {})".format(cat_name, el_id))
                except Exception:
                    pass

            cls.evaluate_element(el)
            cat = el.category_name or "Unknown"
            if cat not in matrix_map:
                matrix_map[cat] = CategoryMatrixRow(cat)
            row = matrix_map[cat]
            row.total_count += 1

            if el.migration_level == MigrationLevel.NATIVE:
                row.native_count += 1
                native += 1
            elif el.migration_level == MigrationLevel.FAMILY_REBUILD:
                row.family_count += 1
                fam_rebuild += 1
            elif el.migration_level in (MigrationLevel.FAMILY_GEOMETRY, MigrationLevel.DIRECT_SHAPE):
                row.geometry_count += 1
                geom_fallback += 1
            else:
                row.unsupported_count += 1
                unsupported += 1

            if "InPlace" in el.element_class or "InPlace" in el.family_name:
                in_place_count += 1

        if in_place_count > 0:
            risks.append("{} 个内建族(In-Place Family)无法参数化重建，将采用 DirectShape 几何兜底".format(in_place_count))

        # Risk and remarks assessment per category
        matrix_rows = []
        for cat, row in sorted(matrix_map.items()):
            if row.unsupported_count > 0:
                row.risk = "High"
                row.remarks = "存在不支持的元素"
            elif row.geometry_count > 0:
                row.risk = "Medium"
                row.remarks = "部分元素采用几何兜底"
            else:
                row.risk = "Low"
                row.remarks = "原生高保真迁移"
            matrix_rows.append(row)

        migratable = native + fam_rebuild + geom_fallback
        coverage_pct = round((float(migratable) / float(total) * 100.0), 2) if total > 0 else 100.0

        stats = {
            "total_elements": total,
            "native_count": native,
            "family_count": fam_rebuild,
            "geometry_count": geom_fallback,
            "unsupported_count": unsupported,
            "coverage_percent": coverage_pct
        }

        return matrix_rows, stats, risks
