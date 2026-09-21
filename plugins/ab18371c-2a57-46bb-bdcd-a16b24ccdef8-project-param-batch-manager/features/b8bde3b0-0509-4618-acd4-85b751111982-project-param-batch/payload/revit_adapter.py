# -*- coding: utf-8 -*-
"""
工具名称: 项目参数批量管理器 - 宿主 API 适配层
功能描述: 封装所有 Revit API 读写与事务操作（打开文档、提取基点与项目参数、
          新增项目参数、批量写入参数并保存）。未来平移平台时仅需重写本层。
架构规范: 三层解耦标准 (UI层 -> 核心算法层 -> 宿主适配层)
兼容性: Revit 2018 - 2026（新版本中 ParameterType / BuiltInParameterGroup
        已被移除，自动切换至 SpecTypeId / GroupTypeId (ForgeTypeId) 体系）
"""

import clr
import os

clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import (
    BasePoint,
    BuiltInCategory,
    BuiltInParameter,
    CategorySet,
    DetachFromCentralOption,
    ElementId,
    FilteredElementCollector,
    InstanceBinding,
    ModelPathUtils,
    OpenOptions,
    StorageType,
    Transaction,
    XYZ,
)

# ----------------------------------------------------------------------
# 版本兼容：ParameterType / BuiltInParameterGroup 在较新 Revit 中被移除，
# 需安全导入，失败时切换到 SpecTypeId / GroupTypeId (ForgeTypeId) 体系。
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
    CONVERTERS,
    PT_ANGLE,
    PT_AREA,
    PT_INTEGER,
    PT_LENGTH,
    PT_NUMBER,
    PT_TEXT,
    PT_VOLUME,
    PT_YESNO,
    STORAGE_DOUBLE,
    STORAGE_ELEMENTID,
    STORAGE_INTEGER,
    STORAGE_NONE,
    STORAGE_STRING,
    FileParamData,
    ParamInfo,
    normalize_builtin_display_name,
    to_display_text,
)


# Revit API 兼容：部分版本不再暴露 ParameterType，不能在模块加载阶段直接引用未定义名称
_PARAMETER_TYPE_CLASS = RevitParameterType
_ANGLE_PARAM_TYPE = getattr(_PARAMETER_TYPE_CLASS, 'Angle', None) if _PARAMETER_TYPE_CLASS is not None else None

# 参数类型标识映射（Revit ParameterType 字符串名 -> core 标识）
PARAM_TYPE_MAP = {
    'Text': PT_TEXT,
    'Integer': PT_INTEGER,
    'Number': PT_NUMBER,
    'YesNo': PT_YESNO,
    'Length': PT_LENGTH,
    'Area': PT_AREA,
    'Volume': PT_VOLUME,
    'Angle': PT_ANGLE,
}

# 存储类型标识映射（Revit StorageType -> core 标识）
STORAGE_TYPE_MAP = {
    'None': STORAGE_NONE,
    'Integer': STORAGE_INTEGER,
    'Double': STORAGE_DOUBLE,
    'String': STORAGE_STRING,
    'ElementId': STORAGE_ELEMENTID,
}

# 新建参数时：core 类型标识 -> Revit 参数类型对象（旧版 ParameterType / 新版 SpecTypeId）
NEW_PARAM_TYPE_TO_REVIT = {}
if RevitParameterType is not None:
    NEW_PARAM_TYPE_TO_REVIT = {
        PT_TEXT: RevitParameterType.Text,
        PT_INTEGER: RevitParameterType.Integer,
        PT_NUMBER: RevitParameterType.Number,
        PT_YESNO: RevitParameterType.YesNo,
        PT_LENGTH: RevitParameterType.Length,
        PT_AREA: RevitParameterType.Area,
        PT_VOLUME: RevitParameterType.Volume,
        PT_ANGLE: RevitParameterType.Angle,
    }
