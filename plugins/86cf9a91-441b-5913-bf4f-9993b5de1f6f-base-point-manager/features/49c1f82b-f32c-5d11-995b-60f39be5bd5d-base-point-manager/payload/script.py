# -*- coding: utf-8 -*-
import clr
import math
import os

# Revit API
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *

# pyRevit
from pyrevit import forms, script

# WPF
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
from System import EventHandler
from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
from System.Windows import Window
from System.Windows.Media import SolidColorBrush, Color

# --------------------------------------------------------------------------------
# 常量与工具函数
# --------------------------------------------------------------------------------
app = __revit__.Application
MM_PER_FOOT = 304.8

LIGHT_THEME = {
    "WindowBg": "#F5F6F7",
    "Surface": "#FFFFFF",
    "SurfaceAlt": "#F7FAFC",
    "Text": "#1F2937",
    "MutedText": "#718096",
    "Border": "#E2E8F0",
    "Primary": "#3182CE",
    "Secondary": "#4A5568",
    "Tertiary": "#718096",
    "Action": "#805AD5",
    "Success": "#38A169",
    "RowSuccess": "#E6FFFA",
    "RowError": "#FFF5F5",
    "RowBusy": "#EBF8FF",
    "Mismatch": "#FED7D7",
}

DARK_THEME = {
    "WindowBg": "#0F172A",
    "Surface": "#111827",
    "SurfaceAlt": "#1F2937",
    "Text": "#E5E7EB",
    "MutedText": "#9CA3AF",
    "Border": "#374151",
    "Primary": "#2563EB",
    "Secondary": "#475569",
    "Tertiary": "#64748B",
    "Action": "#7C3AED",
    "Success": "#059669",
    "RowSuccess": "#0F3D2E",
    "RowError": "#4C1D1D",
    "RowBusy": "#0C4A6E",
    "Mismatch": "#7F1D1D",
}


def color_from_hex(hex_value):
    if not hex_value:
        raise ValueError("颜色值不能为空。")
    value = hex_value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError("颜色值必须是 6 位十六进制，当前为: {}".format(hex_value))
    return Color.FromRgb(
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16)
    )


def brush_from_hex(hex_value):
    brush = SolidColorBrush(color_from_hex(hex_value))
    brush.Freeze()
    return brush


def get_omnimetro_theme_context():
    ctx = globals().get('__omnimetro__')
    if not isinstance(ctx, dict):
        return {"theme": u"浅色", "is_dark": False, "source": u"standalone"}
    theme = ctx.get('theme') or u'浅色'
    return {
        "theme": theme,
        "is_dark": bool(ctx.get('is_dark')) or theme == u'深色',
        "source": ctx.get('source') or u'OmniMetro',
    }

def ft_to_mm(value_ft):
    """Revit 内部单位英尺 → 毫米"""
    return float(value_ft) * MM_PER_FOOT

def mm_to_ft(value_mm):
    """毫米 → Revit 内部单位英尺"""
    return float(value_mm) / MM_PER_FOOT

def deg_to_rad(value_deg):
    """度 → 弧度 (Revit 角度内部单位)"""
    return math.radians(float(value_deg))

def rad_to_deg(value_rad):
    """弧度 → 度"""
    return math.degrees(float(value_rad))

def get_basepoint_param(base_point, builtin_param, fallback_names):
    """获取基点参数，优先使用 BuiltInParameter（can be None for old Revit），失败时按名称回退"""
    if builtin_param is not None:
        param = base_point.get_Parameter(builtin_param)
        if param is not None:
            return param
    for name in fallback_names:
        param = base_point.LookupParameter(name)
        if param is not None:
            return param
    return None

# Revit API 兼容：部分版本不再暴露 ParameterType，不能在模块加载阶段直接引用未定义名称
_PARAMETER_TYPE_CLASS = globals().get('ParameterType', None)
_ANGLE_PARAM_TYPE = getattr(_PARAMETER_TYPE_CLASS, 'Angle', None)

