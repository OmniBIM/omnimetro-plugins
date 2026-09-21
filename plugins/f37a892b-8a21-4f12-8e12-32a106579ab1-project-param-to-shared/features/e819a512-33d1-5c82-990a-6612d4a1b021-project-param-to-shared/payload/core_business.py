# -*- coding: utf-8 -*-
"""
工具名称: 项目参数转共享与数值管理器 - 核心业务与算法层
功能描述: 纯 Python 业务逻辑与数据模型，处理项目参数性质识别、显示与单位换算、数值校验、
          筛选搜索与转化预检。零 Revit API 依赖，可直接进行单元测试与跨平台移植。
架构规范: 三层解耦标准 (UI层 -> 核心算法层 -> 宿主适配层)
"""

from __future__ import unicode_literals
import math
import re

try:
    unicode
except NameError:
    unicode = str


# ----------------------------------------------------------------------
# 单位换算常量 (Revit 内部英制单位 <-> 公制工程单位)
# ----------------------------------------------------------------------
MM_PER_FOOT = 304.8
M2_PER_FT2 = 0.09290304
M3_PER_FT3 = 0.028316846592
DEG_PER_RAD = 180.0 / math.pi

# ----------------------------------------------------------------------
# 参数存储类型与数据类型常量
# ----------------------------------------------------------------------
STORAGE_NONE = 'none'
STORAGE_INTEGER = 'integer'
STORAGE_DOUBLE = 'double'
STORAGE_STRING = 'string'
STORAGE_ELEMENTID = 'elementid'

PT_TEXT = 'text'
PT_INTEGER = 'integer'
PT_NUMBER = 'number'
PT_YESNO = 'yesno'
PT_LENGTH = 'length'
PT_AREA = 'area'
PT_VOLUME = 'volume'
PT_ANGLE = 'angle'
PT_FAMILY_TYPE = 'family_type'
PT_OTHER = 'other'

PARAM_TYPE_LABELS = {
    PT_TEXT: '文字',
    PT_INTEGER: '整数',
    PT_NUMBER: '数字',
    PT_YESNO: '是/否',
    PT_LENGTH: '长度 (mm)',
    PT_AREA: '面积 (m\u00b2)',
    PT_VOLUME: '体积 (m\u00b3)',
    PT_ANGLE: '角度 (\u00b0)',
    PT_FAMILY_TYPE: '族类型',
    PT_OTHER: '其他',
}

# ----------------------------------------------------------------------
# 参数性质常量
# ----------------------------------------------------------------------
NATURE_PROJECT = 'project'   # 普通项目参数 (可转化)
NATURE_SHARED = 'shared'     # 共享参数 (已是共享)
NATURE_BUILTIN = 'builtin'   # 系统内置参数 (不可转化)

NATURE_LABELS = {
    NATURE_PROJECT: '普通项目参数',
    NATURE_SHARED: '共享参数',
    NATURE_BUILTIN: '系统内置',
}

# ----------------------------------------------------------------------
# 转化状态常量
# ----------------------------------------------------------------------
CONVERT_STATUS_READY = 'ready'           # 可转化为共享参数
CONVERT_STATUS_ALREADY = 'already'       # 已是共享参数
CONVERT_STATUS_BUILTIN = 'builtin'       # 系统内置 (不可转)
CONVERT_STATUS_CONVERTED = 'converted'   # 转化成功
CONVERT_STATUS_FAILED = 'failed'         # 转化失败
CONVERT_STATUS_SKIPPED = 'skipped'       # 已跳过

CONVERT_STATUS_LABELS = {
    CONVERT_STATUS_READY: '可转化',
    CONVERT_STATUS_ALREADY: '已是共享',
    CONVERT_STATUS_BUILTIN: '系统原生',
    CONVERT_STATUS_CONVERTED: '转化成功',
    CONVERT_STATUS_FAILED: '转化失败',
    CONVERT_STATUS_SKIPPED: '已跳过',
}

# ----------------------------------------------------------------------
# 数值修改状态常量
# ----------------------------------------------------------------------
VALUE_STATUS_UNCHANGED = 'unchanged'
VALUE_STATUS_MODIFIED = 'modified'
VALUE_STATUS_SAVED = 'saved'
VALUE_STATUS_ERROR = 'error'
VALUE_STATUS_READONLY = 'readonly'