elif SpecTypeId is not None:
    NEW_PARAM_TYPE_TO_REVIT = {
        PT_TEXT: SpecTypeId.String.Text,
        PT_INTEGER: SpecTypeId.Int.Integer,
        PT_NUMBER: SpecTypeId.Number,
        PT_YESNO: SpecTypeId.Boolean.YesNo,
        PT_LENGTH: SpecTypeId.Length,
        PT_AREA: SpecTypeId.Area,
        PT_VOLUME: SpecTypeId.Volume,
        PT_ANGLE: SpecTypeId.Angle,
    }

# 新建参数时：分组标识 -> Revit 分组对象（旧版 BuiltInParameterGroup / 新版 GroupTypeId）
NEW_PARAM_GROUP_TO_REVIT = {}
if RevitBuiltInParameterGroup is not None:
    NEW_PARAM_GROUP_TO_REVIT = {
        'PG_DATA': RevitBuiltInParameterGroup.PG_DATA,
        'PG_TEXT': RevitBuiltInParameterGroup.PG_TEXT,
        'PG_CONSTRUCTION': RevitBuiltInParameterGroup.PG_CONSTRUCTION,
        'PG_GEOMETRY': RevitBuiltInParameterGroup.PG_GEOMETRY,
        'PG_IDENTITY_DATA': RevitBuiltInParameterGroup.PG_IDENTITY_DATA,
        'PG_OTHER': RevitBuiltInParameterGroup.PG_OTHER,
    }
elif GroupTypeId is not None:
    NEW_PARAM_GROUP_TO_REVIT = {
        'PG_DATA': GroupTypeId.Data,
        'PG_TEXT': GroupTypeId.Text,
        'PG_CONSTRUCTION': GroupTypeId.Construction,
        'PG_GEOMETRY': GroupTypeId.Geometry,
        'PG_IDENTITY_DATA': GroupTypeId.IdentityData,
        'PG_OTHER': GroupTypeId.Other,
    }

# 内置参数枚举名缓存（enum值 -> 枚举名字符串）
_BUILTIN_ENUM_CACHE = {}


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------
def get_builtin_enum_name(builtin_enum_value):
    """内置参数枚举值 -> 枚举名称字符串（如 -1005300 -> 'PROJECT_NUMBER'）。"""
    if builtin_enum_value in _BUILTIN_ENUM_CACHE:
        return _BUILTIN_ENUM_CACHE[builtin_enum_value]
    try:
        for name in dir(BuiltInParameter):
            if not name.startswith('_') and name.isupper():
                try:
                    if int(getattr(BuiltInParameter, name)) == int(builtin_enum_value):
                        _BUILTIN_ENUM_CACHE[builtin_enum_value] = name
                        return name
                except Exception:
                    pass
    except Exception:
        pass
    _BUILTIN_ENUM_CACHE[builtin_enum_value] = ''
    return ''


def get_param_type_name(param):
    """Parameter 对象 -> 参数类型标识（text/integer/...），异常时兜底按存储类型判断。"""
    try:
        defn = param.Definition
        if defn is None:
            return ''
        # 新版 Revit (2024+)：InternalDefinition.ParameterType 可能不可用，
        # 优先尝试 GetSpecTypeId() 返回 ForgeTypeId
        try:
            spec = defn.GetSpecTypeId()
            if spec is not None and SpecTypeId is not None:
                tid = str(spec)
                spec_map = {
                    str(SpecTypeId.String.Text): PT_TEXT,
                    str(SpecTypeId.Int.Integer): PT_INTEGER,
                    str(SpecTypeId.Number): PT_NUMBER,
                    str(SpecTypeId.Boolean.YesNo): PT_YESNO,
                    str(SpecTypeId.Length): PT_LENGTH,
                    str(SpecTypeId.Area): PT_AREA,
                    str(SpecTypeId.Volume): PT_VOLUME,
                    str(SpecTypeId.Angle): PT_ANGLE,
                }
                if tid in spec_map:
                    return spec_map[tid]
        except Exception:
            pass
        # 旧版 Revit：ParameterType 属性
        ptype = getattr(defn, 'ParameterType', None)
        if ptype is not None:
            ptype_name = str(ptype)
            if ptype_name in PARAM_TYPE_MAP:
                return PARAM_TYPE_MAP[ptype_name]
        # 兜底：按存储类型推断
        storage_name = str(param.StorageType)
        if storage_name == 'String':
            return PT_TEXT
        if storage_name == 'Integer':
            return 'integer'
        if storage_name == 'Double':
            return 'number'
        return ''
    except Exception:
        return ''


