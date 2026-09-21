# -*- coding: utf-8 -*-
"""
工具名称: 项目参数批量管理器 - GUI 交互层
功能描述: 选择多个 Revit 文件，自动提取项目基点与全部项目参数（内置 + 项目/共享参数），
          支持新增项目参数，并批量修改/保存所有项目参数。
架构规范: 三层解耦标准 (UI层 -> 核心算法层 -> 宿主适配层)
"""

import clr
import os

clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from System import EventHandler
from System.Collections.Generic import Dictionary
from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
from System.Windows import PropertyPath
from System.Windows.Data import Binding, BindingMode, UpdateSourceTrigger
from System.Windows.Media import SolidColorBrush, Color

from pyrevit import forms, script

from core_business import (
    NEW_PARAM_TYPE_OPTIONS,
    PARAM_GROUP_OPTIONS,
    STORAGE_STRING,
    from_display_text,
)
from revit_adapter import RevitHostAdapter


# --------------------------------------------------------------------------------
# 主题（浅色 / 深色）
# --------------------------------------------------------------------------------
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
    value = hex_value.strip().lstrip('#')
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


def escape_binding_key(key):
    """转义 WPF 绑定路径中的索引键（括号内转义）。"""
    return key.replace('[', u'[[]').replace(']', u'[]]')


# --------------------------------------------------------------------------------
# 数据模型（每行 = 一个 Revit 文件）
# --------------------------------------------------------------------------------
class FileRowModel(INotifyPropertyChanged):
    def __init__(self, file_path):
        self._pc = None
        self.FilePath = file_path
        self.FileName = os.path.basename(file_path)
        self._isSelected = True
        self._status = u'待提取'
        # 基点目标值（文本，mm/度）
        self._baseNS = u''
        self._baseEW = u''
        self._baseElev = u''
        self._baseAngle = u''
        # 基点提取原值（文本）用于对比
        self.original_base = {u'ns': u'', u'ew': u'', u'elev': u'', u'angle': u''}
        # 参数目标值字典（参数名 -> 显示文本），绑定动态列
        self.Values = Dictionary[str, str]()
        # 参数提取原值（参数名 -> 显示文本）用于对比/重置
        self.original_values = {}
        # 参数元信息（参数名 -> (param_type, storage_type, is_readonly, display_name)）
        self.param_meta = {}
        self.extract_error = u''

    def add_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Combine(self._pc, value)

    def remove_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Remove(self._pc, value)

    def on_property_changed(self, name):
        if self._pc is not None:
            self._pc(self, PropertyChangedEventArgs(name))

    @property
    def IsSelected(self):
        return self._isSelected
    @IsSelected.setter
    def IsSelected(self, value):
        self._isSelected = value
        self.on_property_changed('IsSelected')

    @property
    def Status(self):
        return self._status
    @Status.setter
    def Status(self, value):
        self._status = value
        self.on_property_changed('Status')

    @property
    def BaseNS(self):
        return self._baseNS
    @BaseNS.setter
    def BaseNS(self, value):
        self._baseNS = u'' if value is None else u'{0}'.format(value)
        self.on_property_changed('BaseNS')

    @property
    def BaseEW(self):
        return self._baseEW
    @BaseEW.setter
    def BaseEW(self, value):
        self._baseEW = u'' if value is None else u'{0}'.format(value)
        self.on_property_changed('BaseEW')

    @property
    def BaseElev(self):
        return self._baseElev
    @BaseElev.setter
    def BaseElev(self, value):
        self._baseElev = u'' if value is None else u'{0}'.format(value)
        self.on_property_changed('BaseElev')

    @property
    def BaseAngle(self):
        return self._baseAngle
    @BaseAngle.setter
    def BaseAngle(self, value):
        self._baseAngle = u'' if value is None else u'{0}'.format(value)
        self.on_property_changed('BaseAngle')

    def set_value(self, name, text):
        """设置参数目标值并通知绑定刷新。"""
        self.Values[name] = u'' if text is None else u'{0}'.format(text)
        self.on_property_changed('Values')

    def get_value(self, name):
        try:
            return self.Values[name]
        except Exception:
            return u''

    def base_changed(self):
        """基点是否有修改。"""
        return (self.BaseNS.strip() != self.original_base[u'ns'].strip() or
                self.BaseEW.strip() != self.original_base[u'ew'].strip() or
                self.BaseElev.strip() != self.original_base[u'elev'].strip() or
                self.BaseAngle.strip() != self.original_base[u'angle'].strip())


