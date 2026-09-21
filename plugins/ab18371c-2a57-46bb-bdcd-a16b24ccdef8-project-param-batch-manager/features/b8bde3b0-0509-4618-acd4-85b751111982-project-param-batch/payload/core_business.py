# -*- coding: utf-8 -*-
"""
工具名称: 项目参数批量管理器 - 核心业务与几何算法层
功能描述: 纯 Python 业务逻辑（单位换算 / 值格式化 / 数据模型），零 Revit API 依赖，
          可无损移植至 Rhino / Blender / 国产 BIM 平台。
架构规范: 三层解耦标准 (UI层 -> 核心算法层 -> 宿主适配层)
"""

import math


# ----------------------------------------------------------------------
# 单位换算常量（Revit 内部单位 -> 工程显示单位）
# ----------------------------------------------------------------------
MM_PER_FOOT = 304.8
M2_PER_FT2 = 0.09290304
M3_PER_FT3 = 0.028316846592
DEG_PER_RAD = 180.0 / math.pi

# 参数存储类型（与 Revit StorageType 对齐的字符串标识，解耦宿主）
STORAGE_NONE = 'none'
STORAGE_INTEGER = 'integer'
STORAGE_DOUBLE = 'double'
STORAGE_STRING = 'string'
STORAGE_ELEMENTID = 'elementid'

# 参数类型分组（与 Revit ParameterType 对齐的字符串标识）
PT_TEXT = 'text'
PT_INTEGER = 'integer'
PT_NUMBER = 'number'
PT_YESNO = 'yesno'
PT_LENGTH = 'length'
PT_AREA = 'area'
PT_VOLUME = 'volume'
PT_ANGLE = 'angle'

# 长度/面积/体积/角度类型的换算函数注册表（显示系数, 回写系数）
CONVERTERS = {
    PT_LENGTH: (MM_PER_FOOT, 1.0 / MM_PER_FOOT),
    PT_AREA: (M2_PER_FT2, 1.0 / M2_PER_FT2),
    PT_VOLUME: (M3_PER_FT3, 1.0 / M3_PER_FT3),
    PT_ANGLE: (DEG_PER_RAD, 1.0 / DEG_PER_RAD),
}

# 新建项目参数时的可选参数类型（供界面下拉框使用）
NEW_PARAM_TYPE_OPTIONS = [
    (PT_TEXT, u'文本'),
    (PT_INTEGER, u'整数'),
    (PT_NUMBER, u'数字'),
    (PT_YESNO, u'是/否'),
    (PT_LENGTH, u'长度 (mm)'),
    (PT_AREA, u'面积 (m2)'),
    (PT_VOLUME, u'体积 (m3)'),
    (PT_ANGLE, u'角度 (度)'),
]

# 参数分组（BuiltInParameterGroup 常用项，供新建参数选择）
PARAM_GROUP_OPTIONS = [
    ('PG_DATA', u'数据'),
    ('PG_TEXT', u'文字'),
    ('PG_CONSTRUCTION', u'构造'),
    ('PG_GEOMETRY', u'几何图形'),
    ('PG_IDENTITY_DATA', u'标识数据'),
    ('PG_OTHER', u'其他'),
]

# 内置项目基本参数 -> 中文显示名（用于界面列头可读性；未收录的用参数原名）
BUILTIN_PROJECT_PARAM_NAMES = {
    'PROJECT_NUMBER': u'项目编号',
    'PROJECT_NAME': u'项目名称',
    'PROJECT_ADDRESS': u'项目地址',
    'PROJECT_STATUS': u'项目状态',
    'PROJECT_ISSUE_DATE': u'发布日期',
    'PROJECT_CLIENT_NAME': u'客户名称',
    'PROJECT_AUTHOR': u'作者',
    'PROJECT_BUILDING_NAME': u'建筑物名称',
    'PROJECT_BUILDING_TYPE': u'建筑物类型',
    'PROJECT_LAST_SAVED_BY': u'最后保存者',
    'PROJECT_ORGANIZATION_NAME': u'组织名称',
    'PROJECT_ORGANIZATION_DESCRIPTION': u'组织描述',
    'PROJECT_ORGANIZATION_ADDRESS': u'组织地址',
    'PROJECT_REVISION': u'修订号',
    'PROJECT_STANDARD': u'标准',
    'PROJECT_UNITS': u'项目单位',
    'PROJECT_ROUNDING': u'项目舍入',
}