def get_storage_type_name(param):
    """Parameter 对象 -> 存储类型标识（string/integer/double/elementid/none）。"""
    try:
        return STORAGE_TYPE_MAP.get(str(param.StorageType), STORAGE_NONE)
    except Exception:
        return STORAGE_NONE


def get_param_raw_value(param, param_type):
    """提取参数的原始值（保持宿主单位）。"""
    try:
        if not param.HasValue:
            return None
        storage_name = str(param.StorageType)
        if storage_name == 'String':
            return param.AsString()
        if storage_name == 'Integer':
            return param.AsInteger()
        if storage_name == 'Double':
            return param.AsDouble()
        if storage_name == 'ElementId':
            return param.AsElementId().IntegerValue
        return None
    except Exception:
        return None


def get_basepoint_param(base_point, builtin_param, fallback_names):
    """获取基点参数，优先使用 BuiltInParameter，失败时按名称回退。"""
    if builtin_param is not None:
        try:
            param = base_point.get_Parameter(builtin_param)
            if param is not None:
                return param
        except Exception:
            pass
    for name in fallback_names:
        try:
            param = base_point.LookupParameter(name)
            if param is not None:
                return param
        except Exception:
            continue
    return None


def get_angle_param(base_point):
    """获取项目基点的「到正北角度」参数对象。"""
    p = get_basepoint_param(
        base_point,
        getattr(BuiltInParameter, 'BASEPOINT_ANGLETONORTH_PARAM', None),
        [u'Angle to True North', u'Angle to North',
         u'正北角度', u'与正北夹角', u'与正北方向夹角', u'正北方向角度'])
    if p is not None:
        return p

    # 遍历基点全部参数：名称关键字 + 类型匹配
    params_list = list(base_point.Parameters)
    for p in params_list:
        try:
            name_lower = p.Definition.Name.lower()
            is_angle_type = (_ANGLE_PARAM_TYPE is not None and
                             p.Definition.ParameterType == _ANGLE_PARAM_TYPE)
            has_keyword = any(kw in name_lower for kw in ('angle', 'north', 'true', '北', '角度', '正北'))
            if is_angle_type and has_keyword:
                return p
        except Exception:
            continue

    # 仅按类型匹配（Angle 类型）
    if _ANGLE_PARAM_TYPE is not None:
        for p in params_list:
            try:
                if p.Definition.ParameterType == _ANGLE_PARAM_TYPE:
                    return p
            except Exception:
                continue

    # 仅按名称关键字匹配（兜底）
    for p in params_list:
        try:
            name_lower = p.Definition.Name.lower()
            if any(kw in name_lower for kw in ('angle', 'north', 'true', '北', '角度', '正北')):
                return p
        except Exception:
            continue

    return None


def get_angle_to_true_north(doc, base_point):
    """获取项目到正北的角度（返回度数）。"""
    import math
    p_ang = get_angle_param(base_point)
    if p_ang is not None:
        try:
            return math.degrees(p_ang.AsDouble())
        except Exception:
            pass
    try:
        proj_pos = doc.ActiveProjectLocation.GetProjectPosition(XYZ(0.0, 0.0, 0.0))
        return math.degrees(proj_pos.Angle)
    except Exception:
        return 0.0