# --------------------------------------------------------------------------------
# UI 类
# --------------------------------------------------------------------------------
class ProjectParamWindow(forms.WPFWindow):
    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file)
        self.theme_context = get_omnimetro_theme_context()
        self.apply_theme()
        self.items = ObservableCollection[FileRowModel]()
        self.DataGridFiles.ItemsSource = self.items
        self.adapter = RevitHostAdapter(__revit__.Application)
        self.param_order = []        # 参数名顺序（用于动态列）
        self._columns_built = False

        # 新增参数下拉框
        for label, _ in NEW_PARAM_TYPE_OPTIONS:
            self.cmbNewParamType.Items.Add(label)
        self.cmbNewParamType.SelectedIndex = 0
        for label, _ in PARAM_GROUP_OPTIONS:
            self.cmbNewParamGroup.Items.Add(label)
        self.cmbNewParamGroup.SelectedIndex = 0

        self.update_status()

    def apply_theme(self):
        palette = DARK_THEME if self.theme_context["is_dark"] else LIGHT_THEME
        for key, value in palette.items():
            self.Resources[key + "Brush"] = brush_from_hex(value)
        self.Background = self.Resources["WindowBgBrush"]

    def update_status(self):
        selected = sum(1 for i in self.items if i.IsSelected)
        self.txtStatus.Text = (u'已添加文件 {0} 个 | 选中 {1} 个 | 已提取参数 {2} 项 | '
                               u'当前活动文档: {3}').format(
            len(self.items), selected, len(self.param_order),
            os.path.basename(__revit__.doc.PathName) if __revit__.doc.PathName else u'(未保存)')

    def _refresh_grid(self):
        try:
            self.DataGridFiles.ItemsSource = None
            self.DataGridFiles.ItemsSource = self.items
        except Exception:
            pass

    # -- 文件操作 ------------------------------------------------------
    def SelectFiles_Click(self, sender, e):
        files = forms.pick_file(files_filter='Revit Files (*.rvt)|*.rvt', multi_file=True)
        if not files:
            return
        existing = set()
        for item in self.items:
            existing.add(item.FilePath.lower())
        added = 0
        for f in files:
            if f.lower() not in existing:
                self.items.Add(FileRowModel(f))
                existing.add(f.lower())
                added += 1
        if added:
            self._refresh_grid()
            self.update_status()

    def RemoveSelected_Click(self, sender, e):
        to_remove = [i for i in self.items if i.IsSelected]
        for i in to_remove:
            self.items.Remove(i)
        self._refresh_grid()
        self.update_status()

    def SelectAll_Click(self, sender, e):
        for i in self.items:
            i.IsSelected = True
        self.update_status()

    def SelectNone_Click(self, sender, e):
        for i in self.items:
            i.IsSelected = False
        self.update_status()

    # -- 动态列构建 ----------------------------------------------------
    def build_param_columns(self):
        """根据 param_order 重建动态参数列（保留固定列）。"""
        # 移除旧的参数列
        fixed_count = 7  # 选择/文件名/状态/NS/EW/Elev/Angle
        while self.DataGridFiles.Columns.Count > fixed_count:
            self.DataGridFiles.Columns.RemoveAt(self.DataGridFiles.Columns.Count - 1)

        for name in self.param_order:
            # 从第一个拥有该参数的行取元信息
            meta = None
            for item in self.items:
                if name in item.param_meta:
                    meta = item.param_meta[name]
                    break
            if meta is None:
                continue
            param_type, storage_type, is_readonly, display_name = meta

            col = self._create_param_column(name, display_name, is_readonly)
            self.DataGridFiles.Columns.Add(col)
        self._columns_built = True

    def _create_param_column(self, name, display_name, is_readonly):
        from System.Windows.Controls import DataGridTextColumn
        col = DataGridTextColumn()
        col.Header = display_name
        col.Width = 120
        col.MinWidth = 80
        binding = Binding()
        binding.Path = PropertyPath(u'Values[{0}]'.format(escape_binding_key(name)))
        binding.Mode = BindingMode.TwoWay
        binding.UpdateSourceTrigger = UpdateSourceTrigger.PropertyChanged
        col.Binding = binding
        col.IsReadOnly = is_readonly
        return col

    # -- 提取 ----------------------------------------------------------
    def ExtractData_Click(self, sender, e):
        items_to_process = [i for i in self.items if i.IsSelected]
        if not items_to_process:
            forms.alert(u'请先选择要处理的 Revit 文件。', title=u'提示')
            return

        # 1) 逐个提取
        extracted = {}
        with forms.ProgressBar(title=u'正在提取项目参数...', total=len(items_to_process)) as pb:
            for index, item in enumerate(items_to_process):
                item.Status = u'提取中'
                try:
                    data = self.adapter.extract_file_data(item.FilePath, item.FileName)
                    extracted[item.FilePath] = data
                    if data.ok:
                        item.Status = u'已提取'
                    else:
                        item.Status = u'失败'
                        item.extract_error = data.error
                except Exception as ex:
                    item.Status = u'失败'
                    item.extract_error = u'{0}'.format(ex)
                pb.update_progress(index + 1)

        # 2) 汇总参数顺序（内置参数在前，按首见顺序去重）
        order = []
        seen = set()
        for data in extracted.values():
            for p in data.params:
                if p.name in seen:
                    continue
                seen.add(p.name)
                order.append(p.name)
        # 内置参数优先排序（stable）
        order.sort(key=lambda n: 0 if self._is_builtin(n, extracted) else 1)
        self.param_order = order

        # 3) 填充每行的基点 + 参数值
        for item in self.items:
            data = extracted.get(item.FilePath)
            if data is None or not data.ok:
                continue
            bp = data.base_point
            item.BaseNS = u'{0:.3f}'.format(bp[u'ns']) if bp[u'ns'] is not None else u''
            item.BaseEW = u'{0:.3f}'.format(bp[u'ew']) if bp[u'ew'] is not None else u''
            item.BaseElev = u'{0:.3f}'.format(bp[u'elev']) if bp[u'elev'] is not None else u''
            item.BaseAngle = u'{0:.3f}'.format(bp[u'angle']) if bp[u'angle'] is not None else u''
            item.original_base = {
                u'ns': item.BaseNS, u'ew': item.BaseEW,
                u'elev': item.BaseElev, u'angle': item.BaseAngle,
            }
            # 参数
            item.original_values = {}
            item.param_meta = {}
            for p in data.params:
                item.original_values[p.name] = p.value_text
                item.param_meta[p.name] = (
                    p.param_type, p.storage_type, p.is_readonly, p.display_name)
                item.set_value(p.name, p.value_text)
            # 确保 param_order 中所有参数都有值（缺失置空）
            for name in self.param_order:
                if name not in item.param_meta:
                    item.param_meta[name] = (STORAGE_STRING, STORAGE_STRING, True, name)
                    item.set_value(name, u'')

        # 4) 重建列
        self.build_param_columns()
        self._refresh_grid()
        self.update_status()

        # 汇总
        ok_count = sum(1 for data in extracted.values() if data.ok)
        fail_count = sum(1 for data in extracted.values() if not data.ok)
        forms.alert(
            u'提取完成：成功 {0} 个文件，失败 {1} 个；共发现 {2} 个项目参数。'.format(
                ok_count, fail_count, len(self.param_order)),
            title=u'提取结果')

    def _is_builtin(self, name, extracted):
        for data in extracted.values():
            for p in data.params:
                if p.name == name:
                    return bool(p.builtin_name)
        return False

    # -- 重置 ----------------------------------------------------------
    def ResetValues_Click(self, sender, e):
        for item in self.items:
            if not item.IsSelected:
                continue
            item.BaseNS = item.original_base[u'ns']
            item.BaseEW = item.original_base[u'ew']
            item.BaseElev = item.original_base[u'elev']
            item.BaseAngle = item.original_base[u'angle']
            for name, text in item.original_values.items():
                item.set_value(name, text)
        self._refresh_grid()
        self.update_status()

    # -- 新增项目参数 --------------------------------------------------
    def AddParam_Click(self, sender, e):
        param_name = self.txtNewParamName.Text.strip()
        if not param_name:
            forms.alert(u'请输入参数名称。', title=u'提示')
            return
        type_idx = self.cmbNewParamType.SelectedIndex
        group_idx = self.cmbNewParamGroup.SelectedIndex
        if type_idx < 0:
            type_idx = 0
        if group_idx < 0:
            group_idx = 0
        param_type_id = NEW_PARAM_TYPE_OPTIONS[type_idx][0]
        group_id = PARAM_GROUP_OPTIONS[group_idx][0]

        items_to_process = [i for i in self.items if i.IsSelected]
        if not items_to_process:
            forms.alert(u'请先选择要添加参数的 Revit 文件。', title=u'提示')
            return

        success = 0
        failed = []
        with forms.ProgressBar(title=u'正在添加项目参数...', total=len(items_to_process)) as pb:
            for index, item in enumerate(items_to_process):
                item.Status = u'添加中'
                try:
                    ok, msg = self.adapter.add_project_param(
                        item.FilePath, item.FileName, param_name, param_type_id, group_id)
                    if ok:
                        item.Status = u'已添加'
                        success += 1
                    else:
                        item.Status = u'失败'
                        failed.append(u'{0}: {1}'.format(item.FileName, msg))
                except Exception as ex:
                    item.Status = u'失败'
                    failed.append(u'{0}: {1}'.format(item.FileName, ex))
                pb.update_progress(index + 1)

        self._refresh_grid()
        self.update_status()

        msg_lines = [u'成功添加参数 "{0}" 到 {1} 个文件。'.format(param_name, success)]
        if failed:
            msg_lines.append(u'失败 {0} 个：'.format(len(failed)))
            msg_lines.extend(failed[:5])
        forms.alert(u'\n'.join(msg_lines), title=u'新增参数完成')

        # 添加成功后提示重新提取以显示新参数列
        if success:
            forms.alert(u'参数已添加。请点击「提取所选数据」刷新列表以显示新参数。', title=u'提示')

    # -- 批量写入 ------------------------------------------------------
    def RunBatch_Click(self, sender, e):
        items_to_process = [i for i in self.items if i.IsSelected]
        if not items_to_process:
            forms.alert(u'请先选择要写入的 Revit 文件。', title=u'提示')
            return

        # 收集修改项
        plan = []  # (item, base_updates, param_updates)
        for item in items_to_process:
            if item.Status not in (u'已提取', u'写入成功', u'已添加'):
                continue
            base_updates = {}
            if item.BaseNS.strip() and item.BaseNS.strip() != item.original_base[u'ns'].strip():
                try:
                    base_updates[u'ns'] = float(item.BaseNS)
                except ValueError:
                    pass
            if item.BaseEW.strip() and item.BaseEW.strip() != item.original_base[u'ew'].strip():
                try:
                    base_updates[u'ew'] = float(item.BaseEW)
                except ValueError:
                    pass
            if item.BaseElev.strip() and item.BaseElev.strip() != item.original_base[u'elev'].strip():
                try:
                    base_updates[u'elev'] = float(item.BaseElev)
                except ValueError:
                    pass
            if item.BaseAngle.strip() and item.BaseAngle.strip() != item.original_base[u'angle'].strip():
                try:
                    base_updates[u'angle'] = float(item.BaseAngle)
                except ValueError:
                    pass

            param_updates = {}
            for name in self.param_order:
                meta = item.param_meta.get(name)
                if meta is None:
                    continue
                param_type, storage_type, is_readonly, display_name = meta
                if is_readonly:
                    continue
                new_text = item.get_value(name)
                orig_text = item.original_values.get(name, u'')
                if new_text.strip() == orig_text.strip():
                    continue
                # 校验可解析
                ok, _ = from_display_text(param_type, storage_type, new_text)
                if not ok:
                    continue
                param_updates[name] = (param_type, storage_type, new_text)

            if base_updates or param_updates:
                plan.append((item, base_updates, param_updates))

        if not plan:
            forms.alert(u'没有检测到需要写入的修改。', title=u'提示')
            return

        # 确认
        confirm_lines = [
            u'将写入以下修改（每个文件单独保存）：',
            u'',
        ]
        for item, base_updates, param_updates in plan:
            parts = []
            if base_updates:
                parts.append(u'基点 {0}'.format(
                    u','.join(u'{0}={1}'.format(k, v) for k, v in base_updates.items())))
            if param_updates:
                parts.append(u'参数 {0} 项'.format(len(param_updates)))
            confirm_lines.append(u'  {0}: {1}'.format(item.FileName, u'；'.join(parts)))
        confirm_lines.append(u'')
        confirm_lines.append(u'继续写入 {0} 个文件？'.format(len(plan)))
        if not forms.alert(u'\n'.join(confirm_lines), title=u'确认批量写入', ok=False, yes=True, no=True):
            return

        # 执行
        total = len(plan)
        success_count = 0
        fail_count = 0
        with forms.ProgressBar(title=u'正在批量写入...', total=total) as pb:
            for index, (item, base_updates, param_updates) in enumerate(plan):
                item.Status = u'修改中'
                try:
                    ok, msg = self.adapter.apply_updates(
                        item.FilePath, item.FileName, base_updates, param_updates)
                    if ok:
                        item.Status = u'写入成功'
                        success_count += 1
                        # 更新原始值（写入成功后以当前目标值为准）
                        item.original_base = {
                            u'ns': item.BaseNS, u'ew': item.BaseEW,
                            u'elev': item.BaseElev, u'angle': item.BaseAngle,
                        }
                        for name in param_updates:
                            item.original_values[name] = item.get_value(name)
                    else:
                        item.Status = u'失败'
                        fail_count += 1
                        print(u'写入失败 {}: {}'.format(item.FileName, msg))
                except Exception as ex:
                    item.Status = u'失败'
                    fail_count += 1
                    print(u'写入异常 {}: {}'.format(item.FileName, ex))
                pb.update_progress(index + 1)

        self._refresh_grid()
        self.update_status()

        lines = [
            u'写入完成：成功 {0} 个，失败 {1} 个。'.format(success_count, fail_count),
        ]
        forms.alert(u'\n'.join(lines), title=u'批量写入完成')


# --------------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------------
if __name__ == '__main__':
    try:
        xaml_file = os.path.join(os.path.dirname(__file__), 'ui.xaml')
        window = ProjectParamWindow(xaml_file)
        window.ShowDialog()
    except Exception as ex:
        import traceback
        traceback.print_exc()
        forms.alert(u'项目参数批量管理器启动失败：{0}'.format(ex))