# ----------------------------------------------------------------------
# 核心业务函数（纯 Python）
# ----------------------------------------------------------------------
def to_display_text(param_type, storage_type, raw_value, has_value):
    """将宿主层提取的原始值转换为界面显示文本。
    长度->mm / 面积->m2 / 体积->m3 / 角度->度，其余按原始类型格式化。
    """
    if not has_value or raw_value is None:
        return u''
    if param_type in CONVERTERS:
        factor, _ = CONVERTERS[param_type]
        try:
            return u'{0:.3f}'.format(float(raw_value) * factor)
        except (TypeError, ValueError):
            return u''
    if storage_type == STORAGE_INTEGER:
        try:
            return u'{0}'.format(int(raw_value))
        except (TypeError, ValueError):
            return u''
    if storage_type == STORAGE_DOUBLE:
        try:
            return u'{0:.3f}'.format(float(raw_value))
        except (TypeError, ValueError):
            return u''
    if storage_type == STORAGE_ELEMENTID:
        # ElementId 类型：1=是, 0=否（YesNo 参数）
        try:
            return u'是' if int(raw_value) != 0 else u'否'
        except (TypeError, ValueError):
            return u''
    return u'{0}'.format(raw_value)


def from_display_text(param_type, storage_type, text):
    """将界面输入的文本转换为写入宿主的原始值。
    返回 (ok, value_or_error_message)。
    """
    if text is None:
        text = u''
    text = text.strip()
    if param_type in CONVERTERS:
        factor, inv = CONVERTERS[param_type]
        try:
            return True, float(text) * inv
        except (TypeError, ValueError):
            return False, u'请输入数字（{0}）'.format(text)
    if storage_type == STORAGE_INTEGER:
        try:
            return True, int(text)
        except (TypeError, ValueError):
            return False, u'请输入整数（{0}）'.format(text)
    if storage_type == STORAGE_DOUBLE:
        try:
            return True, float(text)
        except (TypeError, ValueError):
            return False, u'请输入数字（{0}）'.format(text)
    if storage_type == STORAGE_ELEMENTID:
        if text in (u'是', u'1', u'true', u'True', u'YES', u'yes'):
            return True, 1
        if text in (u'否', u'0', u'false', u'False', u'NO', u'no'):
            return True, 0
        return False, u'请输入"是"或"否"（{0}）'.format(text)
    # 字符串：直接写入
    return True, text


def normalize_builtin_display_name(param_name, builtin_name):
    """内置参数的中文显示名（列头友好）；无映射时返回原参数名。"""
    if builtin_name and builtin_name in BUILTIN_PROJECT_PARAM_NAMES:
        return BUILTIN_PROJECT_PARAM_NAMES[builtin_name]
    return param_name


# ----------------------------------------------------------------------
# 数据模型（纯 Python，可跨平台序列化）
# ----------------------------------------------------------------------
class ParamInfo(object):
    """一个项目参数的信息（从单个 Revit 文件提取）。"""
    def __init__(self, name, builtin_name='', param_type='', storage_type='',
                 display_name='', value_text='', raw_value=None, has_value=False,
                 is_readonly=False, is_shared=False, group_name=''):
        self.name = name                 # 参数定义名（写入时按此名匹配）
        self.builtin_name = builtin_name # 内置参数枚举名（如 PROJECT_NUMBER）
        self.param_type = param_type     # 参数类型标识（text/integer/...）
        self.storage_type = storage_type # 存储类型标识
        self.display_name = display_name # 界面列头显示名
        self.value_text = value_text     # 显示文本（提取值）
        self.raw_value = raw_value       # 原始值（宿主单位）
        self.has_value = has_value
        self.is_readonly = is_readonly
        self.is_shared = is_shared       # 是否共享/项目参数
        self.group_name = group_name

    def to_dict(self):
        return {
            'name': self.name,
            'builtin_name': self.builtin_name,
            'param_type': self.param_type,
            'storage_type': self.storage_type,
            'display_name': self.display_name,
            'value_text': self.value_text,
            'raw_value': self.raw_value,
            'has_value': self.has_value,
            'is_readonly': self.is_readonly,
            'is_shared': self.is_shared,
            'group_name': self.group_name,
        }


class FileParamData(object):
    """一个 Revit 文件提取出的参数数据集。"""
    def __init__(self, file_path, file_name):
        self.file_path = file_path
        self.file_name = file_name
        self.base_point = {   # 项目基点（毫米 / 度）
            'ns': None, 'ew': None, 'elev': None, 'angle': None,
        }
        self.params = []      # [ParamInfo, ...]
        self.ok = False
        self.error = u''

    def param_map(self):
        """参数名 -> ParamInfo"""
        return {p.name: p for p in self.params}

    def to_dict(self):
        return {
            'file_path': self.file_path,
            'file_name': self.file_name,
            'base_point': dict(self.base_point),
            'params': [p.to_dict() for p in self.params],
            'ok': self.ok,
            'error': self.error,
        }