# ----------------------------------------------------------------------
# 宿主适配器
# ----------------------------------------------------------------------
class RevitHostAdapter(object):
    """项目参数批量管理器的 Revit 宿主适配器。"""

    def __init__(self, app):
        self.app = app

    # -- 文档打开/关闭 -------------------------------------------------
    def _find_opened_doc(self, file_path):
        for d in self.app.Documents:
            try:
                if os.path.normpath(d.PathName).lower() == os.path.normpath(file_path).lower():
                    return d
            except Exception:
                continue
        return None

    def _open_doc(self, file_path):
        """打开文档；若已打开则复用。返回 (doc, is_already_opened)。"""
        opened = self._find_opened_doc(file_path)
        if opened is not None:
            return opened, True
        opt = OpenOptions()
        try:
            opt.DetachFromCentralOption = DetachFromCentralOption.DetachAndPreserveWorksets
        except Exception:
            pass
        m_path = ModelPathUtils.ConvertUserVisiblePathToModelPath(file_path)
        return self.app.OpenDocumentFile(m_path, opt), False

    def _close_doc(self, doc, is_already_opened):
        """关闭文档（仅关闭本次新打开的）。"""
        if doc is not None and not is_already_opened:
            try:
                doc.Close(False)
            except Exception:
                pass

    # -- 提取 ----------------------------------------------------------
    def extract_file_data(self, file_path, file_name):
        """提取单个 Revit 文件的基点 + 项目参数。返回 FileParamData。"""
        result = FileParamData(file_path, file_name)
        doc = None
        is_opened = False
        try:
            doc, is_opened = self._open_doc(file_path)

            # 1) 项目基点
            pbp = FilteredElementCollector(doc)\
                .OfCategory(BuiltInCategory.OST_ProjectBasePoint)\
                .WhereElementIsNotElementType()\
                .FirstElement()
            if pbp is not None:
                p_ns = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM,
                                           [u'N/S', u'North/South', u'北/南', u'南北'])
                p_ew = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_EASTWEST_PARAM,
                                           [u'E/W', u'East/West', u'东/西', u'东西'])
                p_elev = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_ELEVATION_PARAM,
                                             [u'Elev', u'Elevation', u'高程', u'标高'])
                result.base_point['ns'] = round(self._ft_to_mm(p_ns.AsDouble()), 3) if p_ns else None
                result.base_point['ew'] = round(self._ft_to_mm(p_ew.AsDouble()), 3) if p_ew else None
                result.base_point['elev'] = round(self._ft_to_mm(p_elev.AsDouble()), 3) if p_elev else None
                result.base_point['angle'] = round(get_angle_to_true_north(doc, pbp), 3)

            # 2) 项目参数（ProjectInformation 上的全部参数：内置 + 项目/共享）
            project_info = doc.ProjectInformation
            if project_info is not None:
                for p in project_info.Parameters:
                    try:
                        info = self._param_to_info(p)
                        if info is not None:
                            result.params.append(info)
                    except Exception:
                        continue

            result.ok = True
        except Exception as ex:
            result.ok = False
            result.error = u'{0}'.format(ex)
        finally:
            self._close_doc(doc, is_opened)
        return result

    def _param_to_info(self, param):
        """Parameter 对象 -> ParamInfo（仅保留可读的参数）。"""
        try:
            defn = param.Definition
            if defn is None:
                return None
            name = defn.Name
            if not name:
                return None
            param_type = get_param_type_name(param)
            storage_type = get_storage_type_name(param)
            is_shared = False
            try:
                is_shared = bool(param.IsShared)
            except Exception:
                pass
            builtin_name = ''
            if not is_shared:
                try:
                    builtin_name = get_builtin_enum_name(param.Id.IntegerValue)
                except Exception:
                    builtin_name = ''
            display_name = normalize_builtin_display_name(name, builtin_name)
            raw_value = get_param_raw_value(param, param_type)
            value_text = to_display_text(param_type, storage_type, raw_value,
                                         getattr(param, 'HasValue', False))
            is_readonly = False
            try:
                is_readonly = bool(param.IsReadOnly)
            except Exception:
                pass
            group_name = ''
            try:
                group_name = u'{0}'.format(defn.ParameterGroup)
            except Exception:
                pass
            return ParamInfo(
                name=name,
                builtin_name=builtin_name,
                param_type=param_type,
                storage_type=storage_type,
                display_name=display_name,
                value_text=value_text,
                raw_value=raw_value,
                has_value=bool(getattr(param, 'HasValue', False)),
                is_readonly=is_readonly,
                is_shared=is_shared,
                group_name=group_name,
            )
        except Exception:
            return None

    # -- 写入 ----------------------------------------------------------
    def write_param_values(self, file_path, file_name, target_values, progress_cb=None):
        """将目标值写入单个文件的项目参数。
        target_values: {参数名: (param_type, storage_type, display_text)}
        返回 (ok, message)。所有写入在一个事务中完成，失败自动回滚。
        """
        doc = None
        is_opened = False
        try:
            doc, is_opened = self._open_doc(file_path)
            if doc.IsReadOnly:
                return False, u'文件只读，无法写入'
            if doc.IsWorkshared and doc.IsDetached is False:
                # 工作共享文件需可编辑；Detach 打开的一般可写
                pass

            project_info = doc.ProjectInformation
            if project_info is None:
                return False, u'文档无项目信息'

            # 参数名 -> Parameter 对象（按名称匹配，兼容中英文版本）
            param_by_name = {}
            for p in project_info.Parameters:
                try:
                    if p.Definition is not None and p.Definition.Name:
                        param_by_name[p.Definition.Name] = p
                except Exception:
                    continue

            t = Transaction(doc, u'批量修改项目参数')
            t.Start()
            try:
                skipped = []
                for name, (param_type, storage_type, text) in target_values.items():
                    p = param_by_name.get(name)
                    if p is None:
                        skipped.append((name, u'参数不存在'))
                        continue
                    if p.IsReadOnly:
                        skipped.append((name, u'只读'))
                        continue
                    from core_business import from_display_text
                    ok, parsed = from_display_text(param_type, storage_type, text)
                    if not ok:
                        skipped.append((name, parsed))
                        continue
                    self._set_param_value(p, parsed)
                t.Commit()
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    try:
                        t.RollBack()
                    except Exception:
                        pass
                raise

            if not is_opened:
                try:
                    doc.Save()
                except Exception as ex:
                    return False, u'保存失败：{0}'.format(ex)

            if skipped:
                return True, u'写入完成（{0} 项跳过：{1}）'.format(
                    len(skipped), u'；'.join(u'{0}={1}'.format(n, r) for n, r in skipped))
            return True, u'写入完成'
        except Exception as ex:
            return False, u'{0}'.format(ex)
        finally:
            self._close_doc(doc, is_opened)

    def _set_param_value(self, param, parsed_value):
        """按存储类型写入参数值。"""
        storage_name = str(param.StorageType)
        if storage_name == 'String':
            param.Set(u'{0}'.format(parsed_value))
        elif storage_name == 'Integer':
            param.Set(int(parsed_value))
        elif storage_name == 'Double':
            param.Set(float(parsed_value))
        elif storage_name == 'ElementId':
            param.Set(ElementId(int(parsed_value)))
        else:
            raise Exception(u'不支持的参数存储类型: {0}'.format(storage_name))

    # -- 基点写入 ------------------------------------------------------
    def write_base_point(self, file_path, file_name, ns_mm, ew_mm, elev_mm, angle_deg):
        """批量修改项目基点。值以毫米/度传入。
        返回 (ok, message)。
        """
        doc = None
        is_opened = False
        try:
            doc, is_opened = self._open_doc(file_path)
            if doc.IsReadOnly:
                return False, u'文件只读，无法写入'

            pbp = FilteredElementCollector(doc)\
                .OfCategory(BuiltInCategory.OST_ProjectBasePoint)\
                .WhereElementIsNotElementType()\
                .FirstElement()
            if pbp is None:
                return False, u'无项目基点'

            p_ns = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM,
                                       [u'N/S', u'North/South', u'北/南', u'南北'])
            p_ew = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_EASTWEST_PARAM,
                                       [u'E/W', u'East/West', u'东/西', u'东西'])
            p_elev = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_ELEVATION_PARAM,
                                         [u'Elev', u'Elevation', u'高程', u'标高'])
            p_ang = get_angle_param(pbp)

            if not all([p_ns, p_ew, p_elev, p_ang]):
                return False, u'基点参数缺失'

            t = Transaction(doc, u'批量修改项目基点')
            t.Start()
            try:
                from core_business import MM_PER_FOOT
                if ns_mm is not None:
                    p_ns.Set(float(ns_mm) / MM_PER_FOOT)
                if ew_mm is not None:
                    p_ew.Set(float(ew_mm) / MM_PER_FOOT)
                if elev_mm is not None:
                    p_elev.Set(float(elev_mm) / MM_PER_FOOT)
                if angle_deg is not None and not p_ang.IsReadOnly:
                    import math
                    p_ang.Set(math.radians(float(angle_deg)))
                t.Commit()
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    try:
                        t.RollBack()
                    except Exception:
                        pass
                raise

            if not is_opened:
                try:
                    doc.Save()
                except Exception as ex:
                    return False, u'保存失败：{0}'.format(ex)
            return True, u'基点已更新'
        except Exception as ex:
            return False, u'{0}'.format(ex)
        finally:
            self._close_doc(doc, is_opened)

    # -- 组合更新（基点 + 参数，单次打开文档） --------------------------
    def apply_updates(self, file_path, file_name, base_updates, param_updates, progress_cb=None):
        """组合更新：base_updates = {ns/ew/elev/angle: 毫米/度 或 None}，
        param_updates = {参数名: (param_type, storage_type, display_text)}。
        返回 (ok, message)。
        """
        doc = None
        is_opened = False
        try:
            doc, is_opened = self._open_doc(file_path)
            if doc.IsReadOnly:
                return False, u'文件只读，无法写入'

            project_info = doc.ProjectInformation
            if project_info is None and param_updates:
                return False, u'文档无项目信息'

            t = Transaction(doc, u'批量修改项目参数')
            t.Start()
            skipped = []
            try:
                # 1) 基点
                if base_updates:
                    pbp = FilteredElementCollector(doc)\
                        .OfCategory(BuiltInCategory.OST_ProjectBasePoint)\
                        .WhereElementIsNotElementType()\
                        .FirstElement()
                    if pbp is not None:
                        p_ns = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM,
                                                   [u'N/S', u'North/South', u'北/南', u'南北'])
                        p_ew = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_EASTWEST_PARAM,
                                                   [u'E/W', u'East/West', u'东/西', u'东西'])
                        p_elev = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_ELEVATION_PARAM,
                                                     [u'Elev', u'Elevation', u'高程', u'标高'])
                        p_ang = get_angle_param(pbp)
                        from core_business import MM_PER_FOOT
                        if 'ns' in base_updates and base_updates['ns'] is not None and p_ns:
                            p_ns.Set(float(base_updates['ns']) / MM_PER_FOOT)
                        if 'ew' in base_updates and base_updates['ew'] is not None and p_ew:
                            p_ew.Set(float(base_updates['ew']) / MM_PER_FOOT)
                        if 'elev' in base_updates and base_updates['elev'] is not None and p_elev:
                            p_elev.Set(float(base_updates['elev']) / MM_PER_FOOT)
                        if 'angle' in base_updates and base_updates['angle'] is not None and p_ang and not p_ang.IsReadOnly:
                            import math
                            p_ang.Set(math.radians(float(base_updates['angle'])))
                    else:
                        skipped.append(u'无项目基点')

                # 2) 项目参数
                if param_updates:
                    param_by_name = {}
                    for p in project_info.Parameters:
                        try:
                            if p.Definition is not None and p.Definition.Name:
                                param_by_name[p.Definition.Name] = p
                        except Exception:
                            continue
                    from core_business import from_display_text
                    for name, (param_type, storage_type, text) in param_updates.items():
                        p = param_by_name.get(name)
                        if p is None:
                            skipped.append(u'{0} 不存在'.format(name))
                            continue
                        if p.IsReadOnly:
                            skipped.append(u'{0} 只读'.format(name))
                            continue
                        ok, parsed = from_display_text(param_type, storage_type, text)
                        if not ok:
                            skipped.append(u'{0} {1}'.format(name, parsed))
                            continue
                        self._set_param_value(p, parsed)

                t.Commit()
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    try:
                        t.RollBack()
                    except Exception:
                        pass
                raise

            if not is_opened:
                try:
                    doc.Save()
                except Exception as ex:
                    return False, u'保存失败：{0}'.format(ex)

            if skipped:
                return True, u'写入完成（跳过：{0}）'.format(u'；'.join(skipped))
            return True, u'写入完成'
        except Exception as ex:
            return False, u'{0}'.format(ex)
        finally:
            self._close_doc(doc, is_opened)

    # -- 新增项目参数 --------------------------------------------------
    def add_project_param(self, file_path, file_name, param_name, param_type_id,
                          group_id, progress_cb=None):
        """向单个文件新增一个项目参数（共享参数绑定到 ProjectInfo）。
        返回 (ok, message)。
        """
        doc = None
        is_opened = False
        try:
            doc, is_opened = self._open_doc(file_path)
            if doc.IsReadOnly:
                return False, u'文件只读，无法写入'

            # 确保共享参数文件存在
            spf = self._ensure_shared_param_file(doc.Application)
            if spf is None:
                return False, u'无法创建共享参数文件'

            t = Transaction(doc, u'新增项目参数')
            t.Start()
            try:
                # 1) 获取/创建共享参数组
                group_name = u'OmniMetro 项目参数'
                group = None
                for g in spf.Groups:
                    if g.Name == group_name:
                        group = g
                        break
                if group is None:
                    group = spf.Groups.Create(group_name)

                # 2) 若已存在同名参数，直接复用
                definition = None
                if group.Definitions.Contains(param_name):
                    definition = group.Definitions.get_Item(param_name)
                else:
                    revit_ptype = NEW_PARAM_TYPE_TO_REVIT.get(param_type_id)
                    if revit_ptype is None:
                        raise Exception(u'不支持的参数类型: {0}'.format(param_type_id))
                    definition = group.Definitions.Create(param_name, revit_ptype, True)

                # 3) 绑定到 ProjectInfo 类别
                if not NEW_PARAM_GROUP_TO_REVIT:
                    raise Exception(u'当前 Revit 版本不支持创建分组参数')
                revit_group = NEW_PARAM_GROUP_TO_REVIT.get(group_id)
                if revit_group is None:
                    revit_group = next(iter(NEW_PARAM_GROUP_TO_REVIT.values()))
                cat_set = doc.Application.Create.NewCategorySet()
                project_info_cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_ProjectInfo)
                cat_set.Insert(project_info_cat)
                binding = doc.Application.Create.NewInstanceBinding(cat_set)
                if not doc.ParameterBindings.Insert(definition, binding, revit_group):
                    # 已存在绑定则尝试替换
                    try:
                        doc.ParameterBindings.ReInsert(definition, binding, revit_group)
                    except Exception:
                        pass
                t.Commit()
            except Exception:
                if t.HasStarted() and not t.HasEnded():
                    try:
                        t.RollBack()
                    except Exception:
                        pass
                raise

            if not is_opened:
                try:
                    doc.Save()
                except Exception as ex:
                    return False, u'保存失败：{0}'.format(ex)
            return True, u'参数已添加'
        except Exception as ex:
            return False, u'{0}'.format(ex)
        finally:
            self._close_doc(doc, is_opened)

    def _ensure_shared_param_file(self, app):
        """确保有可用的共享参数文件；没有则在工作目录创建。返回 SharedParameterFile 或 None。"""
        try:
            spf = app.SharedParameterFile
            if spf is not None:
                return spf
        except Exception:
            spf = None

        # 创建默认共享参数文件（放置于用户临时目录，避免污染项目目录）
        default_dir = os.path.join(os.environ.get('TEMP', os.getcwd()), 'OmniMetro')
        try:
            if not os.path.isdir(default_dir):
                os.makedirs(default_dir)
        except Exception:
            default_dir = os.getcwd()
        spf_path = os.path.join(default_dir, 'OmniMetro_SharedParams.txt')
        try:
            if not os.path.isfile(spf_path):
                with open(spf_path, 'w') as f:
                    f.write('')
            app.SharedParameterFilename = spf_path
            return app.SharedParameterFile
        except Exception:
            return None

    # -- 单位换算 ------------------------------------------------------
    @staticmethod
    def _ft_to_mm(value):
        from core_business import MM_PER_FOOT
        return float(value) * MM_PER_FOOT
