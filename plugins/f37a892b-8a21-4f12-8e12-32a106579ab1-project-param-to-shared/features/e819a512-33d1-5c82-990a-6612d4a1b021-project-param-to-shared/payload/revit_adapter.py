# -*- coding: utf-8 -*-
"""
工具名称: 项目参数转共享与数值管理器 - 宿主 API 适配层
功能描述: 封装所有 Revit API 读写与事务操作：
          1. 提取当前打开项目的全部项目参数、共享参数与内置参数
          2. 共享参数文件检测与智能自动创建/挂载 (UTF-8/ASCII 安全编码)
          3. 项目参数一键/批量无损转化为共享参数 (自动暂存并回写图元数值)
          4. 在当前文档中批量写入修改后的参数数值
架构规范: 三层解耦标准 (UI层 -> 核心算法层 -> 宿主适配层)
兼容性: 兼容 Autodesk Revit 2018 - 2026
"""

from __future__ import unicode_literals
import codecs
import os
import sys
import traceback

try:
    unicode
except NameError:
    unicode = str


def _safe_str(val):
    """安全转换为 unicode 字符串，避免在 Python 2.7 / IronPython 中发生 ASCII 解码崩溃"""
    if val is None:
        return ''
    try:
        return unicode(val)
    except Exception:
        try:
            return str(val).decode('utf-8', 'ignore')
        except Exception:
            return unicode(type(val))


import clr
clr.AddReference('System')
from System import Guid

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    Category,
    CategorySet,
    ElementId,
    ExternalDefinition,
    ExternalDefinitionCreationOptions,
    FilteredElementCollector,
    InstanceBinding,
    InternalDefinition,
    SharedParameterElement,
    StorageType,
    Transaction,
    TypeBinding,
)

# ----------------------------------------------------------------------
# 版本兼容：ParameterType / BuiltInParameterGroup 与 SpecTypeId / GroupTypeId
# ----------------------------------------------------------------------
try:
    from Autodesk.Revit.DB import ParameterType as RevitParameterType
except Exception:
    RevitParameterType = None

try:
    from Autodesk.Revit.DB import BuiltInParameterGroup as RevitBuiltInParameterGroup
except Exception:
    RevitBuiltInParameterGroup = None

try:
    from Autodesk.Revit.DB import SpecTypeId
except Exception:
    SpecTypeId = None

try:
    from Autodesk.Revit.DB import GroupTypeId
except Exception:
    GroupTypeId = None

from core_business import (
    NATURE_BUILTIN,
    NATURE_PROJECT,
    NATURE_SHARED,
    PT_ANGLE,
    PT_AREA,
    PT_FAMILY_TYPE,
    PT_INTEGER,
    PT_LENGTH,
    PT_NUMBER,
    PT_OTHER,
    PT_TEXT,
    PT_VOLUME,
    PT_YESNO,
    STORAGE_DOUBLE,
    STORAGE_ELEMENTID,
    STORAGE_INTEGER,
    STORAGE_NONE,
    STORAGE_STRING,
    ProjectParamItem,
    normalize_builtin_display_name,
    parse_display_to_raw,
    to_display_text,
)

# 内置参数枚举名缓存
_BUILTIN_NAME_CACHE = {}


def _get_builtin_enum_name(builtin_int_val):
    if builtin_int_val in _BUILTIN_NAME_CACHE:
        return _BUILTIN_NAME_CACHE[builtin_int_val]
    try:
        for name in dir(BuiltInParameter):
            if not name.startswith('_') and name.isupper():
                try:
                    if int(getattr(BuiltInParameter, name)) == int(builtin_int_val):
                        _BUILTIN_NAME_CACHE[builtin_int_val] = name
                        return name
                except Exception:
                    pass
    except Exception:
        pass
    _BUILTIN_NAME_CACHE[builtin_int_val] = ''
    return ''


