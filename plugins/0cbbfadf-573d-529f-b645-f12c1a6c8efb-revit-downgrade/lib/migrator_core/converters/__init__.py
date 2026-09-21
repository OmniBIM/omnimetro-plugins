# -*- coding: utf-8 -*-
"""
migrator_core.converters
========================
Converters and registry for transforming neutral records into native Revit 2020 elements.
"""

from .base_converter import BaseConverter
from .registry import ConverterRegistry
from .level_converter import LevelConverter
from .grid_converter import GridConverter
from .material_converter import MaterialConverter
from .wall_converter import WallConverter
from .floor_converter import FloorConverter
from .door_converter import DoorConverter
from .window_converter import WindowConverter
from .family_instance_converter import FamilyInstanceConverter
from .mep_converter import MEPConverter
from .directshape_converter import DirectShapeConverter
from .view_converter import ViewConverter, SheetConverter

# Register native converters by class name (language-independent)
ConverterRegistry.register_class("Wall", WallConverter)
ConverterRegistry.register_class("Floor", FloorConverter)
ConverterRegistry.register_class("Pipe", MEPConverter)
ConverterRegistry.register_class("Duct", MEPConverter)
ConverterRegistry.register_class("CableTray", MEPConverter)
ConverterRegistry.register_class("Conduit", MEPConverter)
ConverterRegistry.register_class("FlexPipe", MEPConverter)
ConverterRegistry.register_class("FlexDuct", MEPConverter)

# Register native converters by category (English + Chinese)
for cat in ["Walls", "墙", "墙体"]:
    ConverterRegistry.register(cat, WallConverter)
for cat in ["Floors", "楼板"]:
    ConverterRegistry.register(cat, FloorConverter)
for cat in ["Doors", "门"]:
    ConverterRegistry.register(cat, DoorConverter)
for cat in ["Windows", "窗"]:
    ConverterRegistry.register(cat, WindowConverter)

# MEP Linear System Families
for cat in ["Pipes", "管道", "Flex Pipes", "软管"]:
    ConverterRegistry.register(cat, MEPConverter)
for cat in ["Ducts", "风管", "Flex Ducts", "软风管"]:
    ConverterRegistry.register(cat, MEPConverter)
for cat in ["Cable Trays", "电缆桥架"]:
    ConverterRegistry.register(cat, MEPConverter)
for cat in ["Conduits", "线管"]:
    ConverterRegistry.register(cat, MEPConverter)

# Loadable Family Categories (Architecture, Structure, MEP)
loadable_cats = [
    "Structural Columns", "结构柱",
    "Structural Framing", "结构框架",
    "Furniture", "家具",
    "Furniture Systems", "家具系统",
    "Generic Models", "常规模型",
    "Specialty Equipment", "专用设备",
    "Duct Fittings", "风管管件",
    "Duct Accessories", "风管附件",
    "Pipe Fittings", "管件", "管道配件",
    "Pipe Accessories", "管道附件",
    "Cable Tray Fittings", "电缆桥架配件",
    "Conduit Fittings", "线管配件",
    "Air Terminals", "风口", "风道末端",
    "Sprinklers", "喷淋头",
    "Mechanical Equipment", "机械设备",
    "Electrical Equipment", "电气设备",
    "Electrical Fixtures", "电气装置",
    "Plumbing Fixtures", "卫浴装置",
    "Lighting Fixtures", "照明设备", "照明灯具",
    "Fire Alarm Devices", "火警设备",
    "Security Devices", "安全设备",
    "Communication Devices", "通讯设备",
    "Data Devices", "数据设备"
]
for cat in loadable_cats:
    ConverterRegistry.register(cat, FamilyInstanceConverter)

# Default fallback
ConverterRegistry.register_fallback(DirectShapeConverter)
