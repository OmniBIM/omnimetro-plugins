# -*- coding: utf-8 -*-
"""
工具名称: 项目参数转共享与数值管理器 - 主程序入口 (GUI 交互层)
功能描述: 提取当前打开项目的全部项目参数、共享参数与内置参数，
          支持一键/批量将普通项目参数无损转化为共享参数，并可直接在表格中修改数值并保存至模型。
架构规范: 三层解耦标准 (UI层 -> 核心算法层 -> 宿主适配层)
"""

from __future__ import unicode_literals
import os
import sys
import traceback

try:
    unicode
except NameError:
    unicode = str

import clr
clr.AddReference('System')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from System import EventHandler
from System.Windows.Controls import SelectionChangedEventArgs
from System.Windows.Media import Color, SolidColorBrush
from pyrevit import forms, script

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from core_business import (
    NATURE_BUILTIN,
    NATURE_PROJECT,
    NATURE_SHARED,
    VALUE_STATUS_MODIFIED,
    calculate_statistics,
    filter_param_items,
)
from revit_adapter import RevitHostAdapter

XAML_FILE = os.path.join(SCRIPT_DIR, 'ui.xaml')


def color_from_hex(hex_value):
    val = hex_value.strip().lstrip('#')
    return Color.FromRgb(
        int(val[0:2], 16),
        int(val[2:4], 16),
        int(val[4:6], 16)
    )


def brush_from_hex(hex_value):
    b = SolidColorBrush(color_from_hex(hex_value))
    b.Freeze()
    return b