def _resolve_param_type_from_spec(spec_type_id):
    """从 ForgeTypeId (SpecTypeId) 解析为 core 标识"""
    if spec_type_id is None or SpecTypeId is None:
        return None
    try:
        sid = str(spec_type_id)
        if sid == str(SpecTypeId.String.Text):
            return PT_TEXT
        elif sid == str(SpecTypeId.Int.Integer):
            return PT_INTEGER
        elif sid == str(SpecTypeId.Number):
            return PT_NUMBER
        elif sid == str(SpecTypeId.Boolean.YesNo):
            return PT_YESNO
        elif sid == str(SpecTypeId.Length):
            return PT_LENGTH
        elif sid == str(SpecTypeId.Area):
            return PT_AREA
        elif sid == str(SpecTypeId.Volume):
            return PT_VOLUME
        elif sid == str(SpecTypeId.Angle):
            return PT_ANGLE
        elif sid == str(SpecTypeId.Reference.FamilyType):
            return PT_FAMILY_TYPE
    except Exception:
        pass
    return None


def _resolve_param_type_from_enum(ptype_enum):
    """从 ParameterType 枚举解析为 core 标识"""
    if ptype_enum is None:
        return None
    try:
        p_name = str(ptype_enum)
        mapping = {
            'Text': PT_TEXT,
            'Integer': PT_INTEGER,
            'Number': PT_NUMBER,
            'YesNo': PT_YESNO,
            'Length': PT_LENGTH,
            'Area': PT_AREA,
            'Volume': PT_VOLUME,
            'Angle': PT_ANGLE,
            'FamilyType': PT_FAMILY_TYPE,
        }
        return mapping.get(p_name, PT_OTHER)
    except Exception:
        return None


def _get_definition_param_type(definition):
    """提取 Definition 的参数类型"""
    if definition is None:
        return PT_TEXT

    # 1. 尝试 Revit 2022+ GetDataType() / GetSpecTypeId()
    for method_name in ['GetDataType', 'GetSpecTypeId']:
        if hasattr(definition, method_name):
            try:
                forge_id = getattr(definition, method_name)()
                resolved = _resolve_param_type_from_spec(forge_id)
                if resolved:
                    return resolved
            except Exception:
                pass

    # 2. 尝试旧版 ParameterType
    if hasattr(definition, 'ParameterType'):
        try:
            resolved = _resolve_param_type_from_enum(definition.ParameterType)
            if resolved:
                return resolved
        except Exception:
            pass

    return PT_TEXT


def _get_storage_type_str(storage_type):
    if storage_type == StorageType.String:
        return STORAGE_STRING
    elif storage_type == StorageType.Integer:
        return STORAGE_INTEGER
    elif storage_type == StorageType.Double:
        return STORAGE_DOUBLE
    elif storage_type == StorageType.ElementId:
        return STORAGE_ELEMENTID
    return STORAGE_NONE


def _get_param_group_name(definition):
    """获取参数分组的友好显示名称"""
    if definition is None:
        return '常用'

    # 1. 尝试旧版 ParameterGroup
    try:
        pg = definition.ParameterGroup
        if pg is not None:
            pg_str = str(pg)
            group_labels = {
                'PG_DATA': '数据',
                'PG_TEXT': '文字',
                'PG_IDENTITY_DATA': '标识数据',
                'PG_CONSTRUCTION': '构造',
                'PG_GEOMETRY': '几何图形',
                'PG_MATERIALS': '材质和装饰',
                'PG_GRAPHICS': '图形',
                'PG_CONSTRAINTS': '约束',
                'PG_PHASING': '阶段化',
                'PG_GENERAL': '常规',
                'PG_OTHER': '其他',
                'INVALID': '其他',
            }
            return group_labels.get(pg_str, pg_str.replace('PG_', ''))
    except Exception:
        pass

    # 2. 尝试新版 GetGroupTypeId()
    try:
        if hasattr(definition, 'GetGroupTypeId'):
            gt = definition.GetGroupTypeId()
            if gt is not None:
                gt_str = str(gt)
                return gt_str.split('/')[-1].split(':')[-1]
    except Exception:
        pass

    return '其他'