VALUE_STATUS_LABELS = {
    VALUE_STATUS_UNCHANGED: '未修改',
    VALUE_STATUS_MODIFIED: '待保存',
    VALUE_STATUS_SAVED: '已保存',
    VALUE_STATUS_ERROR: '格式错误',
    VALUE_STATUS_READONLY: '只读',
}

# 内置参数中文标准化映射
BUILTIN_NAME_TRANSLATIONS = {
    'PROJECT_NUMBER': '项目编号',
    'PROJECT_NAME': '项目名称',
    'PROJECT_ADDRESS': '项目地址',
    'PROJECT_STATUS': '项目状态',
    'PROJECT_ISSUE_DATE': '发布日期',
    'PROJECT_CLIENT_NAME': '客户名称',
    'PROJECT_AUTHOR': '作者',
    'PROJECT_BUILDING_NAME': '建筑物名称',
    'PROJECT_ORGANIZATION_NAME': '组织名称',
    'PROJECT_ORGANIZATION_DESCRIPTION': '组织描述',
    'PROJECT_ORGANIZATION_ADDRESS': '组织地址',
    'PROJECT_REVISION': '修订号',
}


# ----------------------------------------------------------------------
# 纯 Python 数据模型
# ----------------------------------------------------------------------
class ProjectParamItem(object):
    """单条参数项数据模型（解耦宿主对象，便于界面绑定与业务处理）"""

    def __init__(self, index, name, nature=NATURE_PROJECT, param_type=PT_TEXT,
                 storage_type=STORAGE_STRING, group_name='', scope_type='instance',
                 categories=None, guid='', value_text='', raw_value=None,
                 is_readonly=False, builtin_name='', element_count=0):
        self.index = index
        self.name = unicode(name) if name else ''
        self.nature = nature
        self.param_type = param_type
        self.storage_type = storage_type
        self.group_name = unicode(group_name) if group_name else '常用参数'
        self.scope_type = scope_type  # 'instance', 'type', 'project_info'
        self.categories = list(categories) if categories else []
        self.guid = unicode(guid) if guid else ''
        self.builtin_name = unicode(builtin_name) if builtin_name else ''
        self.element_count = int(element_count)

        # 初始值与当前编辑值
        self.original_value = unicode(value_text) if value_text is not None else ''
        self._current_value = self.original_value
        self.raw_value = raw_value
        self.is_readonly = bool(is_readonly)

        # 转化控制与状态
        self.is_checked = (nature == NATURE_PROJECT)
        self.can_convert = (nature == NATURE_PROJECT)
        self.convert_status = self._init_convert_status()
        self.convert_message = ''

        # 数值状态
        self.value_status = VALUE_STATUS_READONLY if self.is_readonly else VALUE_STATUS_UNCHANGED
        self.value_message = ''

        # 宿主句柄（供适配层使用，业务层不直接触碰）
        self.native_definition = None
        self.native_binding = None

    def _init_convert_status(self):
        if self.nature == NATURE_PROJECT:
            return CONVERT_STATUS_READY
        elif self.nature == NATURE_SHARED:
            return CONVERT_STATUS_ALREADY
        else:
            return CONVERT_STATUS_BUILTIN

    @property
    def current_value(self):
        return self._current_value

    @current_value.setter
    def current_value(self, val):
        new_text = unicode(val) if val is not None else ''
        if new_text == self._current_value:
            return
        self._current_value = new_text
        if self.is_readonly:
            self.value_status = VALUE_STATUS_READONLY
            self.value_message = '只读参数'
            return

        is_valid, err = validate_value_text(self.param_type, self.storage_type, self._current_value)
        if not is_valid:
            self.value_status = VALUE_STATUS_ERROR
            self.value_message = err
        elif self.is_value_modified:
            self.value_status = VALUE_STATUS_MODIFIED
            self.value_message = '待保存至模型'
        else:
            self.value_status = VALUE_STATUS_UNCHANGED
            self.value_message = ''

    @property
    def nature_label(self):
        return NATURE_LABELS.get(self.nature, '未知')

    @property
    def param_type_label(self):
        return PARAM_TYPE_LABELS.get(self.param_type, self.param_type or '文字')

    @property
    def convert_status_label(self):
        return CONVERT_STATUS_LABELS.get(self.convert_status, self.convert_status)

    @property
    def value_status_label(self):
        return VALUE_STATUS_LABELS.get(self.value_status, self.value_status)

    @property
    def scope_label(self):
        if self.scope_type == 'instance':
            return '实例'
        elif self.scope_type == 'type':
            return '类型'
        elif self.scope_type == 'project_info':
            return '项目信息'
        return '实例'

    @property
    def categories_label(self):
        if not self.categories:
            return '项目信息'
        if len(self.categories) == 1:
            return self.categories[0]
        if len(self.categories) <= 3:
            return ', '.join(self.categories)
        return '{0} 等共 {1} 个类别'.format(self.categories[0], len(self.categories))

    @property
    def is_value_modified(self):
        return self._current_value != self.original_value

    def mark_value_edited(self, new_text):
        """当用户在表格中编辑数值时触发"""
        self.current_value = new_text

    def mark_value_saved(self, new_original_value=None):
        """当数值成功提交保存至模型后触发"""
        if new_original_value is not None:
            self.original_value = unicode(new_original_value)
            self._current_value = self.original_value
        else:
            self.original_value = self._current_value
        self.value_status = VALUE_STATUS_SAVED
        self.value_message = '修改已保存'

    def mark_converted(self, new_guid):
        """当参数成功转化为共享参数后触发"""
        self.nature = NATURE_SHARED
        self.guid = unicode(new_guid)
        self.can_convert = False
        self.is_checked = False
        self.convert_status = CONVERT_STATUS_CONVERTED
        self.convert_message = '已成功转换为共享参数'