def get_angle_param(base_point):
    """获取项目基点的「到正北角度」参数对象（用于读写）。
    回退链：BuiltInParameter → LookupParameter 多语言名 → 遍历参数按名称/类型匹配"""
    p = get_basepoint_param(
        base_point,
        getattr(BuiltInParameter, 'BASEPOINT_ANGLETONORTH_PARAM', None),
        [u'Angle to True North', u'Angle to North',
         u'正北角度', u'与正北夹角', u'与正北方向夹角', u'正北方向角度'])
    if p is not None:
        return p

    # 遍历基点全部参数：先按名称关键字 + 类型匹配
    params_list = list(base_point.Parameters)
    for p in params_list:
        try:
            name_lower = p.Definition.Name.lower()
            is_angle_type = (_ANGLE_PARAM_TYPE is not None and p.Definition.ParameterType == _ANGLE_PARAM_TYPE)
            has_keyword = any(kw in name_lower for kw in ('angle', 'north', 'true', '北', '角度', '正北'))
            if is_angle_type and has_keyword:
                return p
        except:
            continue

    # 仅按类型匹配（Angle 类型）
    if _ANGLE_PARAM_TYPE is not None:
        for p in params_list:
            try:
                if p.Definition.ParameterType == _ANGLE_PARAM_TYPE:
                    return p
            except:
                continue

    # 仅按名称关键字匹配（兜底：某些版本 ParameterType 可能异常）
    for p in params_list:
        try:
            name_lower = p.Definition.Name.lower()
            if any(kw in name_lower for kw in ('angle', 'north', 'true', '北', '角度', '正北')):
                return p
        except:
            continue

    return None

def get_angle_to_true_north(doc, base_point):
    """获取项目到正北的角度（返回度数）。
    优先用 get_angle_param → 读取值；失败则尝试 ProjectPosition.Angle"""
    p_ang = get_angle_param(base_point)
    if p_ang is not None:
        return rad_to_deg(p_ang.AsDouble())
    try:
        proj_pos = doc.ActiveProjectLocation.GetProjectPosition(XYZ(0.0, 0.0, 0.0))
        return rad_to_deg(proj_pos.Angle)
    except:
        return 0.0

# --------------------------------------------------------------------------------
# 数据模型
# --------------------------------------------------------------------------------
class RevitFileItem(INotifyPropertyChanged):
    def __init__(self, file_path):
        self.FilePath = file_path
        self.FileName = os.path.basename(file_path)
        self._isSelected = True
        self._status = "待提取"
        self._currentNS = 0.0
        self._currentEW = 0.0
        self._currentElev = 0.0
        self._currentAngle = 0.0
        self._targetNS = 0.0
        self._targetEW = 0.0
        self._targetElev = 0.0
        self._targetAngle = 0.0
        self._isMismatch = False
        self._pc = None

    def add_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Combine(self._pc, value)

    def remove_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Remove(self._pc, value)

    def on_property_changed(self, name):
        if self._pc is not None:
            self._pc(self, PropertyChangedEventArgs(name))
        if "Target" in name or "Current" in name:
            self.check_mismatch()

    def check_mismatch(self):
        mismatch = (abs(self._targetNS - self._currentNS) > 0.001 or 
                    abs(self._targetEW - self._currentEW) > 0.001 or 
                    abs(self._targetElev - self._currentElev) > 0.001 or 
                    abs(self._targetAngle - self._currentAngle) > 0.01)
        if mismatch != self._isMismatch:
            self._isMismatch = mismatch
            self.on_property_changed("IsMismatch")

    @property
    def IsSelected(self): return self._isSelected
    @IsSelected.setter
    def IsSelected(self, value): self._isSelected = value; self.on_property_changed("IsSelected")

    @property
    def Status(self): return self._status
    @Status.setter
    def Status(self, value): self._status = value; self.on_property_changed("Status")

    @property
    def CurrentNS(self): return round(self._currentNS, 3)
    @CurrentNS.setter
    def CurrentNS(self, value): self._currentNS = value; self.on_property_changed("CurrentNS")

    @property
    def CurrentEW(self): return round(self._currentEW, 3)
    @CurrentEW.setter
    def CurrentEW(self, value): self._currentEW = value; self.on_property_changed("CurrentEW")

    @property
    def CurrentElev(self): return round(self._currentElev, 3)
    @CurrentElev.setter
    def CurrentElev(self, value): self._currentElev = value; self.on_property_changed("CurrentElev")

    @property
    def CurrentAngle(self): return round(self._currentAngle, 3)
    @CurrentAngle.setter
    def CurrentAngle(self, value): self._currentAngle = value; self.on_property_changed("CurrentAngle")

    @property
    def TargetNS(self): return self._targetNS
    @TargetNS.setter
    def TargetNS(self, value): 
        try: self._targetNS = float(value)
        except: self._targetNS = 0.0
        self.on_property_changed("TargetNS")

    @property
    def TargetEW(self): return self._targetEW
    @TargetEW.setter
    def TargetEW(self, value): 
        try: self._targetEW = float(value)
        except: self._targetEW = 0.0
        self.on_property_changed("TargetEW")

    @property
    def TargetElev(self): return self._targetElev
    @TargetElev.setter
    def TargetElev(self, value): 
        try: self._targetElev = float(value)
        except: self._targetElev = 0.0
        self.on_property_changed("TargetElev")

    @property
    def TargetAngle(self): return self._targetAngle
    @TargetAngle.setter
    def TargetAngle(self, value): 
        try: self._targetAngle = float(value)
        except: self._targetAngle = 0.0
        self.on_property_changed("TargetAngle")

    @property
    def IsMismatch(self): return self._isMismatch