class ProjectParamManagerWindow(forms.WPFWindow):
    """项目参数转共享与数值管理器主窗口"""

    def __init__(self):
        self._is_loading = True
        self.all_items = []
        self.displayed_items = []
        self.adapter = RevitHostAdapter()

        forms.WPFWindow.__init__(self, XAML_FILE)

        self._init_header_info()
        self._apply_theme()
        self.load_data()

        # 数据加载完成后再挂载筛选下拉框事件与就绪标记
        if hasattr(self, 'cmb_nature_filter') and self.cmb_nature_filter:
            self.cmb_nature_filter.SelectionChanged += self.OnNatureFilterChanged

        # 挂载表格单元格编辑结束事件，自动刷新状态列
        if hasattr(self, 'dg_params') and self.dg_params:
            self.dg_params.CellEditEnding += self.OnCellEditEnding

        self._is_loading = False

    def _init_header_info(self):
        """初始化头部文档信息"""
        if self.adapter.is_valid_doc:
            self.lbl_doc_title.Text = self.adapter.document_title
            self.lbl_doc_path.Text = self.adapter.document_path
        else:
            self.lbl_doc_title.Text = '未检测到活动的 Revit 项目'
            self.lbl_doc_path.Text = '请在 Revit 中打开项目后再运行此工具'

    def _apply_theme(self):
        """应用 OmniMetro 现代主题配色"""
        ctx = globals().get('__omnimetro__')
        is_dark = False
        if isinstance(ctx, dict):
            is_dark = bool(ctx.get('is_dark')) or ctx.get('theme') == '深色'

        if is_dark:
            self.Resources['WindowBg'] = brush_from_hex('#0F172A')
            self.Resources['HeaderBg'] = brush_from_hex('#1E293B')
            self.Resources['CardBg'] = brush_from_hex('#1E293B')
            self.Resources['TextPrimary'] = brush_from_hex('#F8FAFC')
            self.Resources['TextSecondary'] = brush_from_hex('#94A3B8')
            self.Resources['BorderBrushColor'] = brush_from_hex('#334155')
            self.Resources['RowHover'] = brush_from_hex('#334155')

    def load_data(self):
        """加载/重新扫描文档中的全部项目参数"""
        try:
            self.lbl_status_msg.Text = '正在扫描提取项目参数...'
            self.all_items = self.adapter.extract_all_parameters()
            self._update_stats()
            self.apply_filter()
            self.lbl_status_msg.Text = '就绪 (共提取 {0} 个参数)'.format(len(self.all_items))
        except Exception as ex:
            self.lbl_status_msg.Text = '提取异常: {0}'.format(ex)
            forms.alert('提取项目参数时发生错误:\n{0}'.format(traceback.format_exc()), title='错误')

    def _update_stats(self):
        """更新头部统计徽标"""
        stats = calculate_statistics(self.all_items)
        self.lbl_stat_total.Text = '总参数: {0}'.format(stats['total'])
        self.lbl_stat_project.Text = '普通项目参数(可转): {0}'.format(stats['project_count'])
        self.lbl_stat_shared.Text = '共享参数: {0}'.format(stats['shared_count'])
        self.lbl_stat_builtin.Text = '系统内置: {0}'.format(stats['builtin_count'])

    def apply_filter(self):
        """根据搜索框与筛选条件刷新表格显示"""
        if not hasattr(self, 'all_items') or not self.all_items:
            if hasattr(self, 'dg_params') and self.dg_params:
                self.dg_params.ItemsSource = None
            return

        keyword = self.txt_search.Text if hasattr(self, 'txt_search') and self.txt_search else ''

        nature_filter = 'all'
        if hasattr(self, 'cmb_nature_filter') and self.cmb_nature_filter and self.cmb_nature_filter.SelectedItem:
            item = self.cmb_nature_filter.SelectedItem
            nature_filter = getattr(item, 'Tag', 'all') or 'all'

        only_convertible = bool(self.chk_only_convertible.IsChecked) if hasattr(self, 'chk_only_convertible') else False
        only_modified = bool(self.chk_only_modified.IsChecked) if hasattr(self, 'chk_only_modified') else False

        filtered = filter_param_items(
            self.all_items,
            keyword=keyword,
            nature_filter=nature_filter,
            convertible_only=only_convertible,
            modified_only=only_modified
        )

        self.displayed_items = filtered
        if hasattr(self, 'dg_params') and self.dg_params:
            self.dg_params.ItemsSource = None
            self.dg_params.ItemsSource = self.displayed_items

    # ------------------------------------------------------------------
    # 界面交互事件
    # ------------------------------------------------------------------
    def OnSearchTextChanged(self, sender, e):
        if not self._is_loading:
            self.apply_filter()

    def OnNatureFilterChanged(self, sender, e):
        if not self._is_loading:
            self.apply_filter()

    def OnFilterChanged(self, sender, e):
        if not self._is_loading:
            self.apply_filter()

    def OnRefreshClicked(self, sender, e):
        self.load_data()

    def OnSelectAllClicked(self, sender, e):
        """全选/取消全选可转项"""
        is_checked = bool(self.chk_select_all.IsChecked)
        for item in self.displayed_items:
            if item.can_convert:
                item.is_checked = is_checked
        if hasattr(self, 'dg_params') and self.dg_params:
            self.dg_params.Items.Refresh()

    def OnCellEditEnding(self, sender, e):
        """当用户结束编辑单元格时，延迟刷新状态提示"""
        try:
            if hasattr(self, 'dg_params') and self.dg_params:
                # 触发 Items 刷新以更新“数值状态”列
                self.Dispatcher.BeginInvoke(System.Action(self._refresh_grid_items))
        except Exception:
            pass

    def _refresh_grid_items(self):
        try:
            if hasattr(self, 'dg_params') and self.dg_params and self.dg_params.Items:
                self.dg_params.Items.Refresh()
                self._update_stats()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 核心动作：一键全部转为共享参数
    # ------------------------------------------------------------------
    def OnConvertAllClicked(self, sender, e):
        """一键将当前所有可转化的普通项目参数转化为共享参数"""
        convertible_items = [item for item in self.all_items if item.can_convert and item.nature == NATURE_PROJECT]
        if not convertible_items:
            forms.alert('当前项目中没有可以转化的普通项目参数（或已全部转化为共享参数）。', title='提示')
            return

        confirm_msg = (
            '即将把当前项目中的 {0} 个普通项目参数一键转化为【共享参数】。\n\n'
            '✓ 系统将自动在共享参数文件中注册参数定义与唯一 GUID\n'
            '✓ 自动扫描全模型并 100% 完整保留已有图元参数值\n'
            '✓ 统一事务提交，支持 Ctrl+Z 撤销回滚\n\n'
            '是否确认立即开始转化？'
        ).format(len(convertible_items))

        if not forms.alert(confirm_msg, title='确认一键转化', ok=False, yes=True, no=True):
            return

        self.lbl_status_msg.Text = '正在执行一键参数转化并回写数值...'
        try:
            count, msg = self.adapter.convert_project_parameters_to_shared(convertible_items)
            self._update_stats()
            self.apply_filter()
            self.lbl_status_msg.Text = '转化完成！' + msg
            forms.alert(msg, title='转化完成')
        except Exception as ex:
            self.lbl_status_msg.Text = '转化失败: {0}'.format(ex)
            forms.alert('转化过程中发生异常:\n{0}'.format(traceback.format_exc()), title='错误')

    # ------------------------------------------------------------------
    # 核心动作：转化所选勾选参数
    # ------------------------------------------------------------------
    def OnConvertSelectedClicked(self, sender, e):
        """仅转化用户勾选的普通项目参数"""
        selected_items = [item for item in self.displayed_items if item.is_checked and item.can_convert]
        if not selected_items:
            forms.alert('请先在列表中勾选要转化的普通项目参数！', title='提示')
            return

        confirm_msg = '确认将勾选的 {0} 个普通项目参数转化为共享参数？'.format(len(selected_items))
        if not forms.alert(confirm_msg, title='确认转化所选', ok=False, yes=True, no=True):
            return

        self.lbl_status_msg.Text = '正在转化勾选的参数...'
        try:
            count, msg = self.adapter.convert_project_parameters_to_shared(selected_items)
            self._update_stats()
            self.apply_filter()
            self.lbl_status_msg.Text = msg
            forms.alert(msg, title='转化完成')
        except Exception as ex:
            self.lbl_status_msg.Text = '转化失败: {0}'.format(ex)
            forms.alert('转化异常:\n{0}'.format(traceback.format_exc()), title='错误')

    # ------------------------------------------------------------------
    # 核心动作：保存表格数值修改
    # ------------------------------------------------------------------
    def OnSaveValuesClicked(self, sender, e):
        """将表格中所有修改后的数值写入 Revit 模型"""
        modified_items = [item for item in self.all_items if item.value_status == VALUE_STATUS_MODIFIED]
        if not modified_items:
            forms.alert('当前没有待保存的数值修改。可直接在表格【参数数值】列中编辑后点击保存。', title='提示')
            return

        self.lbl_status_msg.Text = '正在将数值写入模型...'
        try:
            count, msg = self.adapter.save_parameter_values(modified_items)
            if hasattr(self, 'dg_params') and self.dg_params:
                self.dg_params.Items.Refresh()
            self.lbl_status_msg.Text = msg
            forms.alert(msg, title='保存成功')
        except Exception as ex:
            self.lbl_status_msg.Text = '保存失败: {0}'.format(ex)
            forms.alert('保存数值异常:\n{0}'.format(traceback.format_exc()), title='错误')

    # ------------------------------------------------------------------
    # 查看共享参数文件路径
    # ------------------------------------------------------------------
    def OnOpenSharedParamFileClicked(self, sender, e):
        try:
            sp_path, def_file = self.adapter.ensure_shared_parameter_file()
            forms.alert(
                '当前绑定的共享参数文件路径：\n\n{0}\n\n该文件包含转化后的全部共享参数定义与 GUID。'.format(sp_path),
                title='共享参数文件信息'
            )
        except Exception as ex:
            forms.alert('获取共享参数文件失败: {0}'.format(ex), title='错误')


if __name__ == '__main__':
    win = ProjectParamManagerWindow()
    win.ShowDialog()