# ----------------------------------------------------------------------
# 数值格式化与单位换算函数
# ----------------------------------------------------------------------
def to_display_text(param_type, storage_type, raw_value, has_value=True):
    """将宿主底层数值转换为界面工程显示文本"""
    if not has_value or raw_value is None:
        return ''

    if storage_type == STORAGE_STRING:
        return unicode(raw_value)

    if param_type == PT_LENGTH:
        try:
            val_mm = float(raw_value) * MM_PER_FOOT
            return '{0:.2f}'.format(val_mm).rstrip('0').rstrip('.') if '.' in '{0:.2f}'.format(val_mm) else '{0:.0f}'.format(val_mm)
        except Exception:
            return unicode(raw_value)

    if param_type == PT_AREA:
        try:
            val_m2 = float(raw_value) * M2_PER_FT2
            return '{0:.3f}'.format(val_m2).rstrip('0').rstrip('.')
        except Exception:
            return unicode(raw_value)

    if param_type == PT_VOLUME:
        try:
            val_m3 = float(raw_value) * M3_PER_FT3
            return '{0:.3f}'.format(val_m3).rstrip('0').rstrip('.')
        except Exception:
            return unicode(raw_value)

    if param_type == PT_ANGLE:
        try:
            val_deg = float(raw_value) * DEG_PER_RAD
            return '{0:.2f}'.format(val_deg).rstrip('0').rstrip('.')
        except Exception:
            return unicode(raw_value)

    if param_type == PT_YESNO:
        try:
            int_val = int(raw_value)
            return '是' if int_val == 1 else '否'
        except Exception:
            return unicode(raw_value)

    if storage_type == STORAGE_INTEGER:
        try:
            return unicode(int(raw_value))
        except Exception:
            return unicode(raw_value)

    if storage_type == STORAGE_DOUBLE:
        try:
            d_val = float(raw_value)
            return '{0:.4f}'.format(d_val).rstrip('0').rstrip('.')
        except Exception:
            return unicode(raw_value)

    return unicode(raw_value)


def validate_value_text(param_type, storage_type, text_value):
    """校验用户输入的文本是否符合参数类型格式要求"""
    text = unicode(text_value).strip() if text_value is not None else ''
    if not text:
        return True, ''

    if storage_type == STORAGE_STRING or param_type == PT_TEXT:
        return True, ''

    if param_type == PT_YESNO:
        lower = text.lower()
        if lower in ['是', 'yes', '1', 'true', 't', 'y', '否', 'no', '0', 'false', 'f', 'n']:
            return True, ''
        return False, '请输入“是/否”或“1/0”'

    if param_type == PT_INTEGER or storage_type == STORAGE_INTEGER:
        try:
            int(text)
            return True, ''
        except ValueError:
            return False, '请输入有效整数'

    if param_type in [PT_NUMBER, PT_LENGTH, PT_AREA, PT_VOLUME, PT_ANGLE] or storage_type == STORAGE_DOUBLE:
        try:
            float(text)
            return True, ''
        except ValueError:
            return False, '请输入有效数字'

    return True, ''