# --------------------------------------------------------------------------------
# UI 类
# --------------------------------------------------------------------------------
class BasePointWindow(forms.WPFWindow):
    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file)
        self.theme_context = get_omnimetro_theme_context()
        self.apply_theme()
        self.items = ObservableCollection[RevitFileItem]()
        self.DataGridFiles.ItemsSource = self.items

    def apply_theme(self):
        palette = DARK_THEME if self.theme_context["is_dark"] else LIGHT_THEME
        for key, value in palette.items():
            self.Resources[key + "Brush"] = brush_from_hex(value)
        self.Background = self.Resources["WindowBgBrush"]

    def _refresh_grid(self):
        """强制刷新 DataGrid（兼容绑定异常时的兜底方案）"""
        try:
            self.DataGridFiles.ItemsSource = None
            self.DataGridFiles.ItemsSource = self.items
        except:
            pass

    def SelectFiles_Click(self, sender, e):
        files = forms.pick_file(files_filter='Revit Files (*.rvt)|*.rvt', multi_file=True)
        if files:
            for f in files:
                if not any(item.FilePath.lower() == f.lower() for item in self.items):
                    self.items.Add(RevitFileItem(f))
            self._refresh_grid()

    def BatchFill_Click(self, sender, e):
        selected_items = [i for i in self.items if i.IsSelected]
        if not selected_items:
            return
        master = selected_items[0]
        for i in selected_items[1:]:
            i.TargetNS = master.TargetNS
            i.TargetEW = master.TargetEW
            i.TargetElev = master.TargetElev
            i.TargetAngle = master.TargetAngle
        self._refresh_grid()

    def FillCurrent_Click(self, sender, e):
        """将当前提取值填充到真实数据列"""
        selected_items = [i for i in self.items if i.IsSelected]
        if not selected_items:
            forms.alert(u"请先勾选需要填充的行。", title=u"提示")
            return
        for item in selected_items:
            item.TargetNS = item.CurrentNS
            item.TargetEW = item.CurrentEW
            item.TargetElev = item.CurrentElev
            item.TargetAngle = item.CurrentAngle
        self._refresh_grid()

    def ExtractData_Click(self, sender, e):
        items_to_process = [i for i in self.items if i.IsSelected]
        if not items_to_process:
            return

        with forms.ProgressBar(title="正在提取基点数据...", total=len(items_to_process)) as pb:
            for index, item in enumerate(items_to_process):
                item.Status = "提取中"
                doc = None
                try:
                    opened_doc = next((d for d in app.Documents
                                      if os.path.normpath(d.PathName).lower() == os.path.normpath(item.FilePath).lower()), None)

                    if opened_doc:
                        doc = opened_doc
                        is_opened = True
                    else:
                        opt = OpenOptions()
                        opt.DetachFromCentralOption = DetachFromCentralOption.DetachAndPreserveWorksets
                        m_path = ModelPathUtils.ConvertUserVisiblePathToModelPath(item.FilePath)
                        doc = app.OpenDocumentFile(m_path, opt)
                        is_opened = False

                    pbp = FilteredElementCollector(doc)\
                        .OfCategory(BuiltInCategory.OST_ProjectBasePoint)\
                        .WhereElementIsNotElementType()\
                        .FirstElement()

                    if pbp:
                        p_ns = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM,
                                                    [u'N/S', u'North/South', u'北/南', u'南北'])
                        p_ew = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_EASTWEST_PARAM,
                                                    [u'E/W', u'East/West', u'东/西', u'东西'])
                        p_elev = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_ELEVATION_PARAM,
                                                      [u'Elev', u'Elevation', u'高程', u'标高'])

                        item.CurrentNS = round(ft_to_mm(p_ns.AsDouble()), 3) if p_ns else 0.0
                        item.CurrentEW = round(ft_to_mm(p_ew.AsDouble()), 3) if p_ew else 0.0
                        item.CurrentElev = round(ft_to_mm(p_elev.AsDouble()), 3) if p_elev else 0.0
                        item.CurrentAngle = round(get_angle_to_true_north(doc, pbp), 3)
                        item.Status = "已提取"
                    else:
                        item.Status = "无基点"

                    if not is_opened and doc:
                        doc.Close(False)
                except Exception as ex:
                    item.Status = "失败"
                    print("Error {}: {}".format(item.FileName, str(ex)))
                finally:
                    pb.update_progress(index + 1)

        self._refresh_grid()

    def RunBatch_Click(self, sender, e):
        items_to_process = [i for i in self.items if i.IsSelected]
        if not items_to_process:
            return

        total = len(items_to_process)
        success_count = 0
        fail_count = 0
        skip_readonly = 0
        skip_nobase = 0
        skip_noparam = 0

        with forms.ProgressBar(title="正在批量修改...", total=total) as pb:
            for index, item in enumerate(items_to_process):
                item.Status = "修改中"
                doc = None
                try:
                    opened_doc = next((d for d in app.Documents
                                      if os.path.normpath(d.PathName).lower() == os.path.normpath(item.FilePath).lower()), None)

                    if opened_doc:
                        doc = opened_doc
                        is_opened = True
                    else:
                        opt = OpenOptions()
                        opt.DetachFromCentralOption = DetachFromCentralOption.DetachAndPreserveWorksets
                        m_path = ModelPathUtils.ConvertUserVisiblePathToModelPath(item.FilePath)
                        doc = app.OpenDocumentFile(m_path, opt)
                        is_opened = False

                    if doc.IsReadOnly:
                        item.Status = "只读"
                        skip_readonly += 1
                        if not is_opened and doc:
                            doc.Close(False)
                        continue

                    pbp = FilteredElementCollector(doc)\
                        .OfCategory(BuiltInCategory.OST_ProjectBasePoint)\
                        .WhereElementIsNotElementType()\
                        .FirstElement()

                    if not pbp:
                        item.Status = "无基点"
                        skip_nobase += 1
                        if not is_opened and doc:
                            doc.Close(False)
                        continue

                    p_ns = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM,
                                                [u'N/S', u'North/South', u'北/南', u'南北'])
                    p_ew = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_EASTWEST_PARAM,
                                                [u'E/W', u'East/West', u'东/西', u'东西'])
                    p_elev = get_basepoint_param(pbp, BuiltInParameter.BASEPOINT_ELEVATION_PARAM,
                                                  [u'Elev', u'Elevation', u'高程', u'标高'])
                    p_ang = get_angle_param(pbp)

                    if not all([p_ns, p_ew, p_elev, p_ang]):
                        item.Status = "参数缺失"
                        skip_noparam += 1
                        if not is_opened and doc:
                            doc.Close(False)
                        continue

                    t = Transaction(doc, "Batch Update Base Point")
                    t.Start()
                    try:
                        p_ns.Set(mm_to_ft(item.TargetNS))
                        p_ew.Set(mm_to_ft(item.TargetEW))
                        p_elev.Set(mm_to_ft(item.TargetElev))
                        if not p_ang.IsReadOnly:
                            p_ang.Set(deg_to_rad(item.TargetAngle))
                        t.Commit()
                    except:
                        if t.HasStarted() and not t.HasEnded():
                            t.RollBack()
                        raise

                    if not is_opened:
                        doc.Save()

                    item.Status = "修改成功"
                    item.CurrentNS = item.TargetNS
                    item.CurrentEW = item.TargetEW
                    item.CurrentElev = item.TargetElev
                    item.CurrentAngle = item.TargetAngle
                    success_count += 1

                    if not is_opened and doc:
                        doc.Close(False)
                except Exception as ex:
                    item.Status = "失败"
                    fail_count += 1
                    print("Error {}: {}".format(item.FileName, str(ex)))
                    if doc and not is_opened:
                        try:
                            doc.Close(False)
                        except:
                            pass
                finally:
                    pb.update_progress(index + 1)

        self._refresh_grid()

        # 汇总弹窗
        lines = [
            u"本次修改文件数量：{} 个".format(total),
            u"成功：{} 个".format(success_count),
            u"失败：{} 个".format(fail_count),
        ]
        if skip_readonly:
            lines.append(u"跳过（只读）：{} 个".format(skip_readonly))
        if skip_nobase:
            lines.append(u"跳过（无基点）：{} 个".format(skip_nobase))
        if skip_noparam:
            lines.append(u"跳过（参数缺失）：{} 个".format(skip_noparam))
        forms.alert(u"\n".join(lines), title=u"批量修改完成")

if __name__ == "__main__":
    try:
        xaml_file = os.path.join(os.path.dirname(__file__), "ui.xaml")
        window = BasePointWindow(xaml_file)
        window.ShowDialog()
    except Exception as ex:
        forms.alert(u"项目基点批量管理器启动失败：{0}".format(ex))