class RevitHostAdapter(object):
    """Revit 宿主适配器，提供完整的项目参数扫描、转共享参数及数值修改接口"""

    def __init__(self, doc=None, uiapp=None):
        if doc is not None:
            self.doc = doc
            self.app = doc.Application
        else:
            try:
                from pyrevit import revit
                self.doc = revit.doc
                self.app = revit.doc.Application if revit.doc else None
            except Exception:
                self.doc = None
                self.app = None

    @property
    def is_valid_doc(self):
        return self.doc is not None and self.doc.IsValidObject

    @property
    def document_title(self):
        if not self.is_valid_doc:
            return '未连接文档'
        try:
            return self.doc.Title
        except Exception:
            return '活动文档'

    @property
    def document_path(self):
        if not self.is_valid_doc:
            return ''
        try:
            path = self.doc.PathName
            return path if path else '未保存的本地项目'
        except Exception:
            return ''

    # ------------------------------------------------------------------
    # 1. 提取当前打开项目的所有项目参数
    # ------------------------------------------------------------------
    def extract_all_parameters(self):
        """扫描并提取当前文档中的全部参数（普通项目参数、共享参数、内置参数）"""
        if not self.is_valid_doc:
            return []

        items = []
        seen_names = set()
        index = 1

        # A. 从 doc.ParameterBindings (BindingMap) 中提取所有项目绑定参数
        try:
            binding_map = self.doc.ParameterBindings
            iterator = binding_map.ForwardIterator()
            while iterator.MoveNext():
                try:
                    defn = iterator.Key
                    binding = iterator.Current
                    if defn is None or not defn.Name:
                        continue

                    name = defn.Name
                    seen_names.add(name)

                    # 判断是否为共享参数
                    is_shared = False
                    guid_str = ''
                    if hasattr(defn, 'GUID'):
                        try:
                            g = defn.GUID
                            if g and str(g) != '00000000-0000-0000-0000-000000000000':
                                is_shared = True
                                guid_str = str(g)
                        except Exception:
                            pass

                    # 如果没有直接 GUID，通过 SharedParameterElement 进一步检测
                    if not is_shared:
                        try:
                            spe = FilteredElementCollector(self.doc)\
                                .OfClass(SharedParameterElement)\
                                .WhereElementIsNotElementType()
                            for sp in spe:
                                if sp.GetDefinition() and sp.GetDefinition().Name == name:
                                    is_shared = True
                                    guid_str = str(sp.GuidValue)
                                    break
                        except Exception:
                            pass

                    nature = NATURE_SHARED if is_shared else NATURE_PROJECT
                    param_type = _get_definition_param_type(defn)
                    group_name = _get_param_group_name(defn)

                    # 作用范围与关联类别
                    scope_type = 'instance'
                    categories = []
                    if isinstance(binding, TypeBinding):
                        scope_type = 'type'
                    elif isinstance(binding, InstanceBinding):
                        scope_type = 'instance'

                    if binding and binding.Categories:
                        cat_enum = binding.Categories.GetEnumerator()
                        while cat_enum.MoveNext():
                            cat = cat_enum.Current
                            if cat:
                                categories.append(cat.Name)

                    # 判定是否包含项目信息
                    is_project_info_bound = ('项目信息' in categories or 'Project Information' in categories)
                    if is_project_info_bound and len(categories) == 1:
                        scope_type = 'project_info'

                    # 获取当前数值与存储类型
                    storage_type, raw_val, val_text, is_readonly = self._inspect_param_value(name, binding, categories)

                    item = ProjectParamItem(
                        index=index,
                        name=name,
                        nature=nature,
                        param_type=param_type,
                        storage_type=storage_type,
                        group_name=group_name,
                        scope_type=scope_type,
                        categories=categories,
                        guid=guid_str,
                        value_text=val_text,
                        raw_value=raw_val,
                        is_readonly=is_readonly,
                        element_count=len(categories)
                    )
                    item.native_definition = defn
                    item.native_binding = binding
                    items.append(item)
                    index += 1
                except Exception:
                    continue
        except Exception:
            pass

        # B. 从 doc.ProjectInformation 提取项目级参数（补充系统内置参数）
        try:
            proj_info = self.doc.ProjectInformation
            if proj_info:
                for p in proj_info.Parameters:
                    try:
                        p_defn = p.Definition
                        if not p_defn or not p_defn.Name:
                            continue
                        name = p_defn.Name
                        if name in seen_names:
                            continue
                        seen_names.add(name)

                        # 判断是否为共享参数或系统内置参数
                        is_shared = False
                        guid_str = ''
                        try:
                            if p.IsShared:
                                is_shared = True
                                if hasattr(p_defn, 'GUID'):
                                    guid_str = str(p_defn.GUID)
                        except Exception:
                            pass

                        builtin_name = ''
                        if not is_shared:
                            try:
                                builtin_name = _get_builtin_enum_name(p.Id.IntegerValue)
                            except Exception:
                                pass

                        nature = NATURE_SHARED if is_shared else (NATURE_BUILTIN if builtin_name else NATURE_PROJECT)
                        param_type = _get_definition_param_type(p_defn)
                        storage_type = _get_storage_type_str(p.StorageType)
                        group_name = _get_param_group_name(p_defn)
                        raw_val = self._extract_raw_value(p)
                        val_text = to_display_text(param_type, storage_type, raw_val, p.HasValue)
                        is_readonly = bool(p.IsReadOnly)
                        display_name = normalize_builtin_display_name(name, builtin_name)

                        item = ProjectParamItem(
                            index=index,
                            name=display_name,
                            nature=nature,
                            param_type=param_type,
                            storage_type=storage_type,
                            group_name=group_name,
                            scope_type='project_info',
                            categories=['项目信息'],
                            guid=guid_str,
                            value_text=val_text,
                            raw_value=raw_val,
                            is_readonly=is_readonly,
                            builtin_name=builtin_name,
                            element_count=1
                        )
                        item.native_definition = p_defn
                        items.append(item)
                        index += 1
                    except Exception:
                        continue
        except Exception:
            pass

        return items

    def _inspect_param_value(self, param_name, binding, categories):
        """探测参数的当前数值、存储类型和只读属性"""
        storage_type = STORAGE_STRING
        raw_val = None
        val_text = ''
        is_readonly = False

        # 优先在项目信息中寻找
        try:
            proj_info = self.doc.ProjectInformation
            if proj_info:
                p = proj_info.LookupParameter(param_name)
                if p:
                    storage_type = _get_storage_type_str(p.StorageType)
                    raw_val = self._extract_raw_value(p)
                    param_type = _get_definition_param_type(p.Definition)
                    val_text = to_display_text(param_type, storage_type, raw_val, p.HasValue)
                    is_readonly = bool(p.IsReadOnly)
                    return storage_type, raw_val, val_text, is_readonly
        except Exception:
            pass

        # 若未在项目信息中找到，在绑定类别的第一批图元中探测
        try:
            if binding and binding.Categories:
                cat_enum = binding.Categories.GetEnumerator()
                while cat_enum.MoveNext():
                    cat = cat_enum.Current
                    if not cat:
                        continue
                    collector = FilteredElementCollector(self.doc).OfCategoryId(cat.Id)
                    if isinstance(binding, TypeBinding):
                        collector = collector.WhereElementIsElementType()
                    else:
                        collector = collector.WhereElementIsNotElementType()
                    elem = collector.FirstElement()
                    if elem:
                        p = elem.LookupParameter(param_name)
                        if p:
                            storage_type = _get_storage_type_str(p.StorageType)
                            raw_val = self._extract_raw_value(p)
                            param_type = _get_definition_param_type(p.Definition)
                            val_text = to_display_text(param_type, storage_type, raw_val, p.HasValue)
                            is_readonly = bool(p.IsReadOnly)
                            return storage_type, raw_val, val_text, is_readonly
        except Exception:
            pass

        return storage_type, raw_val, val_text, is_readonly

    def _extract_raw_value(self, param):
        """从 Parameter 对象中安全提取底层数值"""
        try:
            if not param.HasValue:
                return None
            st = param.StorageType
            if st == StorageType.String:
                return param.AsString()
            elif st == StorageType.Integer:
                return param.AsInteger()
            elif st == StorageType.Double:
                return param.AsDouble()
            elif st == StorageType.ElementId:
                eid = param.AsElementId()
                return eid.IntegerValue if eid else None
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # 2. 共享参数文件智能保障
    # ------------------------------------------------------------------
    def ensure_shared_parameter_file(self):
        """确保 Revit 配置了有效的共享参数文件；若无则自动在 AppData 创建标准文件"""
        try:
            current_path = self.app.SharedParametersFilename
            if current_path and os.path.isfile(current_path):
                def_file = self.app.OpenSharedParameterFile()
                if def_file is not None:
                    return current_path, def_file

            # 自动创建默认 OmniMetro 共享参数文件
            app_data = os.environ.get('APPDATA') or os.path.expanduser('~')
            omni_dir = os.path.join(app_data, 'OmniMetro', 'SharedParams')
            if not os.path.isdir(omni_dir):
                os.makedirs(omni_dir)

            default_path = os.path.join(omni_dir, 'OmniMetro_ProjectParams_Shared.txt')
            if not os.path.isfile(default_path) or os.path.getsize(default_path) == 0:
                header = (
                    "# This is a Revit shared parameter file.\n"
                    "# Do not edit manually.\n"
                    "*META\tVERSION\tMINVERSION\n"
                    "META\t2\t1\n"
                    "*GROUP\tID\tNAME\n"
                    "*PARAM\tGUID\tNAME\tDATATYPE\tDATACAT\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE\n"
                )
                with codecs.open(default_path, 'w', 'utf-8') as f:
                    f.write(header)

            self.app.SharedParametersFilename = default_path
            def_file = self.app.OpenSharedParameterFile()
            if def_file is None:
                raise RuntimeError('OpenSharedParameterFile 返回空对象: {0}'.format(default_path))
            return default_path, def_file
        except Exception as ex:
            raise RuntimeError('无法初始化共享参数文件: {0}'.format(_safe_str(ex)))

    # ------------------------------------------------------------------
    # 3. 一键/批量将普通项目参数无损转化为共享参数
    # ------------------------------------------------------------------
    def convert_project_parameters_to_shared(self, param_items):
        """
        将所选普通项目参数批量转换为共享参数：
        1. 遍历图元并暂存已有参数值
        2. 在共享参数文件中创建 ExternalDefinition
        3. 在事务中移除旧绑定、插入新共享参数绑定
        4. 完整回写暂存值至所有受影响图元
        """
        if not self.is_valid_doc:
            return 0, '无效的 Revit 文档'

        sp_path, def_file = self.ensure_shared_parameter_file()
        if not def_file:
            return 0, '无法打开共享参数文件'

        # 获取或创建分组
        group_name = 'OmniMetro_ProjectParams'
        group = def_file.Groups.get_Item(group_name)
        if not group:
            try:
                group = def_file.Groups.Create(group_name)
            except Exception:
                group = def_file.Groups.get_Item(0) if def_file.Groups.Size > 0 else None

        if not group:
            return 0, '无法在共享参数文件中创建参数分组'

        success_count = 0
        error_messages = []

        # 逐个处理参数转化
        for item in param_items:
            if not item.can_convert or item.nature != NATURE_PROJECT:
                continue

            param_name = item.name
            defn = item.native_definition
            binding = item.native_binding

            if not defn or not binding:
                continue

            try:
                # 步骤 1: 扫描并暂存全模型受影响图元的已有参数值
                collected_values = {}  # {ElementId: (StorageType, raw_val)}
                if binding.Categories:
                    cat_enum = binding.Categories.GetEnumerator()
                    while cat_enum.MoveNext():
                        cat = cat_enum.Current
                        if not cat:
                            continue
                        collector = FilteredElementCollector(self.doc).OfCategoryId(cat.Id)
                        if isinstance(binding, TypeBinding):
                            collector = collector.WhereElementIsElementType()
                        else:
                            collector = collector.WhereElementIsNotElementType()

                        for elem in collector:
                            try:
                                p = elem.LookupParameter(param_name)
                                if p and p.HasValue:
                                    val = self._extract_raw_value(p)
                                    if val is not None:
                                        collected_values[elem.Id] = (p.StorageType, val)
                            except Exception:
                                continue

                # 步骤 2: 在共享参数文件中创建/获取 ExternalDefinition
                ext_defn = group.Definitions.get_Item(param_name)
                new_guid = None
                if ext_defn is None:
                    # 获取创建参数类型
                    creation_type = self._get_creation_param_type(item.param_type)
                    opt = ExternalDefinitionCreationOptions(param_name, creation_type)
                    opt.UserModifiable = True
                    opt.Visible = True
                    ext_defn = group.Definitions.Create(opt)
                    new_guid = ext_defn.GUID
                else:
                    new_guid = ext_defn.GUID

                # 步骤 3 & 4: 事务内替换绑定并回写原有数值
                group_id_to_insert = self._get_insert_group(defn)
                with Transaction(self.doc, '参数转共享: {0}'.format(param_name)) as trans:
                    trans.Start()

                    # 移除旧的项目参数绑定
                    self.doc.ParameterBindings.Remove(defn)

                    # 插入新的共享参数绑定 (保持原有类别集合与实例/类型设置)
                    inserted = self.doc.ParameterBindings.Insert(ext_defn, binding, group_id_to_insert)
                    if not inserted:
                        # 尝试 ReInsert
                        self.doc.ParameterBindings.ReInsert(ext_defn, binding, group_id_to_insert)

                    # 回写暂存的数值
                    restored_count = 0
                    for elem_id, (st_type, val) in collected_values.items():
                        try:
                            elem = self.doc.GetElement(elem_id)
                            if elem:
                                new_p = elem.LookupParameter(param_name)
                                if new_p and not new_p.IsReadOnly:
                                    self._set_param_value(new_p, st_type, val)
                                    restored_count += 1
                        except Exception:
                            continue

                    trans.Commit()

                item.mark_converted(str(new_guid))
                item.native_definition = ext_defn
                success_count += 1

            except Exception as ex:
                err = '参数 [{0}] 转化失败: {1}'.format(param_name, _safe_str(ex))
                item.convert_status = 'failed'
                item.convert_message = _safe_str(ex)
                error_messages.append(err)

        summary_msg = '成功将 {0} 个项目参数转化为共享参数！'.format(success_count)
        if error_messages:
            summary_msg += '\n部分异常: ' + '; '.join(error_messages[:3])
        return success_count, summary_msg

    def _get_creation_param_type(self, param_type):
        """获取创建 ExternalDefinition 所需的参数类型对象（适配旧版 ParameterType 与新版 SpecTypeId）"""
        if SpecTypeId is not None:
            spec_map = {
                PT_TEXT: SpecTypeId.String.Text,
                PT_INTEGER: SpecTypeId.Int.Integer,
                PT_NUMBER: SpecTypeId.Number,
                PT_YESNO: SpecTypeId.Boolean.YesNo,
                PT_LENGTH: SpecTypeId.Length,
                PT_AREA: SpecTypeId.Area,
                PT_VOLUME: SpecTypeId.Volume,
                PT_ANGLE: SpecTypeId.Angle,
            }
            return spec_map.get(param_type, SpecTypeId.String.Text)

        if RevitParameterType is not None:
            type_map = {
                PT_TEXT: RevitParameterType.Text,
                PT_INTEGER: RevitParameterType.Integer,
                PT_NUMBER: RevitParameterType.Number,
                PT_YESNO: RevitParameterType.YesNo,
                PT_LENGTH: RevitParameterType.Length,
                PT_AREA: RevitParameterType.Area,
                PT_VOLUME: RevitParameterType.Volume,
                PT_ANGLE: RevitParameterType.Angle,
            }
            return type_map.get(param_type, RevitParameterType.Text)

        return None

    def _get_insert_group(self, definition):
        """获取插入 ParameterBindings 时所需的分组参数"""
        try:
            if hasattr(definition, 'GetGroupTypeId') and GroupTypeId is not None:
                gt = definition.GetGroupTypeId()
                if gt:
                    return gt
        except Exception:
            pass

        try:
            if hasattr(definition, 'ParameterGroup') and RevitBuiltInParameterGroup is not None:
                pg = definition.ParameterGroup
                if pg:
                    return pg
        except Exception:
            pass

        if RevitBuiltInParameterGroup is not None:
            return RevitBuiltInParameterGroup.PG_DATA
        if GroupTypeId is not None:
            return GroupTypeId.Data
        return None

    # ------------------------------------------------------------------
    # 4. 批量保存参数数值修改
    # ------------------------------------------------------------------
    def save_parameter_values(self, modified_items):
        """将用户在表中修改的参数数值批量提交写入 Revit 模型"""
        if not self.is_valid_doc or not modified_items:
            return 0, '没有需要保存的数值修改'

        updated_count = 0
        errors = []

        with Transaction(self.doc, '批量修改项目参数数值') as trans:
            trans.Start()

            for item in modified_items:
                if item.is_readonly:
                    continue

                raw_val, is_valid, err = parse_display_to_raw(item.param_type, item.storage_type, item.current_value)
                if not is_valid:
                    errors.append('{0}: {1}'.format(item.name, err))
                    continue

                success = False
                # A. 写入 ProjectInformation
                try:
                    proj_info = self.doc.ProjectInformation
                    if proj_info:
                        p = proj_info.LookupParameter(item.name)
                        if p and not p.IsReadOnly:
                            self._set_param_value_raw(p, item.param_type, item.storage_type, raw_val)
                            success = True
                except Exception:
                    pass

                # B. 写入绑定类别的所有图元
                if not success and item.native_binding and item.native_binding.Categories:
                    try:
                        binding = item.native_binding
                        cat_enum = binding.Categories.GetEnumerator()
                        while cat_enum.MoveNext():
                            cat = cat_enum.Current
                            if not cat:
                                continue
                            collector = FilteredElementCollector(self.doc).OfCategoryId(cat.Id)
                            if isinstance(binding, TypeBinding):
                                collector = collector.WhereElementIsElementType()
                            else:
                                collector = collector.WhereElementIsNotElementType()

                            for elem in collector:
                                p = elem.LookupParameter(item.name)
                                if p and not p.IsReadOnly:
                                    self._set_param_value_raw(p, item.param_type, item.storage_type, raw_val)
                                    success = True
                    except Exception as ex:
                        errors.append('{0} 写入图元异常: {1}'.format(item.name, _safe_str(ex)))

                if success:
                    item.mark_value_saved()
                    updated_count += 1

            trans.Commit()

        msg = '成功保存 {0} 项参数数值！'.format(updated_count)
        if errors:
            msg += '\n异常项: ' + '; '.join(errors[:2])
        return updated_count, msg

    def _set_param_value_raw(self, param, param_type, storage_type, raw_val):
        """根据存储类型向 Parameter 写入原生数值"""
        if raw_val is None:
            return
        if storage_type == STORAGE_STRING or param.StorageType == StorageType.String:
            param.Set(unicode(raw_val))
        elif storage_type == STORAGE_INTEGER or param.StorageType == StorageType.Integer:
            param.Set(int(raw_val))
        elif storage_type == STORAGE_DOUBLE or param.StorageType == StorageType.Double:
            param.Set(float(raw_val))

    def _set_param_value(self, param, storage_type, raw_val):
        """根据 StorageType 枚举向 Parameter 写入数值"""
        if raw_val is None:
            return
        if storage_type == StorageType.String:
            param.Set(unicode(raw_val))
        elif storage_type == StorageType.Integer:
            param.Set(int(raw_val))
        elif storage_type == StorageType.Double:
            param.Set(float(raw_val))
        elif storage_type == StorageType.ElementId and isinstance(raw_val, int):
            param.Set(ElementId(raw_val))