def parse_display_to_raw(param_type, storage_type, display_text):
    """将界面显示文本解析为写入 Revit 模型的原生数值（含公制->英制换算）"""
    text = unicode(display_text).strip() if display_text is not None else ''

    if storage_type == STORAGE_STRING or param_type == PT_TEXT:
        return text, True, ''

    if not text:
        return None, True, ''

    if param_type == PT_YESNO:
        lower = text.lower()
        if lower in ['是', 'yes', '1', 'true', 't', 'y']:
            return 1, True, ''
        elif lower in ['否', 'no', '0', 'false', 'f', 'n']:
            return 0, True, ''
        return None, False, '无法识别的布尔值: {0}'.format(text)

    if param_type == PT_INTEGER or storage_type == STORAGE_INTEGER:
        try:
            return int(text), True, ''
        except ValueError:
            return None, False, '无效整数: {0}'.format(text)

    if param_type == PT_LENGTH:
        try:
            mm = float(text)
            return mm / MM_PER_FOOT, True, ''
        except ValueError:
            return None, False, '无效长度数值: {0}'.format(text)

    if param_type == PT_AREA:
        try:
            m2 = float(text)
            return m2 / M2_PER_FT2, True, ''
        except ValueError:
            return None, False, '无效面积数值: {0}'.format(text)

    if param_type == PT_VOLUME:
        try:
            m3 = float(text)
            return m3 / M3_PER_FT3, True, ''
        except ValueError:
            return None, False, '无效体积数值: {0}'.format(text)

    if param_type == PT_ANGLE:
        try:
            deg = float(text)
            return deg / DEG_PER_RAD, True, ''
        except ValueError:
            return None, False, '无效角度数值: {0}'.format(text)

    if storage_type == STORAGE_DOUBLE or param_type == PT_NUMBER:
        try:
            return float(text), True, ''
        except ValueError:
            return None, False, '无效数字: {0}'.format(text)

    return text, True, ''


# ----------------------------------------------------------------------
# 筛选与统计核心算法
# ----------------------------------------------------------------------
def filter_param_items(items, keyword='', nature_filter='all', convertible_only=False, modified_only=False):
    """根据关键词、性质类别及状态筛选参数列表"""
    kw = unicode(keyword).strip().lower() if keyword else ''
    result = []

    for item in items:
        # 1. 关键词过滤 (支持参数名、分组、GUID、数值、关联类别)
        if kw:
            matched = (
                kw in item.name.lower() or
                kw in item.group_name.lower() or
                kw in item.param_type_label.lower() or
                kw in item.guid.lower() or
                kw in item.current_value.lower() or
                kw in item.categories_label.lower() or
                kw in item.nature_label.lower()
            )
            if not matched:
                continue

        # 2. 性质过滤 (all / project / shared / builtin)
        if nature_filter and nature_filter != 'all':
            if item.nature != nature_filter:
                continue

        # 3. 仅显示可转化项
        if convertible_only and not item.can_convert:
            continue

        # 4. 仅显示待保存修改项
        if modified_only and item.value_status != VALUE_STATUS_MODIFIED:
            continue

        result.append(item)

    return result


def calculate_statistics(items):
    """计算当前参数项总览统计信息"""
    total = len(items)
    project_count = 0
    shared_count = 0
    builtin_count = 0
    convertible_count = 0
    modified_count = 0
    converted_count = 0

    for item in items:
        if item.nature == NATURE_PROJECT:
            project_count += 1
        elif item.nature == NATURE_SHARED:
            shared_count += 1
        elif item.nature == NATURE_BUILTIN:
            builtin_count += 1

        if item.can_convert:
            convertible_count += 1

        if item.value_status == VALUE_STATUS_MODIFIED:
            modified_count += 1

        if item.convert_status == CONVERT_STATUS_CONVERTED:
            converted_count += 1

    return {
        'total': total,
        'project_count': project_count,
        'shared_count': shared_count,
        'builtin_count': builtin_count,
        'convertible_count': convertible_count,
        'modified_count': modified_count,
        'converted_count': converted_count,
    }


def normalize_builtin_display_name(name, builtin_enum_name):
    """标准化内置参数的中文显示名"""
    if builtin_enum_name in BUILTIN_NAME_TRANSLATIONS:
        return BUILTIN_NAME_TRANSLATIONS[builtin_enum_name]
    return name
