# -*- coding: utf-8 -*-

from __future__ import division

__persistentengine__ = True

import os
import math
import time
import traceback

from Autodesk.Revit.DB import ElementId
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType

from pyrevit import DB, forms, revit, script
from pyrevit.framework import Controls, Drawing, Forms, List, Media, Windows

from liner_master import core, db, alignment

try:
    unicode
except NameError:
    unicode = str


logger = script.get_logger()
brush_converter = Media.BrushConverter()

DISCIPLINE_PREFIXES = ['Track', 'Arch', 'Struct', 'Vent', 'Plumb', 'Lght', 'StrPwr', 'WkPwr']
PREFIX_TAB_INDEX = {
    'Clearance': 1,
    'Track': 2,
    'Arch': 3,
    'Struct': 4,
    'Vent': 5,
    'Plumb': 6,
    'Lght': 7,
    'StrPwr': 8,
    'WkPwr': 9,
}


class CurveElementSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        return core.is_curve_element(element)

    def AllowReference(self, reference, position):
        return True


class PathReferenceSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        return True

    def AllowReference(self, reference, position):
        return True


class FamilyInstanceSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        try:
            core.get_symbol_info_from_instance(element)
            return True
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return True


class ConfigEntry(object):
    def __init__(
        self,
        config_id,
        mode_text,
        curve_selection,
        symbol_info,
        profile_selection,
        spacing_text,
        count_text,
        horizontal_offset_text,
        vertical_offset_text,
        horizontal_rotation_text,
        vertical_rotation_text,
    ):
        self.config_id = config_id
        self.mode_text = mode_text
        self.curve_selection = curve_selection
        self.symbol_info = symbol_info
        self.profile_selection = profile_selection
        self.spacing_text = spacing_text
        self.count_text = count_text
        self.horizontal_offset_text = horizontal_offset_text
        self.vertical_offset_text = vertical_offset_text
        self.horizontal_rotation_text = horizontal_rotation_text
        self.vertical_rotation_text = vertical_rotation_text


class ToolState(object):
    def __init__(self):
        self.mode_text = u'family'
        self.curve_selection = None
        self.symbol_info = None
        self.profile_selection = None

        self.spacing_text = u'1000'
        self.count_text = u''
        self.horizontal_offset_text = u'0'
        self.vertical_offset_text = u'0'
        self.horizontal_rotation_text = u'0'
        self.vertical_rotation_text = u'0'

        # Global segment controls
        self.global_start_dist = u'0'
        self.global_end_dist = u''
        self.global_segment_length = u'500'

        self.config_entries = []
        self.selected_config_id = None
        self.next_config_id = 1

        self.status_text = u'就绪。'
        self.status_is_error = False
        self.requested_action = None
        self.progress_value = 0
        self.progress_text = u'等待开始。'
        self.elapsed_text = u'耗时: 0.0 s'
        self.alignment_points = []
        self.active_prefix = None
        self.active_tab_index = 0
        self.generation_queue = []
        self.symbol_infos_by_prefix = {}
        self.profile_selections_by_prefix = {}
        self.preview_zoom_by_prefix = {}
        self.selected_queue_index = None


class PreviewRow(object):
    def __init__(self, index, distance_mm, x_mm, y_mm, z_mm, note):
        self.Index = unicode(index)
        self.DistanceMm = distance_mm
        self.Xmm = x_mm
        self.Ymm = y_mm
        self.Zmm = z_mm
        self.Note = note


class AlignmentDataRow(object):
    def __init__(self, data_dict):
        self.Index = unicode(data_dict.get('index', ''))
        self.Chainage = unicode(data_dict.get('chainage', ''))
        self.X = u"{0:.3f}".format(data_dict.get('x', 0))
        self.Y = u"{0:.3f}".format(data_dict.get('y', 0))
        self.Z = u"{0:.3f}".format(data_dict.get('z', 0))
        self.IsEquation = u"是" if data_dict.get('is_equation') else u"否"

class ConfigListRow(object):
    def __init__(self, config_entry):
        self.ConfigId = config_entry.config_id
        self.ConfigName = u'#{0}'.format(config_entry.config_id)
        self.Mode = u'阵列' if config_entry.mode_text == u'family' else u'放样'
        self.Curve = summarize_curve(config_entry.curve_selection)
        self.Target = summarize_target(config_entry)
        self.Spacing = config_entry.spacing_text if config_entry.mode_text == u'family' else u'-'
        self.Count = (config_entry.count_text or u'自动') if config_entry.mode_text == u'family' else u'1'
        self.Angles = u'H {0} / V {1}'.format(
            config_entry.horizontal_rotation_text,
            config_entry.vertical_rotation_text,
        )
        self.Offsets = u'H {0} / V {1}'.format(
            config_entry.horizontal_offset_text,
            config_entry.vertical_offset_text,
        )


class TaskQueueRow(object):
    """任务队列的行数据模型，用于绑定到总控面板的 DataGrid"""
    def __init__(self, index, label, task_type, discipline, family_name,
                 spacing, count, h_offset, v_offset, h_rotation, v_rotation):
        self.Index = unicode(index)
        self.Label = unicode(label)
        self.TaskType = unicode(task_type)
        self.Discipline = unicode(discipline)
        self.FamilyName = unicode(family_name)
        self.Spacing = unicode(spacing)
        self.Count = unicode(count)
        self.HOffset = unicode(h_offset)
        self.VOffset = unicode(v_offset)
        self.HRotation = unicode(h_rotation)
        self.VRotation = unicode(v_rotation)

def get_basepoint_angle_param(base_point, built_in_parameter):
    angle_param_id = getattr(built_in_parameter, 'BASEPOINT_ANGLETONORTH_PARAM', None)
    if angle_param_id:
        param = base_point.get_Parameter(angle_param_id)
        if param:
            return param
    for param_name in [u'Angle to True North', u'Angle to North', u'正北角度', u'与正北夹角']:
        param = base_point.LookupParameter(param_name)
        if param:
            return param
    return None

class AlongCurveWindow(forms.WPFWindow):
    def __init__(self, state):
        xaml_path = os.path.join(os.path.dirname(__file__), 'ui.xaml')
        forms.WPFWindow.__init__(self, xaml_path)

        self.state = state
        self.curve_selection = state.curve_selection
        self.symbol_info = state.symbol_info
        self.profile_selection = state.profile_selection
        self.layout_result = None
        self.preview_rows = []
        self.config_rows = []
        self.generation_queue = list(getattr(state, 'generation_queue', []) or [])
        self.symbol_infos_by_prefix = dict(getattr(state, 'symbol_infos_by_prefix', {}) or {})
        self.profile_selections_by_prefix = dict(getattr(state, 'profile_selections_by_prefix', {}) or {})
        self.preview_zoom_by_prefix = dict(getattr(state, 'preview_zoom_by_prefix', {}) or {})
        self.selected_queue_index = getattr(state, 'selected_queue_index', None)
        self.handling_config_selection = False

        self.btnImportAlignmentCSV.Click += self.on_import_alignment_csv
        self.btnGenerateAlignmentSpline.Click += self.on_generate_alignment_spline
        self.btnSelectCurve.Click += self.on_select_curve

        try:
            self.gridPreview.ItemsSource = self.preview_rows
            self.gridConfigs.ItemsSource = self.config_rows
            self.btnSelectFamily.Click += self.on_select_family
            self.btnPickPlacedFamily.Click += self.on_pick_placed_family
            self.btnSelectProfile.Click += self.on_select_profile
            self.btnSelectProfileFamily.Click += self.on_select_profile_family
        except AttributeError:
            pass

        # 核心按钮绑定 (确保这些控件在 UI 中必须存在)
        if hasattr(self, 'btnPlace'): self.btnPlace.Click += self.on_place
        if hasattr(self, 'btnBatchPlace'): self.btnBatchPlace.Click += self.on_batch_place
        if hasattr(self, 'btnStepPlace'): self.btnStepPlace.Click += self.on_step_place
        if hasattr(self, 'btnClose'): self.btnClose.Click += self.on_close

        # 预览与配置列表绑定 (根据 XAML 存在性动态绑定)
        try:
            if hasattr(self, 'gridPreview'):
                self.gridPreview.SelectionChanged += self.on_preview_selection_changed
            if hasattr(self, 'gridConfigs'):
                self.gridConfigs.SelectionChanged += self.on_config_selection_changed
            if hasattr(self, 'previewCanvas'):
                self.previewCanvas.SizeChanged += self.on_preview_canvas_size_changed
            if hasattr(self, 'cmbMode'):
                self.cmbMode.SelectionChanged += self.on_mode_changed
        except Exception:
            pass

        try:
            self.txtClearanceInnerDia.TextChanged += self.on_clearance_changed
            self.txtClearanceOuterDia.TextChanged += self.on_clearance_changed
            self.txtClearanceTrackHeight.TextChanged += self.on_clearance_changed
            
            # Dashboard global segment controls
            self.txtStartDist_Dashboard.TextChanged += self.on_input_changed
            self.txtEndDist_Dashboard.TextChanged += self.on_input_changed
            self.txtSegmentLength_Dashboard.TextChanged += self.on_input_changed
        except AttributeError:
            pass
        self._load_state_into_controls()

        # Save/Load and Queue management
        try:
            self.btnSaveProject.Click += self.on_save_project
            self.btnLoadProject.Click += self.on_load_project
        except AttributeError:
            pass
        try:
            self.btnRemoveQueueTask.Click += self.on_remove_queue_task
            self.btnClearQueue.Click += self.on_clear_queue
            if hasattr(self, 'gridTaskQueue'):
                self.gridTaskQueue.SelectionChanged += self.on_task_queue_selection_changed
            # 绑定基点应用按钮
            if hasattr(self, 'btnApplyBasePoint'):
                self.btnApplyBasePoint.Click += self.on_apply_base_point
        except AttributeError:
            pass

        # 初始化读取项目基点
        self._load_project_base_point()

        # 动态绑定所有专业标签页的按钮
        for p in DISCIPLINE_PREFIXES:
            btn = getattr(self, 'btnSelectFamily_' + p, None)
            if btn:
                btn.Click += lambda s, e, prefix=p: self.on_select_family_prefix(prefix)
            btn = getattr(self, 'btnPickPlacedFamily_' + p, None)
            if btn:
                btn.Click += lambda s, e, prefix=p: self.on_pick_placed_family_prefix(prefix)
            btn = getattr(self, 'btnAddArrayTask_' + p, None)
            if btn:
                btn.Click += lambda s, e, prefix=p: self.on_generate_array_prefix(prefix)
            btn = getattr(self, 'btnSelectProfile_' + p, None)
            if btn:
                btn.Click += lambda s, e, prefix=p: self.on_select_profile_prefix(prefix)
            btn = getattr(self, 'btnSelectProfileFamily_' + p, None)
            if btn:
                btn.Click += lambda s, e, prefix=p: self.on_select_profile_family_prefix(prefix)
            btn = getattr(self, 'btnAddSweepTask_' + p, None)
            if btn:
                btn.Click += lambda s, e, prefix=p: self.on_generate_sweep_prefix(prefix)
            canvas = getattr(self, 'canvasPreview_' + p, None)
            if canvas:
                canvas.Focusable = True
                canvas.MouseWheel += lambda s, e, prefix=p: self.on_preview_mouse_wheel(prefix, s, e)
            self._bind_task_editor_keys(p)

        clearance_canvas = getattr(self, 'canvasPreview_Clearance', None)
        if clearance_canvas:
            clearance_canvas.Focusable = True
            clearance_canvas.MouseWheel += lambda s, e: self.on_preview_mouse_wheel('Clearance', s, e)

        self._draw_normal_plane(None)
        self.refresh_preview(silent=True)
        self._refresh_config_grid()
        self._refresh_task_queue_grid()
        self._set_status(state.status_text, is_error=state.status_is_error)
        self._set_progress(state.progress_value, state.progress_text, state.elapsed_text)
        self._apply_mode_visuals()
        self.update_clearance_drawings()
        self._select_active_tab()

    def on_clearance_changed(self, sender, args):
        self.update_clearance_drawings()

    def _bind_task_editor_keys(self, prefix):
        names = [
            'txtSpacing_', 'txtCount_', 'txtHorizontalOffset_', 'txtVerticalOffset_',
            'txtHorizontalRotation_', 'txtVerticalRotation_', 'txtArrayLabel_',
            'txtSweepHorizontalOffset_', 'txtSweepVerticalOffset_', 'txtSweepLabel_',
        ]
        for name in names:
            control = getattr(self, name + prefix, None)
            if control:
                control.KeyDown += lambda s, e, p=prefix: self.on_task_editor_key_down(p, s, e)

    def on_preview_mouse_wheel(self, prefix, sender, args):
        zoom = self.preview_zoom_by_prefix.get(prefix, 1.0)
        if args.Delta > 0:
            zoom *= 1.12
        else:
            zoom /= 1.12
        zoom = max(0.45, min(3.0, zoom))
        self.preview_zoom_by_prefix[prefix] = zoom
        self.state.preview_zoom_by_prefix = dict(self.preview_zoom_by_prefix)
        self.update_clearance_drawings()
        try:
            args.Handled = True
            sender.Focus()
        except Exception:
            pass

    def on_preview_marker_clicked(self, queue_index, prefix, sender, args):
        self.selected_queue_index = queue_index
        self.state.selected_queue_index = queue_index
        self.state.active_prefix = prefix
        self._load_task_into_prefix_inputs(queue_index)
        self._refresh_task_queue_grid()
        self.update_clearance_drawings()
        self._select_active_tab()
        try:
            args.Handled = True
        except Exception:
            pass

    def _load_task_into_prefix_inputs(self, queue_index):
        if queue_index is None or queue_index < 0 or queue_index >= len(self.generation_queue):
            return
        task = self.generation_queue[queue_index]
        prefix = task.get('prefix')
        if not prefix:
            return
        if task.get('type') == 'array':
            pairs = [
                ('txtSpacing_', 'spacing'),
                ('txtCount_', 'count'),
                ('txtHorizontalOffset_', 'h_offset'),
                ('txtVerticalOffset_', 'v_offset'),
                ('txtHorizontalRotation_', 'h_rotation'),
                ('txtVerticalRotation_', 'v_rotation'),
                ('txtArrayLabel_', 'label'),
            ]
        else:
            pairs = [
                ('txtSweepHorizontalOffset_', 'h_offset'),
                ('txtSweepVerticalOffset_', 'v_offset'),
                ('txtSweepLabel_', 'label'),
            ]
        for control_prefix, key in pairs:
            control = getattr(self, control_prefix + prefix, None)
            if control:
                value = task.get(key, u'')
                control.Text = u'' if value is None or value == u'自动' else unicode(value)
        focus_box = getattr(self, 'txtHorizontalOffset_' + prefix, None)
        if task.get('type') != 'array':
            focus_box = getattr(self, 'txtSweepHorizontalOffset_' + prefix, None)
        try:
            if focus_box:
                focus_box.Focus()
                focus_box.SelectAll()
        except Exception:
            pass
        self._set_status(u'已选中队列第 {0} 条，可在左侧修改参数后按 Enter 确认。'.format(queue_index + 1))

    def on_task_editor_key_down(self, prefix, sender, args):
        if unicode(args.Key) not in [u'Return', u'Enter']:
            return
        try:
            self._apply_selected_task_from_inputs(prefix)
            args.Handled = True
        except Exception as ex:
            self._set_status(u'更新队列参数失败: {0}'.format(unicode(ex)), is_error=True)

    def _apply_selected_task_from_inputs(self, prefix):
        queue_index = self.selected_queue_index
        if queue_index is None or queue_index < 0 or queue_index >= len(self.generation_queue):
            self._set_status(u'请先在右侧预览中点击一个队列小圆点。', is_error=True)
            return
        task = self.generation_queue[queue_index]
        if task.get('prefix') != prefix:
            self._set_status(u'当前选中的队列任务属于 {}，请切换到对应专业修改。'.format(task.get('prefix', u'-')), is_error=True)
            return
        if task.get('type') == 'array':
            task['spacing'] = self._get_text('txtSpacing_' + prefix, task.get('spacing', u''))
            count_text = self._get_text('txtCount_' + prefix, u'')
            task['count'] = count_text if count_text else u'自动'
            task['h_offset'] = self._get_text('txtHorizontalOffset_' + prefix, task.get('h_offset', u'0'))
            task['v_offset'] = self._get_text('txtVerticalOffset_' + prefix, task.get('v_offset', u'0'))
            task['h_rotation'] = self._get_text('txtHorizontalRotation_' + prefix, task.get('h_rotation', u'0'))
            task['v_rotation'] = self._get_text('txtVerticalRotation_' + prefix, task.get('v_rotation', u'0'))
            task['label'] = self._get_text('txtArrayLabel_' + prefix, task.get('label', u''))
        else:
            task['h_offset'] = self._get_text('txtSweepHorizontalOffset_' + prefix, task.get('h_offset', u'0'))
            task['v_offset'] = self._get_text('txtSweepVerticalOffset_' + prefix, task.get('v_offset', u'0'))
            task['label'] = self._get_text('txtSweepLabel_' + prefix, task.get('label', u''))
        self.generation_queue[queue_index] = task
        self._refresh_task_queue_grid()
        self.update_clearance_drawings()
        self._set_status(u'已更新队列第 {0} 条参数。'.format(queue_index + 1))

    def _get_text(self, control_name, default_value):
        control = getattr(self, control_name, None)
        if control:
            return control.Text
        return default_value

    def update_clearance_drawings(self):
        from System.Windows import Media, Shapes
        from System.Windows.Controls import Canvas, TextBlock
        try:
            inner_dia = float(self.txtClearanceInnerDia.Text)
        except Exception:
            inner_dia = 5400
        try:
            outer_dia = float(self.txtClearanceOuterDia.Text)
        except Exception:
            outer_dia = 6000
        try:
            track_h = float(self.txtClearanceTrackHeight.Text)
        except Exception:
            track_h = -1500

        base_scale = 800.0 / 10000.0  # display 10m area in 800px

        center_x = 400
        center_y = 400

        def draw_canvas(canvas, prefix):
            zoom = self.preview_zoom_by_prefix.get(prefix, 1.0)
            scale = base_scale * zoom
            canvas.Children.Clear()

            # Crosshairs
            line_v = Shapes.Line()
            line_v.Stroke = Media.Brushes.LightGray
            line_v.StrokeDashArray = Media.DoubleCollection([5.0, 5.0])
            line_v.X1 = center_x
            line_v.Y1 = 0
            line_v.X2 = center_x
            line_v.Y2 = 800
            canvas.Children.Add(line_v)

            line_h = Shapes.Line()
            line_h.Stroke = Media.Brushes.LightGray
            line_h.StrokeDashArray = Media.DoubleCollection([5.0, 5.0])
            line_h.X1 = 0
            line_h.Y1 = center_y
            line_h.X2 = 800
            line_h.Y2 = center_y
            canvas.Children.Add(line_h)

            # Outer circle
            c_out = Shapes.Ellipse()
            c_out.Width = outer_dia * scale
            c_out.Height = outer_dia * scale
            c_out.Stroke = Media.Brushes.DarkGray
            c_out.StrokeThickness = 2
            c_out.Fill = Media.SolidColorBrush(Media.Color.FromArgb(20, 100, 100, 100))
            Canvas.SetLeft(c_out, center_x - c_out.Width / 2)
            Canvas.SetTop(c_out, center_y - c_out.Height / 2)
            canvas.Children.Add(c_out)

            # Inner circle
            c_in = Shapes.Ellipse()
            c_in.Width = inner_dia * scale
            c_in.Height = inner_dia * scale
            c_in.Stroke = Media.Brushes.SteelBlue
            c_in.StrokeThickness = 3
            c_in.Fill = Media.SolidColorBrush(Media.Color.FromArgb(30, 70, 130, 180))
            Canvas.SetLeft(c_in, center_x - c_in.Width / 2)
            Canvas.SetTop(c_in, center_y - c_in.Height / 2)
            canvas.Children.Add(c_in)

            # Track line
            t_line = Shapes.Line()
            t_line.Stroke = Media.Brushes.OrangeRed
            t_line.StrokeThickness = 3
            # Revit Z is up. In WPF Canvas, Y is down. So positive height (up) means smaller Y.
            # Thus y_pos = center_y - height
            y_pos = center_y - (track_h * scale)
            t_line.X1 = center_x - 3000 * scale
            t_line.Y1 = y_pos
            t_line.X2 = center_x + 3000 * scale
            t_line.Y2 = y_pos
            canvas.Children.Add(t_line)

            # Labels
            lbl_tr = TextBlock()
            lbl_tr.Text = u"轨面参考线"
            lbl_tr.Foreground = Media.Brushes.OrangeRed
            Canvas.SetLeft(lbl_tr, t_line.X2 + 10)
            Canvas.SetTop(lbl_tr, y_pos - 10)
            canvas.Children.Add(lbl_tr)

            lbl_in = TextBlock()
            lbl_in.Text = u"内径:" + str(int(inner_dia))
            lbl_in.Foreground = Media.Brushes.SteelBlue
            Canvas.SetLeft(lbl_in, center_x + (inner_dia/2 * scale) * 0.707 + 5)
            Canvas.SetTop(lbl_in, center_y - (inner_dia/2 * scale) * 0.707 - 20)
            canvas.Children.Add(lbl_in)

            if abs(zoom - 1.0) > 0.01:
                lbl_zoom = TextBlock()
                lbl_zoom.Text = u"缩放 {:.0f}%".format(zoom * 100.0)
                lbl_zoom.Foreground = Media.Brushes.DimGray
                Canvas.SetLeft(lbl_zoom, 12)
                Canvas.SetTop(lbl_zoom, 12)
                canvas.Children.Add(lbl_zoom)

        def draw_task_markers(canvas, prefix):
            """在画板上绘制属于当前专业的队列任务标注点"""
            if not hasattr(self, 'generation_queue'):
                return
            zoom = self.preview_zoom_by_prefix.get(prefix, 1.0)
            scale = base_scale * zoom
            colors = [
                Media.Brushes.Green, Media.Brushes.Blue, Media.Brushes.Purple,
                Media.Brushes.DarkCyan, Media.Brushes.DarkMagenta, Media.Brushes.Brown,
                Media.Brushes.DarkOliveGreen, Media.Brushes.Crimson,
            ]
            task_index = 0
            for queue_index, task in enumerate(self.generation_queue):
                if task.get('prefix') != prefix:
                    continue
                try:
                    h_off_mm = float(task.get('h_offset', 0))
                except Exception:
                    h_off_mm = 0.0
                try:
                    v_off_mm = float(task.get('v_offset', 0))
                except Exception:
                    v_off_mm = 0.0
                # 基于轨面位置计算标注点坐标
                px = center_x + h_off_mm * scale
                py = (center_y - (track_h * scale)) - v_off_mm * scale
                color = colors[task_index % len(colors)]
                selected = self.selected_queue_index == queue_index
                # 增加发光效果使标注点更显眼
                glow = Windows.Media.Effects.DropShadowEffect()
                glow.BlurRadius = 16 if selected else 10
                glow.ShadowDepth = 0
                glow.Color = color.Color
                glow.Opacity = 0.8
                
                dot = Shapes.Ellipse()
                dot.Width = 20.0 if selected else 14.0
                dot.Height = 20.0 if selected else 14.0
                dot.Fill = color
                dot.Stroke = Media.Brushes.Firebrick if selected else Media.Brushes.White
                dot.StrokeThickness = 3.0 if selected else 2.0
                dot.Effect = glow
                dot.ToolTip = u'队列第 {0} 条：点击后在左侧编辑，按 Enter 确认'.format(queue_index + 1)
                dot.MouseLeftButtonDown += lambda s, e, idx=queue_index, p=prefix: self.on_preview_marker_clicked(idx, p, s, e)
                radius = dot.Width / 2.0
                Canvas.SetLeft(dot, px - radius)
                Canvas.SetTop(dot, py - radius)
                canvas.Children.Add(dot)
                
                # 绘制标签文字并增加半透明背景块提升可读性
                label_text = task.get('label', '') or task.get('family_name', '')
                if label_text and label_text != u'-':
                    lbl_border = Shapes.Rectangle()
                    lbl_border.Fill = Media.SolidColorBrush(Media.Color.FromArgb(160, 255, 255, 255))
                    lbl_border.RadiusX = 4
                    lbl_border.RadiusY = 4
                    
                    lbl = TextBlock()
                    lbl.Text = u" #{} {} ".format(queue_index + 1, label_text[:15])
                    lbl.FontSize = 11.0
                    lbl.FontWeight = Windows.FontWeights.Bold
                    lbl.Foreground = Media.Brushes.Black
                    
                    Canvas.SetLeft(lbl, px + 12.0)
                    Canvas.SetTop(lbl, py - 8.0)
                    Canvas.SetLeft(lbl_border, px + 10.0)
                    Canvas.SetTop(lbl_border, py - 10.0)
                    
                    canvas.Children.Add(lbl_border)
                    canvas.Children.Add(lbl)
                task_index += 1

        prefixes = ['Clearance', 'Track', 'Arch', 'Struct', 'Vent', 'Plumb', 'Lght', 'StrPwr', 'WkPwr']
        for p in prefixes:
            canvas = getattr(self, 'canvasPreview_' + p, None)
            if canvas:
                draw_canvas(canvas, p)
                draw_task_markers(canvas, p)

    def on_input_changed(self, sender, args):
        self._capture_state_from_controls()
        self.refresh_preview(silent=True)

    def on_mode_changed(self, sender, args):
        self._capture_state_from_controls()
        self._apply_mode_visuals()
        self.update_clearance_drawings()
        self.refresh_preview(silent=True)

    def on_select_curve(self, sender, args):
        self._capture_state_from_controls()
        self.state.requested_action = 'pick_curve'
        self.Close()

    def on_select_family(self, sender, args):
        self._capture_state_from_controls()
        self.state.requested_action = 'pick_family_type'
        self.Close()

    def on_pick_placed_family(self, sender, args):
        self._capture_state_from_controls()
        self.state.requested_action = 'pick_placed_family'
        self.Close()

    def on_select_profile(self, sender, args):
        self._capture_state_from_controls()
        self.state.requested_action = 'pick_profile'
        self.Close()

    def on_select_profile_family(self, sender, args):
        self._capture_state_from_controls()
        self.state.requested_action = 'pick_profile_family'
        self.Close()

    def on_import_alignment_csv(self, sender, args):
        csv_path = forms.pick_file(file_ext='csv')
        if not csv_path:
            return
        try:
            points = alignment.read_alignment_points_from_csv(csv_path)
            self.state.alignment_points = points
            self._refresh_alignment_grid()
            self._set_status(u'已成功导入 {0} 个线路坐标点。'.format(len(points)))
        except Exception as e:
            forms.alert(unicode(e))

    def on_generate_alignment_spline(self, sender, args):
        if not self.state.alignment_points:
            forms.alert(u'请先导入线路坐标点。', exitscript=False)
            return
        self._capture_state_from_controls()
        self.state.requested_action = 'generate_spline'
        self.Close()


    def on_select_family_prefix(self, prefix):
        self._capture_state_from_controls()
        self.state.requested_action = 'pick_family_type'
        self.state.active_prefix = prefix
        self.Close()

    def on_pick_placed_family_prefix(self, prefix):
        self._capture_state_from_controls()
        self.state.requested_action = 'pick_placed_family'
        self.state.active_prefix = prefix
        self.Close()

    def on_select_profile_prefix(self, prefix):
        self._capture_state_from_controls()
        self.state.requested_action = 'pick_profile'
        self.state.active_prefix = prefix
        self.Close()

    def on_select_profile_family_prefix(self, prefix):
        self._capture_state_from_controls()
        self.state.requested_action = 'pick_profile_family'
        self.state.active_prefix = prefix
        self.Close()

    def on_select_family_prefix(self, prefix):
        self._capture_state_from_controls()
        self.state.requested_action = 'pick_family_type'
        self.state.active_prefix = prefix
        self.Close()

    def on_pick_placed_family_prefix(self, prefix):
        self._capture_state_from_controls()
        self.state.requested_action = 'pick_placed_family'
        self.state.active_prefix = prefix
        self.Close()

    def on_select_profile_prefix(self, prefix):
        self._capture_state_from_controls()
        self.state.requested_action = 'pick_profile'
        self.state.active_prefix = prefix
        self.Close()

    def on_select_profile_family_prefix(self, prefix):
        self._capture_state_from_controls()
        self.state.requested_action = 'pick_profile_family'
        self.state.active_prefix = prefix
        self.Close()

    def _refresh_alignment_grid(self):
        pass  # 坐标列表已替换为任务队列

    def _refresh_task_queue_grid(self):
        """刷新总控面板中的任务队列 DataGrid"""
        try:
            self.state.generation_queue = list(getattr(self, 'generation_queue', []) or [])
            from System.Collections.ObjectModel import ObservableCollection
            rows = ObservableCollection[object]()
            prefix_names = {
                'Track': u'轨道', 'Arch': u'建筑', 'Struct': u'结构',
                'Vent': u'通风', 'Plumb': u'给排水', 'Lght': u'动照',
                'StrPwr': u'强电', 'WkPwr': u'弱电',
            }
            for i, task in enumerate(self.generation_queue):
                row = TaskQueueRow(
                    i + 1,
                    task.get('label', u''),
                    u'阵列' if task.get('type') == 'array' else u'放样',
                    prefix_names.get(task.get('prefix'), task.get('prefix', u'-')),
                    task.get('family_name', u'-'),
                    task.get('spacing', u'-'),
                    task.get('count', u'-'),
                    task.get('h_offset', u'0'),
                    task.get('v_offset', u'0'),
                    task.get('h_rotation', u'0'),
                    task.get('v_rotation', u'0'),
                )
                rows.Add(row)
            self.gridTaskQueue.ItemsSource = rows
            if self.selected_queue_index is not None and 0 <= self.selected_queue_index < len(self.generation_queue):
                try:
                    self.gridTaskQueue.SelectedIndex = self.selected_queue_index
                except Exception:
                    pass
        except Exception:
            pass

    def on_task_queue_selection_changed(self, sender, args):
        try:
            selected_row = self.gridTaskQueue.SelectedItem
            if selected_row is None:
                return
            queue_index = int(selected_row.Index) - 1
            if queue_index < 0 or queue_index >= len(self.generation_queue):
                return
            task = self.generation_queue[queue_index]
            prefix = task.get('prefix')
            self.selected_queue_index = queue_index
            self.state.selected_queue_index = queue_index
            self.state.active_prefix = prefix
            self._load_task_into_prefix_inputs(queue_index)
            self.update_clearance_drawings()
            self._select_active_tab()
        except Exception as ex:
            self._set_status(u'载入队列任务失败: {0}'.format(unicode(ex)), is_error=True)

    def on_refresh_preview(self, sender, args):
        self.refresh_preview()

    def on_add_config(self, sender, args):
        try:
            self._capture_state_from_controls()
            config_entry = build_config_entry_from_state(self.state)
            validate_config_entry(config_entry)
            self.state.config_entries.append(config_entry)
            self.state.selected_config_id = config_entry.config_id
            self.state.next_config_id += 1
            self._refresh_config_grid()
            self._set_status(u'已将当前配置加入批量列表。')
        except Exception as ex:
            forms.alert(unicode(ex), exitscript=False)

    def on_update_config(self, sender, args):
        try:
            self._capture_state_from_controls()
            selected_entry = find_config_entry(self.state, self.state.selected_config_id)
            if selected_entry is None:
                forms.alert(u'请先在批量配置列表中选中一条配置。', exitscript=False)
                return
            updated_entry = build_config_entry_from_state(self.state, config_id=selected_entry.config_id)
            validate_config_entry(updated_entry)
            replace_config_entry(self.state, updated_entry)
            self._refresh_config_grid()
            self._set_status(u'已更新选中的批量配置。')
        except Exception as ex:
            forms.alert(unicode(ex), exitscript=False)

    def on_remove_config(self, sender, args):
        selected_entry = find_config_entry(self.state, self.state.selected_config_id)
        if selected_entry is None:
            forms.alert(u'请先在批量配置列表中选中一条配置。', exitscript=False)
            return
        self.state.config_entries = [x for x in self.state.config_entries if x.config_id != selected_entry.config_id]
        self.state.selected_config_id = None
        self._refresh_config_grid()
        self._set_status(u'已删除选中的批量配置。')

    def on_delete_generated(self, sender, args):
        self._capture_state_from_controls()
        self.state.requested_action = 'delete_generated'
        self.Close()

    def on_preview_selection_changed(self, sender, args):
        if self.layout_result is None or not self.layout_result.items:
            self._draw_normal_plane(None)
            return

        selected_item = self.gridPreview.SelectedItem
        if selected_item is None:
            self._show_preview_item(self.layout_result.items[0])
            return

        row_index = int(selected_item.Index) - 1
        if 0 <= row_index < len(self.layout_result.items):
            self._show_preview_item(self.layout_result.items[row_index])

    def on_config_selection_changed(self, sender, args):
        if self.handling_config_selection:
            return
        selected_row = self.gridConfigs.SelectedItem
        if selected_row is None:
            self.state.selected_config_id = None
            return

        config_entry = find_config_entry(self.state, selected_row.ConfigId)
        if config_entry is None:
            return

        self.state.selected_config_id = config_entry.config_id
        self._apply_config_entry_to_editor(config_entry)
        self.refresh_preview(silent=True)
        self._set_status(u'已载入批量配置 #{0} 到当前编辑区。'.format(config_entry.config_id))

    def on_preview_canvas_size_changed(self, sender, args):
        if self.layout_result is not None and self.layout_result.items:
            selected_item = self.gridPreview.SelectedItem
            if selected_item is None:
                self._show_preview_item(self.layout_result.items[0])
            else:
                row_index = int(selected_item.Index) - 1
                if 0 <= row_index < len(self.layout_result.items):
                    self._show_preview_item(self.layout_result.items[row_index])
        else:
            self._draw_normal_plane(None)

    def refresh_preview(self, silent=False, return_layout=False):
        if not hasattr(self, 'gridPreview'): return None if return_layout else None
        try:
            layout_result = build_layout_from_editor_state(self.state)
        except Exception as ex:
            self.layout_result = None
            self._clear_preview_grid()
            self._reset_preview_text()
            self._draw_normal_plane(None)
            if not silent:
                self._set_status(unicode(ex), is_error=True)
            if return_layout:
                return None
            return

        self.layout_result = layout_result
        self._populate_preview_grid(layout_result)
        self._update_summary(layout_result)
        if layout_result.items:
            self.gridPreview.SelectedIndex = 0
            self._show_preview_item(layout_result.items[0])
        else:
            self._draw_normal_plane(None)

        if layout_result.valid:
            if not silent:
                self._set_status(layout_result.message)
        else:
            self._set_status(layout_result.message, is_error=True)

        if return_layout:
            return layout_result

    def _load_state_into_controls(self):
        if not hasattr(self, 'cmbMode'): return
        self.cmbMode.SelectedIndex = 0 if self.state.mode_text == u'family' else 1
        self.txtSpacing.Text = self.state.spacing_text
        self.txtCount.Text = self.state.count_text
        self.txtHorizontalOffset.Text = self.state.horizontal_offset_text
        self.txtVerticalOffset.Text = self.state.vertical_offset_text
        self.txtHorizontalRotation.Text = self.state.horizontal_rotation_text
        self.txtVerticalRotation.Text = self.state.vertical_rotation_text
        self._apply_curve_selection(self.curve_selection)
        self._apply_symbol_info(self.symbol_info)
        self._apply_profile_selection(self.profile_selection)
        self._apply_active_prefix_info()

        # Load global segment controls
        if hasattr(self, 'txtStartDist_Dashboard'):
            self.txtStartDist_Dashboard.Text = getattr(self.state, 'global_start_dist', u'0')
            self.txtEndDist_Dashboard.Text = getattr(self.state, 'global_end_dist', u'')
            self.txtSegmentLength_Dashboard.Text = getattr(self.state, 'global_segment_length', u'500')
        self._select_active_tab()

    def _apply_active_prefix_info(self):
        active_prefix = getattr(self.state, 'active_prefix', None)
        prefixes = list(DISCIPLINE_PREFIXES)
        if active_prefix and active_prefix not in prefixes:
            prefixes.append(active_prefix)
        symbol_infos = getattr(self, 'symbol_infos_by_prefix', {}) or {}
        profile_selections = getattr(self, 'profile_selections_by_prefix', {}) or {}
        for p in prefixes:
            self._apply_prefix_symbol_info(p, symbol_infos.get(p))
            self._apply_prefix_profile_selection(p, profile_selections.get(p))

    def _format_symbol_info_text(self, symbol_info):
        extra_line = u''
        if symbol_info.source_instance_id is not None:
            extra_line = u'\n来源实例: {0}'.format(symbol_info.source_instance_id)
        return u'类别: {0}\n族: {1}\n类型: {2}\n放置方式: {3}{4}'.format(
            symbol_info.category_name,
            symbol_info.family_name,
            symbol_info.type_name,
            core.get_placement_type_label(symbol_info.placement_type),
            extra_line,
        )

    def _apply_prefix_symbol_info(self, prefix, symbol_info):
        if not prefix or not hasattr(self, 'txtFamilyInfo_' + prefix):
            return
        txt = getattr(self, 'txtFamilyInfo_' + prefix)
        txt.Text = self._format_symbol_info_text(symbol_info) if symbol_info else u'尚未选择族类型。'

    def _apply_prefix_profile_selection(self, prefix, profile_selection):
        if not prefix or not hasattr(self, 'txtProfileInfo_' + prefix):
            return
        txt = getattr(self, 'txtProfileInfo_' + prefix)
        txt.Text = profile_selection.description if profile_selection else u'尚未选择放样轮廓。'

    def _select_active_tab(self):
        if not hasattr(self, 'tabMain'):
            return
        try:
            prefix = getattr(self.state, 'active_prefix', None)
            if prefix in PREFIX_TAB_INDEX:
                self.tabMain.SelectedIndex = PREFIX_TAB_INDEX[prefix]
            else:
                self.tabMain.SelectedIndex = int(getattr(self.state, 'active_tab_index', 0) or 0)
        except Exception:
            pass


    def _capture_state_from_controls(self):
        if not hasattr(self, 'cmbMode'): return
        self.state.mode_text = u'family' if self.cmbMode.SelectedIndex <= 0 else u'sweep'
        self.state.spacing_text = self.txtSpacing.Text
        self.state.count_text = self.txtCount.Text
        self.state.horizontal_offset_text = self.txtHorizontalOffset.Text
        self.state.vertical_offset_text = self.txtVerticalOffset.Text
        self.state.horizontal_rotation_text = self.txtHorizontalRotation.Text
        self.state.vertical_rotation_text = self.txtVerticalRotation.Text
        self.state.curve_selection = self.curve_selection
        self.state.symbol_info = self.symbol_info
        self.state.profile_selection = self.profile_selection
        self.state.symbol_infos_by_prefix = dict(getattr(self, 'symbol_infos_by_prefix', {}) or {})
        self.state.profile_selections_by_prefix = dict(getattr(self, 'profile_selections_by_prefix', {}) or {})
        self.state.generation_queue = list(getattr(self, 'generation_queue', []) or [])
        self.state.preview_zoom_by_prefix = dict(getattr(self, 'preview_zoom_by_prefix', {}) or {})
        self.state.selected_queue_index = self.selected_queue_index
        if hasattr(self, 'tabMain'):
            try:
                self.state.active_tab_index = self.tabMain.SelectedIndex
            except Exception:
                pass

        # Capture global segment controls
        if hasattr(self, 'txtStartDist_Dashboard'):
            self.state.global_start_dist = self.txtStartDist_Dashboard.Text
            self.state.global_end_dist = self.txtEndDist_Dashboard.Text
            self.state.global_segment_length = self.txtSegmentLength_Dashboard.Text

    def _apply_curve_selection(self, curve_selection):
        self.curve_selection = curve_selection
        if curve_selection is None:
            self.txtCurveInfo.Text = u'尚未选择曲线。'
            return
        curve_length_mm = core.ft_to_mm(core.get_curve_length(curve_selection.curve))
        self.txtCurveInfo.Text = u'{0}\n曲线长度: {1:.1f} mm'.format(
            curve_selection.description,
            curve_length_mm,
        )

    def _apply_symbol_info(self, symbol_info):
        if not hasattr(self, 'txtFamilyInfo'): return
        if not hasattr(self, 'txtFamilyInfo'): return
        self.symbol_info = symbol_info
        if symbol_info is None:
            self.txtFamilyInfo.Text = u'尚未选择族类型。'
            return
        extra_line = u''
        if symbol_info.source_instance_id is not None:
            extra_line = u'\n来源实例: {0}'.format(symbol_info.source_instance_id)
        self.txtFamilyInfo.Text = u'类别: {0}\n族: {1}\n类型: {2}\n放置方式: {3}{4}'.format(
            symbol_info.category_name,
            symbol_info.family_name,
            symbol_info.type_name,
            core.get_placement_type_label(symbol_info.placement_type),
            extra_line,
        )

    def _apply_profile_selection(self, profile_selection):
        if not hasattr(self, 'txtProfileInfo'): return
        if not hasattr(self, 'txtProfileInfo'): return
        self.profile_selection = profile_selection
        if profile_selection is None:
            self.txtProfileInfo.Text = u'尚未选择封闭轮廓。'
            return
        self.txtProfileInfo.Text = profile_selection.description

    def _apply_config_entry_to_editor(self, config_entry):
        self.curve_selection = config_entry.curve_selection
        self.symbol_info = config_entry.symbol_info
        self.profile_selection = config_entry.profile_selection
        self.txtSpacing.Text = config_entry.spacing_text
        self.txtCount.Text = config_entry.count_text
        self.txtHorizontalOffset.Text = config_entry.horizontal_offset_text
        self.txtVerticalOffset.Text = config_entry.vertical_offset_text
        self.txtHorizontalRotation.Text = config_entry.horizontal_rotation_text
        self.txtVerticalRotation.Text = config_entry.vertical_rotation_text
        self.cmbMode.SelectedIndex = 0 if config_entry.mode_text == u'family' else 1
        self._capture_state_from_controls()
        self._apply_curve_selection(config_entry.curve_selection)
        self._apply_symbol_info(config_entry.symbol_info)
        self._apply_profile_selection(config_entry.profile_selection)
        self._apply_mode_visuals()
        self.update_clearance_drawings()

    def _refresh_config_grid(self):
        if not hasattr(self, 'gridConfigs'): return
        self.handling_config_selection = True
        self.config_rows = [ConfigListRow(x) for x in self.state.config_entries]
        self.gridConfigs.ItemsSource = None
        self.gridConfigs.ItemsSource = self.config_rows

        if self.state.selected_config_id is not None:
            for index, row in enumerate(self.config_rows):
                if row.ConfigId == self.state.selected_config_id:
                    self.gridConfigs.SelectedIndex = index
                    break
        self.handling_config_selection = False

    def _populate_preview_grid(self, layout_result):
        rows = []
        for item in layout_result.items:
            rows.append(PreviewRow(
                index=item.index,
                distance_mm=u'{0:.1f}'.format(core.ft_to_mm(item.distance_ft)),
                x_mm=u'{0:.1f}'.format(core.ft_to_mm(item.target_point.X)),
                y_mm=u'{0:.1f}'.format(core.ft_to_mm(item.target_point.Y)),
                z_mm=u'{0:.1f}'.format(core.ft_to_mm(item.target_point.Z)),
                note=u'基点 {0}'.format(core.format_xyz_mm(item.base_point)),
            ))
        self.preview_rows = rows
        self.gridPreview.ItemsSource = None
        self.gridPreview.ItemsSource = self.preview_rows

    def _clear_preview_grid(self):
        self.preview_rows = []
        self.gridPreview.ItemsSource = None

    def _update_summary(self, layout_result):
        if layout_result is None:
            self._reset_preview_text()
            return

        summary_text = u'当前编辑配置 | 曲线长度: {0:.1f} mm | 预览数量: {1} | 覆盖长度: {2:.1f} mm'.format(
            core.ft_to_mm(layout_result.curve_length_ft),
            layout_result.resolved_count,
            core.ft_to_mm(layout_result.coverage_ft),
        )
        summary_text += u'\n模式: {0}'.format(u'族沿线阵列' if self.state.mode_text == u'family' else u'封闭轮廓沿线放样')
        summary_text += u'\n目标: {0}'.format(summarize_target(build_config_entry_from_state(self.state, config_id=0)))
        summary_text += u'\n批量配置数量: {0}'.format(len(self.state.config_entries))
        if not layout_result.valid:
            summary_text += u'\n当前预览不可布置。'
        self.txtSummary.Text = summary_text

        if layout_result.items:
            self._set_normal_plane_info(layout_result.items[0])
        else:
            self.txtNormalPlaneInfo.Text = u'下方示意图展示所选预览点在法向平面上的偏移位置。'

    def _reset_preview_text(self):
        self.txtSummary.Text = u'选择曲线并输入参数后会在这里显示曲线长度、数量和覆盖长度。'
        self.txtNormalPlaneInfo.Text = u'下方示意图展示所选预览点在法向平面上的偏移位置。'

    def _show_preview_item(self, preview_item):
        self._draw_normal_plane(preview_item)
        self._set_normal_plane_info(preview_item)

    def _set_normal_plane_info(self, preview_item):
        self.txtNormalPlaneInfo.Text = u'当前示意点: 第 {0} 个 | 距起点 {1:.1f} mm | 目标坐标 {2}'.format(
            preview_item.index,
            core.ft_to_mm(preview_item.distance_ft),
            core.format_xyz_mm(preview_item.target_point),
        )

    def _draw_normal_plane(self, placement_item):
        if not hasattr(self, 'previewCanvas'): return
        self.previewCanvas.Children.Clear()

        canvas_width = self.previewCanvas.ActualWidth or self.previewCanvas.MinWidth or 320.0
        canvas_height = self.previewCanvas.ActualHeight or self.previewCanvas.MinHeight or 320.0
        center_x = canvas_width / 2.0
        center_y = canvas_height / 2.0
        padding = 24.0

        horizontal_axis = self._make_line(padding, center_y, canvas_width - padding, center_y, '#FF9CB6D1', 1.4)
        vertical_axis = self._make_line(center_x, canvas_height - padding, center_x, padding, '#FF7D8FA3', 1.4)
        self.previewCanvas.Children.Add(horizontal_axis)
        self.previewCanvas.Children.Add(vertical_axis)

        self._add_text(u'+H', canvas_width - 42, center_y + 6, '#FF1E6091')
        self._add_text(u'+V', center_x + 6, padding, '#FF7A3E00')
        self._add_text(u'基点', center_x + 8, center_y + 8, '#FF4F5B66')

        if placement_item is None:
            self._add_text(u'选择曲线并输入参数后显示预览。', 46, 24, '#FF4F5B66')
            return

        offset_vector = placement_item.target_point.Subtract(placement_item.base_point)
        horizontal_mm = core.ft_to_mm(offset_vector.DotProduct(placement_item.horizontal))
        vertical_mm = core.ft_to_mm(offset_vector.DotProduct(placement_item.vertical))

        scale_base = max(abs(horizontal_mm), abs(vertical_mm), 100.0)
        available_x = max(center_x - padding - 18.0, 40.0)
        available_y = max(center_y - padding - 18.0, 40.0)
        scale = min(available_x / scale_base, available_y / scale_base)

        marker_x = center_x + horizontal_mm * scale
        marker_y = center_y - vertical_mm * scale

        connector = self._make_line(center_x, center_y, marker_x, marker_y, '#FF2A6E3F', 2.0)
        self.previewCanvas.Children.Add(connector)

        marker = Windows.Shapes.Ellipse()
        marker.Width = 16
        marker.Height = 16
        marker.Fill = Media.Brushes.OrangeRed
        marker.Stroke = Media.Brushes.White
        marker.StrokeThickness = 1.5
        marker.Margin = Windows.Thickness(marker_x - 8, marker_y - 8, 0, 0)
        self.previewCanvas.Children.Add(marker)

        text_left = min(max(marker_x + 12, padding), canvas_width - 120)
        text_top = min(max(marker_y - 10, padding), canvas_height - 60)
        self._add_text(
            u'目标点\nH {0:.1f} mm\nV {1:.1f} mm'.format(horizontal_mm, vertical_mm),
            text_left,
            text_top,
            '#FF24313C'
        )

    def _make_line(self, x1, y1, x2, y2, color_hex, thickness):
        line = Windows.Shapes.Line()
        line.X1 = x1
        line.Y1 = y1
        line.X2 = x2
        line.Y2 = y2
        line.Stroke = brush_converter.ConvertFrom(color_hex)
        line.StrokeThickness = thickness
        return line

    def _add_text(self, text, left, top, color_hex):
        text_block = Controls.TextBlock()
        text_block.Text = text
        text_block.Foreground = brush_converter.ConvertFrom(color_hex)
        text_block.Margin = Windows.Thickness(left, top, 0, 0)
        self.previewCanvas.Children.Add(text_block)


    def on_save_project(self, sender, args):
        import shutil
        from pyrevit import forms
        try:
            self._capture_state_from_controls()
            # 同步当前状态到核心数据库
            self._sync_state_to_db()
            
            db_path = core.db_manager.db_path
            dest_path = forms.save_file(file_ext='db', default_name='LinerMaster_Project.db')
            if dest_path:
                shutil.copy2(db_path, dest_path)
                self._set_status(u'项目数据已成功导出至: {}'.format(os.path.basename(dest_path)))
                forms.alert('项目已保存成功！', title='区间自动建模')
        except Exception as e:
            forms.alert(u'保存失败: ' + str(e))

    def _sync_state_to_db(self):
        """将当前内存中的队列和全局设置写入 SQLite 数据库"""
        try:
            dm = core.db_manager
            # 保存任务队列
            dm.set_config('Global', 'TaskQueue', self.generation_queue)
            # 保存全局分段设置
            global_segments = {
                'start': self.state.global_start_dist,
                'end': self.state.global_end_dist,
                'length': self.state.global_segment_length,
            }
            dm.set_config('Global', 'GlobalSegments', global_segments)
            # 保存限界设置
            clearance = {
                'inner': self.txtClearanceInnerDia.Text if hasattr(self, 'txtClearanceInnerDia') else '5400',
                'outer': self.txtClearanceOuterDia.Text if hasattr(self, 'txtClearanceOuterDia') else '6000',
                'height': self.txtClearanceTrackHeight.Text if hasattr(self, 'txtClearanceTrackHeight') else '-1500',
            }
            dm.set_config('Global', 'Clearance', clearance)
        except Exception as e:
            print("Sync to DB failed: " + str(e))

    def on_load_project(self, sender, args):
        import shutil
        from pyrevit import forms
        try:
            src_path = forms.pick_file(file_ext='db')
            if src_path:
                db_path = core.db_manager.db_path
                shutil.copy2(src_path, db_path)
                
                # 从新覆盖的数据库中读取数据并应用到 UI
                self._load_state_from_db()
                self._load_state_into_controls()
                self._refresh_task_queue_grid()
                self.update_clearance_drawings()
                
                self._set_status(u'项目数据已从 {} 成功导入。'.format(os.path.basename(src_path)))
                forms.alert(u'项目已读取并刷新界面！', title='LinerMaster')
        except Exception as e:
            forms.alert(u'读取失败: ' + str(e))

    def _load_state_from_db(self):
        """从 SQLite 数据库加载全局数据到内存状态"""
        try:
            dm = core.db_manager
            # 加载队列
            queue = dm.get_config('Global', 'TaskQueue')
            if queue:
                self.generation_queue = list(queue)
                self.state.generation_queue = list(self.generation_queue)
            
            # 加载全局设置
            gs = dm.get_config('Global', 'GlobalSegments')
            if gs:
                self.state.global_start_dist = gs.get('start', '0')
                self.state.global_end_dist = gs.get('end', '')
                self.state.global_segment_length = gs.get('length', '500')
            
            # 加载限界
            c = dm.get_config('Global', 'Clearance')
            if c:
                if hasattr(self, 'txtClearanceInnerDia'): self.txtClearanceInnerDia.Text = c.get('inner', '5400')
                if hasattr(self, 'txtClearanceOuterDia'): self.txtClearanceOuterDia.Text = c.get('outer', '6000')
                if hasattr(self, 'txtClearanceTrackHeight'): self.txtClearanceTrackHeight.Text = c.get('height', '-1500')
        except Exception as e:
            print("Load from DB failed: " + str(e))

    def on_generate_array_prefix(self, prefix):
        self._capture_state_from_controls()
        self.state.active_prefix = prefix
        symbol_info = (getattr(self, 'symbol_infos_by_prefix', {}) or {}).get(prefix)
        if symbol_info is None:
            self._set_status(u'{} 尚未选择族类型，不能加入阵列任务。'.format(prefix), is_error=True)
            return
        family_name = u'{0}: {1}'.format(symbol_info.family_name, symbol_info.type_name)
        spacing = getattr(self, 'txtSpacing_' + prefix, None)
        spacing_val = spacing.Text if spacing else '-'
        count = getattr(self, 'txtCount_' + prefix, None)
        count_val = count.Text if count and count.Text else u'自动'
        h_off = getattr(self, 'txtHorizontalOffset_' + prefix, None)
        v_off = getattr(self, 'txtVerticalOffset_' + prefix, None)
        h_rot = getattr(self, 'txtHorizontalRotation_' + prefix, None)
        v_rot = getattr(self, 'txtVerticalRotation_' + prefix, None)
        label_box = getattr(self, 'txtArrayLabel_' + prefix, None)
        label_val = label_box.Text if label_box and label_box.Text else u''
        
        # 保存到任务队列
        self.generation_queue.append({
            'type': 'array',
            'prefix': prefix,
            'label': label_val,
            'family_name': family_name,
            'symbol_info': symbol_info,
            'spacing': spacing_val,
            'count': count_val,
            'h_offset': h_off.Text if h_off else '0',
            'v_offset': v_off.Text if v_off else '0',
            'h_rotation': h_rot.Text if h_rot else '0',
            'v_rotation': v_rot.Text if v_rot else '0',
        })
        self.selected_queue_index = len(self.generation_queue) - 1
        self.state.selected_queue_index = self.selected_queue_index
        self._refresh_task_queue_grid()
        self.update_clearance_drawings()
        self._select_active_tab()
        self._set_status(u'已添加 {} 阵列任务到队列。'.format(prefix))

    def _load_project_base_point(self):
        """从当前文档读取项目基点数据并显示在 UI"""
        from Autodesk.Revit.DB import BuiltInCategory, BuiltInParameter, FilteredElementCollector
        doc = __revit__.ActiveUIDocument.Document
        try:
            # 获取项目基点
            bp = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_ProjectBasePoint).FirstElement()
            if bp:
                # 获取参数 (Revit 内部单位是英尺)
                p_n = bp.get_Parameter(BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM)
                p_e = bp.get_Parameter(BuiltInParameter.BASEPOINT_EASTWEST_PARAM)
                p_z = bp.get_Parameter(BuiltInParameter.BASEPOINT_ELEVATION_PARAM)
                p_a = get_basepoint_angle_param(bp, BuiltInParameter)
                
                if hasattr(self, 'txtBasePointN'): self.txtBasePointN.Text = "{:.4f}".format(core.ft_to_m(p_n.AsDouble()) if p_n else 0.0)
                if hasattr(self, 'txtBasePointE'): self.txtBasePointE.Text = "{:.4f}".format(core.ft_to_m(p_e.AsDouble()) if p_e else 0.0)
                if hasattr(self, 'txtBasePointElev'): self.txtBasePointElev.Text = "{:.4f}".format(core.ft_to_m(p_z.AsDouble()) if p_z else 0.0)
                if hasattr(self, 'txtBasePointAngle'): self.txtBasePointAngle.Text = "{:.4f}".format(math.degrees(p_a.AsDouble()) if p_a else 0.0)
        except Exception as e:
            print("Failed to load base point: " + str(e))

    def on_apply_base_point(self, sender, args):
        """应用项目基点修改"""
        from pyrevit import forms
        from Autodesk.Revit.DB import BuiltInCategory, BuiltInParameter, FilteredElementCollector, Transaction
        
        res = forms.alert(u"确认是否需要修改项目基点？\n这可能会影响整个模型的坐标系统，请谨慎操作。", 
                          options=[u"确认修改", u"取消"], 
                          title=u"区间自动建模")
        if res != u"确认修改":
            return

        doc = __revit__.ActiveUIDocument.Document
        try:
            bp = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_ProjectBasePoint).FirstElement()
            if not bp:
                forms.alert(u"未找到项目基点元素。")
                return

            t = Transaction(doc, u'修改项目基点')
            t.Start()
            
            # 读取 UI 值并转换为英尺
            val_n = core.m_to_ft(float(self.txtBasePointN.Text))
            val_e = core.m_to_ft(float(self.txtBasePointE.Text))
            val_z = core.m_to_ft(float(self.txtBasePointElev.Text))
            val_a = math.radians(float(self.txtBasePointAngle.Text))
            
            # 设置参数
            p_n = bp.get_Parameter(BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM)
            p_e = bp.get_Parameter(BuiltInParameter.BASEPOINT_EASTWEST_PARAM)
            p_z = bp.get_Parameter(BuiltInParameter.BASEPOINT_ELEVATION_PARAM)
            for param, value in [(p_n, val_n), (p_e, val_e), (p_z, val_z)]:
                if param and not param.IsReadOnly:
                    param.Set(value)
            p_a = get_basepoint_angle_param(bp, BuiltInParameter)
            if p_a and not p_a.IsReadOnly:
                p_a.Set(val_a)
            
            t.Commit()
            self._set_status(u"项目基点修改成功！")
            forms.alert(u"项目基点已成功更新。")
        except Exception as e:
            if 't' in locals() and t.GetStatus().ToString() == 'Started':
                t.RollBack()
            forms.alert(u"修改失败: " + str(e))

    def on_generate_sweep_prefix(self, prefix):
        self._capture_state_from_controls()
        self.state.active_prefix = prefix
        profile_selection = (getattr(self, 'profile_selections_by_prefix', {}) or {}).get(prefix)
        if profile_selection is None:
            self._set_status(u'{} 尚未选择放样轮廓，不能加入放样任务。'.format(prefix), is_error=True)
            return
        profile_name = profile_selection.description[:60]
        h_off = getattr(self, 'txtSweepHorizontalOffset_' + prefix, None)
        v_off = getattr(self, 'txtSweepVerticalOffset_' + prefix, None)
        label_box = getattr(self, 'txtSweepLabel_' + prefix, None)
        label_val = label_box.Text if label_box and label_box.Text else u''
        self.generation_queue.append({
            'type': 'sweep', 'prefix': prefix,
            'label': label_val,
            'family_name': profile_name,
            'profile_selection': profile_selection,
            'spacing': u'-',
            'count': u'-',
            'h_offset': h_off.Text if h_off else '0',
            'v_offset': v_off.Text if v_off else '0',
            'h_rotation': u'-',
            'v_rotation': u'-',
        })
        self.selected_queue_index = len(self.generation_queue) - 1
        self.state.selected_queue_index = self.selected_queue_index
        self._refresh_task_queue_grid()
        self.update_clearance_drawings()
        self._select_active_tab()
        self._set_status(u'已添加 {} 放样任务到队列。当前队列任务数: {}'.format(prefix, len(self.generation_queue)))

    def on_remove_queue_task(self, sender, args):
        try:
            sel = self.gridTaskQueue.SelectedItem
            if sel is not None:
                idx = int(sel.Index) - 1
                if 0 <= idx < len(self.generation_queue):
                    self.generation_queue.pop(idx)
                    if self.selected_queue_index == idx:
                        self.selected_queue_index = None
                    elif self.selected_queue_index is not None and self.selected_queue_index > idx:
                        self.selected_queue_index -= 1
                    self.state.selected_queue_index = self.selected_queue_index
                    self._refresh_task_queue_grid()
                    self.update_clearance_drawings()
                    self._set_status(u'已移除第 {} 条任务。剩余任务数: {}'.format(idx + 1, len(self.generation_queue)))
        except Exception as ex:
            self._set_status(u'移除队列任务失败: {0}'.format(unicode(ex)), is_error=True)

    def on_clear_queue(self, sender, args):
        self.generation_queue = []
        self.selected_queue_index = None
        self.state.selected_queue_index = None
        self._refresh_task_queue_grid()
        self.update_clearance_drawings()
        self._set_status(u'队列已清空。')

    def on_place(self, sender, args):
        self.on_batch_place(sender, args)

    def on_batch_place(self, sender, args):
        self._capture_state_from_controls()
        self.state.requested_action = 'place'
        self.Close()

    def on_step_place(self, sender, args):
        self._capture_state_from_controls()
        self.state.requested_action = 'step_place'
        self.Close()

    def on_save_project(self, sender, args):
        from pyrevit import forms
        dest_file = forms.save_file(file_ext='db', title=u'保存项目数据')
        if not dest_file: return
        self._capture_state_from_controls()
        try:
            import pickle
            data = {
                'config_entries': self.state.config_entries,
                'generation_queue': self.generation_queue,
                'clearance': {
                    'inner': self.txtClearanceInnerDia.Text if hasattr(self, 'txtClearanceInnerDia') else '5400',
                    'outer': self.txtClearanceOuterDia.Text if hasattr(self, 'txtClearanceOuterDia') else '6000',
                    'height': self.txtClearanceTrackHeight.Text if hasattr(self, 'txtClearanceTrackHeight') else '-1500',
                },
                'global_segments': {
                    'start': self.state.global_start_dist,
                    'end': self.state.global_end_dist,
                    'length': self.state.global_segment_length,
                }
            }
            with open(dest_file, 'wb') as f:
                pickle.dump(data, f)
            self._set_status(u'项目数据已成功储存至: {}'.format(os.path.basename(dest_file)))
        except Exception as e:
            forms.alert(u'储存失败: {}'.format(str(e)))

    def on_load_project(self, sender, args):
        from pyrevit import forms
        src_file = forms.pick_file(file_ext='db', title=u'读取项目数据')
        if not src_file: return
        try:
            import pickle
            with open(src_file, 'rb') as f:
                data = pickle.load(f)
            
            if 'config_entries' in data: self.state.config_entries = data['config_entries']
            if 'generation_queue' in data:
                self.generation_queue = list(data['generation_queue'])
                self.state.generation_queue = list(self.generation_queue)
            
            if 'clearance' in data:
                c = data['clearance']
                if hasattr(self, 'txtClearanceInnerDia'): self.txtClearanceInnerDia.Text = c.get('inner', '5400')
                if hasattr(self, 'txtClearanceOuterDia'): self.txtClearanceOuterDia.Text = c.get('outer', '6000')
                if hasattr(self, 'txtClearanceTrackHeight'): self.txtClearanceTrackHeight.Text = c.get('height', '-1500')
            
            if 'global_segments' in data:
                g = data['global_segments']
                self.state.global_start_dist = g.get('start', '0')
                self.state.global_end_dist = g.get('end', '')
                self.state.global_segment_length = g.get('length', '500')

            self._load_state_into_controls()
            self._refresh_task_queue_grid()
            self.update_clearance_drawings()
            self._set_status(u'项目数据已从 {} 成功载入。'.format(os.path.basename(src_file)))
        except Exception as e:
            forms.alert(u'读取失败: {}'.format(str(e)))
        
    def on_close(self, sender, args):
        from pyrevit import forms
        res = forms.alert('关闭前是否保存当前配置数据？', options=['保存并关闭', '不保存关闭', '取消'], title='区间自动建模')
        if res == '保存并关闭':
            self._capture_state_from_controls()
            self.Close()
        elif res == '不保存关闭':
            self.Close()
        # if res == '取消', do nothing
        

    def _set_status(self, text, is_error=False):
        if not hasattr(self, 'txtStatus'): return
        self.state.status_text = text
        self.state.status_is_error = is_error
        self.txtStatus.Text = text
        self.txtStatus.Foreground = Media.Brushes.Firebrick if is_error else Media.Brushes.SeaGreen

    def _set_progress(self, value, info_text, elapsed_text):
        if not hasattr(self, 'prgBuild'): return
        self.state.progress_value = value
        self.state.progress_text = info_text
        self.state.elapsed_text = elapsed_text
        self.prgBuild.Value = max(0, min(100, value))
        self.txtProgressInfo.Text = info_text
        self.txtElapsed.Text = elapsed_text

    def _apply_mode_visuals(self):
        if not hasattr(self, 'cmbMode'): return
        is_family_mode = self.state.mode_text == u'family'
        self.cardFamilySelection.Visibility = Windows.Visibility.Visible if is_family_mode else Windows.Visibility.Collapsed
        self.cardProfileSelection.Visibility = Windows.Visibility.Collapsed if is_family_mode else Windows.Visibility.Visible
        self.gridSpacingCount.Visibility = Windows.Visibility.Visible if is_family_mode else Windows.Visibility.Collapsed
        self.btnSelectFamily.IsEnabled = is_family_mode
        self.btnPickPlacedFamily.IsEnabled = is_family_mode
        self.btnSelectProfile.IsEnabled = not is_family_mode
        self.btnSelectProfileFamily.IsEnabled = not is_family_mode
        self.txtSpacing.IsEnabled = is_family_mode
        self.txtCount.IsEnabled = is_family_mode
        if hasattr(self, 'btnPlace'):
            if is_family_mode:
                self.btnPlace.Content = u'开始生成族'
            else:
                self.btnPlace.Content = u'开始放样'


class FamilyTypePickerForm(Forms.Form):
    def __init__(self, symbol_infos, current_symbol_id=None):
        Forms.Form.__init__(self)
        self.Text = u'选择族类型'
        self.Width = 760
        self.Height = 210
        self.FormBorderStyle = Forms.FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.StartPosition = Forms.FormStartPosition.CenterScreen
        self.TopMost = True

        self.selected_info = None
        self.family_groups = {}

        self.lblFamily = Forms.Label()
        self.lblFamily.Text = u'族'
        self.lblFamily.Location = Drawing.Point(18, 20)
        self.lblFamily.Size = Drawing.Size(90, 22)

        self.cmbFamily = Forms.ComboBox()
        self.cmbFamily.Location = Drawing.Point(18, 45)
        self.cmbFamily.Size = Drawing.Size(700, 24)
        self.cmbFamily.DropDownStyle = Forms.ComboBoxStyle.DropDownList
        self.cmbFamily.SelectedIndexChanged += self.on_family_changed

        self.lblType = Forms.Label()
        self.lblType.Text = u'类型'
        self.lblType.Location = Drawing.Point(18, 82)
        self.lblType.Size = Drawing.Size(90, 22)

        self.cmbType = Forms.ComboBox()
        self.cmbType.Location = Drawing.Point(18, 107)
        self.cmbType.Size = Drawing.Size(700, 24)
        self.cmbType.DropDownStyle = Forms.ComboBoxStyle.DropDownList

        self.btnOk = Forms.Button()
        self.btnOk.Text = u'确定'
        self.btnOk.Location = Drawing.Point(548, 145)
        self.btnOk.Size = Drawing.Size(80, 28)
        self.btnOk.Click += self.on_ok

        self.btnCancel = Forms.Button()
        self.btnCancel.Text = u'取消'
        self.btnCancel.Location = Drawing.Point(638, 145)
        self.btnCancel.Size = Drawing.Size(80, 28)
        self.btnCancel.Click += self.on_cancel

        self.Controls.Add(self.lblFamily)
        self.Controls.Add(self.cmbFamily)
        self.Controls.Add(self.lblType)
        self.Controls.Add(self.cmbType)
        self.Controls.Add(self.btnOk)
        self.Controls.Add(self.btnCancel)

        self._load_symbol_infos(symbol_infos, current_symbol_id=current_symbol_id)

    def _load_symbol_infos(self, symbol_infos, current_symbol_id=None):
        grouped = {}
        current_family_label = None
        current_type_label = None
        for info in symbol_infos:
            family_label = u'{0} | {1} | {2}'.format(
                info.category_name,
                info.family_name,
                core.get_placement_type_label(info.placement_type),
            )
            if family_label not in grouped:
                grouped[family_label] = {}
            type_label = u'{0}'.format(info.type_name)
            if type_label in grouped[family_label]:
                type_label = u'{0} | Id {1}'.format(type_label, info.symbol_id)
            grouped[family_label][type_label] = info
            if current_symbol_id is not None and info.symbol_id == current_symbol_id:
                current_family_label = family_label
                current_type_label = type_label

        self.family_groups = grouped
        family_labels = sorted(grouped.keys())
        self.cmbFamily.Items.Clear()
        for family_label in family_labels:
            self.cmbFamily.Items.Add(family_label)

        if not family_labels:
            return

        if current_family_label in family_labels:
            self.cmbFamily.SelectedItem = current_family_label
            self._populate_type_combo(current_family_label, selected_type=current_type_label)
        else:
            self.cmbFamily.SelectedIndex = 0
            self._populate_type_combo(family_labels[0])

    def _populate_type_combo(self, family_label, selected_type=None):
        type_map = self.family_groups.get(family_label, {})
        type_labels = sorted(type_map.keys())
        self.cmbType.Items.Clear()
        for type_label in type_labels:
            self.cmbType.Items.Add(type_label)
        if not type_labels:
            return
        if selected_type in type_labels:
            self.cmbType.SelectedItem = selected_type
        else:
            self.cmbType.SelectedIndex = 0

    def on_family_changed(self, sender, args):
        family_label = self.cmbFamily.SelectedItem
        if family_label:
            self._populate_type_combo(family_label)

    def on_ok(self, sender, args):
        family_label = self.cmbFamily.SelectedItem
        type_label = self.cmbType.SelectedItem
        if not family_label or not type_label:
            Forms.MessageBox.Show(u'请先选择族和类型。', u'沿线布置族')
            return
        self.selected_info = self.family_groups.get(family_label, {}).get(type_label)
        if self.selected_info is None:
            Forms.MessageBox.Show(u'未找到所选族类型。', u'沿线布置族')
            return
        self.DialogResult = Forms.DialogResult.OK
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = Forms.DialogResult.Cancel
        self.Close()


def summarize_curve(curve_selection):
    if curve_selection is None:
        return u'未选'
    return u'元素 {0} | {1}'.format(
        curve_selection.source_element_id.IntegerValue,
        curve_selection.curve.GetType().Name,
    )


def summarize_family(symbol_info):
    if symbol_info is None:
        return u'未选'
    return u'{0} | {1}'.format(symbol_info.family_name, symbol_info.type_name)


def summarize_profile(profile_selection):
    if profile_selection is None:
        return u'未选'
    return profile_selection.description


def summarize_target(config_entry):
    if config_entry.mode_text == u'family':
        return summarize_family(config_entry.symbol_info)
    return summarize_profile(config_entry.profile_selection)


def format_duration(total_seconds):
    total_seconds = max(total_seconds or 0.0, 0.0)
    if total_seconds < 60.0:
        return u'{0:.1f} s'.format(total_seconds)

    total_minutes = int(total_seconds // 60.0)
    seconds = total_seconds - total_minutes * 60.0
    if total_minutes < 60:
        return u'{0} min {1:.1f} s'.format(total_minutes, seconds)

    hours = int(total_minutes // 60)
    minutes = total_minutes % 60
    return u'{0} h {1} min {2:.0f} s'.format(hours, minutes, seconds)


def build_progress_text(step_index, total_steps, source_label, timer_start):
    progress_ratio = float(step_index) / float(total_steps or 1)
    progress_percent = progress_ratio * 100.0
    if step_index <= 0:
        eta_text = u'预计剩余: 计算中...'
    else:
        elapsed_seconds = time.time() - timer_start
        remaining_steps = max(total_steps - step_index, 0)
        remaining_seconds = (elapsed_seconds / float(step_index)) * remaining_steps
        eta_text = u'预计剩余: {0}'.format(format_duration(remaining_seconds))
    return u'{0} | {1}/{2} ({3:.0f}%) | {4}'.format(
        source_label,
        step_index,
        total_steps,
        progress_percent,
        eta_text,
    )


def build_mode_breakdown_text(info_list):
    family_count = len([x for x in info_list if x.mode == u'family'])
    sweep_count = len([x for x in info_list if x.mode == u'sweep'])
    parts = [u'共 {0} 个'.format(len(info_list))]
    if family_count:
        parts.append(u'阵列 {0}'.format(family_count))
    if sweep_count:
        parts.append(u'放样 {0}'.format(sweep_count))
    return u' | '.join(parts)


def group_generated_infos_by_category(infos):
    grouped = {}
    for info in infos:
        category_name = info.category_name or u'<无类别>'
        grouped.setdefault(category_name, []).append(info)
    return grouped


def read_float_text(text, field_name, allow_blank=False, default=None):
    value_text = (text or u'').strip()
    if not value_text:
        if allow_blank:
            return default
        raise ValueError(u'{0}不能为空。'.format(field_name))
    try:
        return float(value_text)
    except Exception:
        raise ValueError(u'{0}必须是数字。'.format(field_name))


def read_int_text(text, field_name, allow_blank=False, default=None):
    value_text = (text or u'').strip()
    if not value_text:
        if allow_blank:
            return default
        raise ValueError(u'{0}不能为空。'.format(field_name))
    try:
        return int(value_text)
    except Exception:
        raise ValueError(u'{0}必须是整数。'.format(field_name))


def build_config_entry_from_state(state, config_id=None):
    if config_id is None:
        config_id = state.next_config_id
    return ConfigEntry(
        config_id=config_id,
        mode_text=state.mode_text,
        curve_selection=state.curve_selection,
        symbol_info=state.symbol_info,
        profile_selection=state.profile_selection,
        spacing_text=state.spacing_text,
        count_text=state.count_text,
        horizontal_offset_text=state.horizontal_offset_text,
        vertical_offset_text=state.vertical_offset_text,
        horizontal_rotation_text=state.horizontal_rotation_text,
        vertical_rotation_text=state.vertical_rotation_text,
    )


def validate_config_entry(config_entry):
    if config_entry.curve_selection is None:
        raise ValueError(u'当前编辑区尚未选择曲线。')
    if config_entry.mode_text == u'family' and config_entry.symbol_info is None:
        raise ValueError(u'当前编辑区尚未选择族类型。')
    if config_entry.mode_text == u'sweep' and config_entry.profile_selection is None:
        raise ValueError(u'当前编辑区尚未选择封闭轮廓。')
    layout_result = build_layout_from_config_entry(config_entry)
    if not layout_result.valid:
        raise ValueError(layout_result.message)
    return layout_result


def build_layout_from_editor_state(state):
    current_entry = build_config_entry_from_state(state, config_id=state.selected_config_id or 0)
    return build_layout_from_config_entry(current_entry)


def build_layout_from_config_entry(config_entry):
    if config_entry.curve_selection is None:
        raise ValueError(u'请先选择曲线。')

    read_float_text(config_entry.horizontal_rotation_text, u'族水平旋转', allow_blank=True, default=0.0)
    read_float_text(config_entry.vertical_rotation_text, u'族垂直旋转', allow_blank=True, default=0.0)
    horizontal_offset_mm = read_float_text(config_entry.horizontal_offset_text, u'水平偏移', allow_blank=True, default=0.0)
    vertical_offset_mm = read_float_text(config_entry.vertical_offset_text, u'垂直偏移', allow_blank=True, default=0.0)

    if config_entry.mode_text == u'family':
        spacing_mm = read_float_text(config_entry.spacing_text, u'间距')
        count_value = read_int_text(config_entry.count_text, u'数量', allow_blank=True, default=0)
        if count_value is not None and count_value < 0:
            raise ValueError(u'数量不能小于 0。')
        return core.build_layout(
            config_entry.curve_selection.curve,
            core.mm_to_ft(spacing_mm),
            count_value or 0,
            core.mm_to_ft(horizontal_offset_mm or 0.0),
            core.mm_to_ft(vertical_offset_mm or 0.0),
        )

    frame = core.get_curve_frame(config_entry.curve_selection.curve, 0.0)
    target_point = frame['origin']
    if abs(core.mm_to_ft(horizontal_offset_mm or 0.0)) > core.GEOM_TOLERANCE:
        target_point = target_point.Add(frame['horizontal'].Multiply(core.mm_to_ft(horizontal_offset_mm or 0.0)))
    if abs(core.mm_to_ft(vertical_offset_mm or 0.0)) > core.GEOM_TOLERANCE:
        target_point = target_point.Add(frame['vertical'].Multiply(core.mm_to_ft(vertical_offset_mm or 0.0)))
    layout_result = core.LayoutResult()
    layout_result.curve_length_ft = core.get_curve_length(config_entry.curve_selection.curve)
    layout_result.resolved_count = 1
    layout_result.coverage_ft = layout_result.curve_length_ft
    layout_result.items.append(core.PlacementItem(
        1,
        0.0,
        frame['origin'],
        target_point,
        frame['tangent'],
        frame['horizontal'],
        frame['vertical'],
    ))
    layout_result.valid = True
    layout_result.message = u'放样预览已更新。'
    return layout_result


def find_config_entry(state, config_id):
    if config_id is None:
        return None
    for config_entry in state.config_entries:
        if config_entry.config_id == config_id:
            return config_entry
    return None


def replace_config_entry(state, updated_entry):
    for index, config_entry in enumerate(state.config_entries):
        if config_entry.config_id == updated_entry.config_id:
            state.config_entries[index] = updated_entry
            return


def build_config_entry_from_queue_task(state, task, config_id):
    task_type = task.get('type')
    prefix = task.get('prefix', u'-')
    if task_type == 'array':
        symbol_info = task.get('symbol_info')
        if symbol_info is None:
            raise ValueError(u'队列第 {0} 条（{1} 阵列）缺少族类型，请回到该专业重新选择族并重新加入队列。'.format(config_id, prefix))
        return ConfigEntry(
            config_id,
            u'family',
            state.curve_selection,
            symbol_info,
            None,
            task.get('spacing', u''),
            u'' if task.get('count') == u'自动' else task.get('count', u''),
            task.get('h_offset', u'0'),
            task.get('v_offset', u'0'),
            u'0' if task.get('h_rotation') == u'-' else task.get('h_rotation', u'0'),
            u'0' if task.get('v_rotation') == u'-' else task.get('v_rotation', u'0'),
        )

    if task_type == 'sweep':
        profile_selection = task.get('profile_selection')
        if profile_selection is None:
            raise ValueError(u'队列第 {0} 条（{1} 放样）缺少轮廓，请回到该专业重新选择轮廓并重新加入队列。'.format(config_id, prefix))
        return ConfigEntry(
            config_id,
            u'sweep',
            state.curve_selection,
            None,
            profile_selection,
            u'-',
            u'-',
            task.get('h_offset', u'0'),
            task.get('v_offset', u'0'),
            task.get('h_rotation', u'0'),
            task.get('v_rotation', u'0'),
        )

    raise ValueError(u'队列第 {0} 条任务类型无效: {1}'.format(config_id, unicode(task_type)))


def build_config_entries_from_task_queue(state, selected_only=False):
    queue = getattr(state, 'generation_queue', []) or []
    if not queue:
        return []
    if state.curve_selection is None:
        raise ValueError(u'请先在总控页选择路径线，再按队列生成。')

    if selected_only:
        queue_index = getattr(state, 'selected_queue_index', None)
        if queue_index is None or queue_index < 0 or queue_index >= len(queue):
            raise ValueError(u'请先在总控队列或右侧预览中选择一个任务，再执行单步生成。')
        return [build_config_entry_from_queue_task(state, queue[queue_index], queue_index + 1)]

    entries = []
    for index, task in enumerate(queue):
        entries.append(build_config_entry_from_queue_task(state, task, index + 1))
    return entries


def pick_curve():
    try:
        path_reference = revit.uidoc.Selection.PickObject(
            ObjectType.PointOnElement,
            PathReferenceSelectionFilter(),
            u'选择路径线、模型线、带 LocationCurve 的构件，或模型边。'
        )
        return core.get_curve_from_reference(revit.doc, path_reference)
    except OperationCanceledException:
        return None
    except Exception as ex:
        forms.alert(
            u'无法从当前选择中解析路径曲线。\n\n'
            u'可选择对象: 模型线、详图线、路径线、带 LocationCurve 的构件，或可解析为曲线的模型边。\n\n'
            u'错误信息: {0}'.format(unicode(ex)),
            exitscript=False
        )
        return None


def pick_family_instance_symbol():
    try:
        instance_reference = revit.uidoc.Selection.PickObject(
            ObjectType.Element,
            FamilyInstanceSelectionFilter(),
            u'选择一个已放置的族实例以复用其族类型。'
        )
        instance = revit.doc.GetElement(instance_reference.ElementId)
        return core.get_symbol_info_from_instance(instance)
    except OperationCanceledException:
        return None


def pick_profile():
    try:
        face_reference = revit.uidoc.Selection.PickObject(
            ObjectType.Face,
            u'优先选择一个任意封闭平面图形的面作为放样轮廓。若要改选边或曲线，请按 ESC。'
        )
        return core.get_profile_from_face_reference(revit.doc, face_reference)
    except OperationCanceledException:
        pass
    except Exception as ex:
        forms.alert(unicode(ex), exitscript=False)
        return None

    try:
        references = revit.uidoc.Selection.PickObjects(
            ObjectType.Edge,
            u'选择组成封闭轮廓的几何边，要求首尾闭合并共面。若要改选曲线元素，请按 ESC。'
        )
        if not references:
            return None
        return core.get_profile_from_references(revit.doc, references)
    except OperationCanceledException:
        pass
    except Exception as ex:
        forms.alert(unicode(ex), exitscript=False)
        return None

    try:
        references = revit.uidoc.Selection.PickObjects(
            ObjectType.Element,
            CurveElementSelectionFilter(),
            u'选择组成封闭轮廓的曲线元素，要求首尾闭合并共面。'
        )
        if not references:
            return None
        return core.get_profile_from_references(revit.doc, references)
    except OperationCanceledException:
        return None
    except Exception as ex:
        forms.alert(unicode(ex), exitscript=False)
        return None


def pick_symbol_info_with_winforms(current_symbol_info):
    symbol_infos = core.get_model_symbol_infos(revit.doc)
    if not symbol_infos:
        forms.alert(u'当前项目中没有可直接沿线布置的模型族类型。', exitscript=False)
        return None
    current_symbol_id = current_symbol_info.symbol_id if current_symbol_info is not None else None
    picker = FamilyTypePickerForm(symbol_infos, current_symbol_id=current_symbol_id)
    result = picker.ShowDialog()
    if result == Forms.DialogResult.OK:
        return picker.selected_info
    return None


def pick_profile_family_with_winforms(current_profile_selection):
    profile_symbol_infos = core.get_profile_family_symbol_infos(revit.doc)
    if not profile_symbol_infos:
        forms.alert(u'当前项目中没有找到可用的轮廓族类型。', exitscript=False)
        return None

    current_symbol_id = None
    if current_profile_selection is not None and current_profile_selection.source_element_ids:
        current_element = revit.doc.GetElement(current_profile_selection.source_element_ids[0])
        if isinstance(current_element, DB.FamilySymbol):
            current_symbol_id = current_element.Id.IntegerValue

    picker = ProfileFamilyTypePickerForm(profile_symbol_infos, current_symbol_id=current_symbol_id)
    result = picker.ShowDialog()
    if result == Forms.DialogResult.OK and picker.selected_info is not None:
        symbol = revit.doc.GetElement(ElementId(picker.selected_info.symbol_id))
        if symbol is None:
            forms.alert(u'选中的轮廓族类型已不存在。', exitscript=False)
            return None
        return core.get_profile_from_family_symbol(revit.doc, symbol)
    return None


class BuildProgressForm(Forms.Form):
    def __init__(self, total_steps):
        Forms.Form.__init__(self)
        self.Text = u'正在生成'
        self.Width = 580
        self.Height = 190
        self.FormBorderStyle = Forms.FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.StartPosition = Forms.FormStartPosition.CenterScreen
        self.TopMost = True

        self.lblStatus = Forms.Label()
        self.lblStatus.Text = u'准备中...'
        self.lblStatus.Location = Drawing.Point(18, 18)
        self.lblStatus.Size = Drawing.Size(530, 44)

        self.progressBar = Forms.ProgressBar()
        self.progressBar.Location = Drawing.Point(18, 74)
        self.progressBar.Size = Drawing.Size(530, 20)
        self.progressBar.Minimum = 0
        self.progressBar.Maximum = max(total_steps, 1)

        self.lblElapsed = Forms.Label()
        self.lblElapsed.Text = u'耗时: 0.0 s'
        self.lblElapsed.Location = Drawing.Point(18, 110)
        self.lblElapsed.Size = Drawing.Size(530, 24)

        self.lblFootnote = Forms.Label()
        self.lblFootnote.Text = u'进度按预计生成结果数量估算。'
        self.lblFootnote.Location = Drawing.Point(18, 136)
        self.lblFootnote.Size = Drawing.Size(530, 24)

        self.Controls.Add(self.lblStatus)
        self.Controls.Add(self.progressBar)
        self.Controls.Add(self.lblElapsed)
        self.Controls.Add(self.lblFootnote)

    def update_progress(self, value, status_text, elapsed_text):
        self.progressBar.Value = min(max(value, 0), self.progressBar.Maximum)
        self.lblStatus.Text = status_text
        self.lblElapsed.Text = elapsed_text
        Forms.Application.DoEvents()


class ProfileFamilyTypePickerForm(Forms.Form):
    def __init__(self, symbol_infos, current_symbol_id=None):
        Forms.Form.__init__(self)
        self.Text = u'选择轮廓族类型'
        self.Width = 720
        self.Height = 210
        self.FormBorderStyle = Forms.FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.StartPosition = Forms.FormStartPosition.CenterScreen
        self.TopMost = True

        self.selected_info = None
        self.family_groups = {}

        self.lblFamily = Forms.Label()
        self.lblFamily.Text = u'轮廓族'
        self.lblFamily.Location = Drawing.Point(18, 20)
        self.lblFamily.Size = Drawing.Size(90, 22)

        self.cmbFamily = Forms.ComboBox()
        self.cmbFamily.Location = Drawing.Point(18, 45)
        self.cmbFamily.Size = Drawing.Size(660, 24)
        self.cmbFamily.DropDownStyle = Forms.ComboBoxStyle.DropDownList
        self.cmbFamily.SelectedIndexChanged += self.on_family_changed

        self.lblType = Forms.Label()
        self.lblType.Text = u'类型'
        self.lblType.Location = Drawing.Point(18, 82)
        self.lblType.Size = Drawing.Size(90, 22)

        self.cmbType = Forms.ComboBox()
        self.cmbType.Location = Drawing.Point(18, 107)
        self.cmbType.Size = Drawing.Size(660, 24)
        self.cmbType.DropDownStyle = Forms.ComboBoxStyle.DropDownList

        self.btnOk = Forms.Button()
        self.btnOk.Text = u'确定'
        self.btnOk.Location = Drawing.Point(508, 145)
        self.btnOk.Size = Drawing.Size(80, 28)
        self.btnOk.Click += self.on_ok

        self.btnCancel = Forms.Button()
        self.btnCancel.Text = u'取消'
        self.btnCancel.Location = Drawing.Point(598, 145)
        self.btnCancel.Size = Drawing.Size(80, 28)
        self.btnCancel.Click += self.on_cancel

        self.Controls.Add(self.lblFamily)
        self.Controls.Add(self.cmbFamily)
        self.Controls.Add(self.lblType)
        self.Controls.Add(self.cmbType)
        self.Controls.Add(self.btnOk)
        self.Controls.Add(self.btnCancel)

        self._load_symbol_infos(symbol_infos, current_symbol_id=current_symbol_id)

    def _load_symbol_infos(self, symbol_infos, current_symbol_id=None):
        grouped = {}
        current_family_label = None
        current_type_label = None
        for info in symbol_infos:
            family_label = info.family_name
            if family_label not in grouped:
                grouped[family_label] = {}
            type_label = info.type_name
            if type_label in grouped[family_label]:
                type_label = u'{0} | Id {1}'.format(type_label, info.symbol_id)
            grouped[family_label][type_label] = info
            if current_symbol_id is not None and info.symbol_id == current_symbol_id:
                current_family_label = family_label
                current_type_label = type_label

        self.family_groups = grouped
        family_labels = sorted(grouped.keys())
        self.cmbFamily.Items.Clear()
        for family_label in family_labels:
            self.cmbFamily.Items.Add(family_label)

        if not family_labels:
            return

        if current_family_label in family_labels:
            self.cmbFamily.SelectedItem = current_family_label
            self._populate_type_combo(current_family_label, selected_type=current_type_label)
        else:
            self.cmbFamily.SelectedIndex = 0
            self._populate_type_combo(family_labels[0])

    def _populate_type_combo(self, family_label, selected_type=None):
        type_map = self.family_groups.get(family_label, {})
        type_labels = sorted(type_map.keys())
        self.cmbType.Items.Clear()
        for type_label in type_labels:
            self.cmbType.Items.Add(type_label)
        if not type_labels:
            return
        if selected_type in type_labels:
            self.cmbType.SelectedItem = selected_type
        else:
            self.cmbType.SelectedIndex = 0

    def on_family_changed(self, sender, args):
        family_label = self.cmbFamily.SelectedItem
        if family_label:
            self._populate_type_combo(family_label)

    def on_ok(self, sender, args):
        family_label = self.cmbFamily.SelectedItem
        type_label = self.cmbType.SelectedItem
        if not family_label or not type_label:
            Forms.MessageBox.Show(u'请先选择轮廓族和类型。', u'沿线放样')
            return
        self.selected_info = self.family_groups.get(family_label, {}).get(type_label)
        if self.selected_info is None:
            Forms.MessageBox.Show(u'未找到所选轮廓族类型。', u'沿线放样')
            return
        self.DialogResult = Forms.DialogResult.OK
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = Forms.DialogResult.Cancel
        self.Close()


class DeleteGeneratedForm(Forms.Form):
    def __init__(self, grouped_infos):
        Forms.Form.__init__(self)
        self.Text = u'删除程序生成结果'
        self.Width = 760
        self.Height = 540
        self.FormBorderStyle = Forms.FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.StartPosition = Forms.FormStartPosition.CenterScreen
        self.TopMost = True
        self.selected_keys = []

        self.lblHint = Forms.Label()
        self.lblHint.Text = u'按类别选择要删除的程序生成结果，可一次删除多个类别。'
        self.lblHint.Location = Drawing.Point(18, 16)
        self.lblHint.Size = Drawing.Size(706, 24)

        self.listBox = Forms.CheckedListBox()
        self.listBox.Location = Drawing.Point(18, 48)
        self.listBox.Size = Drawing.Size(706, 392)

        self.btnSelectAll = Forms.Button()
        self.btnSelectAll.Text = u'全选'
        self.btnSelectAll.Location = Drawing.Point(448, 454)
        self.btnSelectAll.Size = Drawing.Size(84, 30)
        self.btnSelectAll.Click += self.on_select_all

        self.btnClear = Forms.Button()
        self.btnClear.Text = u'清空'
        self.btnClear.Location = Drawing.Point(540, 454)
        self.btnClear.Size = Drawing.Size(84, 30)
        self.btnClear.Click += self.on_clear

        self.btnOk = Forms.Button()
        self.btnOk.Text = u'删除选中'
        self.btnOk.Location = Drawing.Point(632, 454)
        self.btnOk.Size = Drawing.Size(84, 30)
        self.btnOk.Click += self.on_ok

        self.btnCancel = Forms.Button()
        self.btnCancel.Text = u'取消'
        self.btnCancel.Location = Drawing.Point(632, 490)
        self.btnCancel.Size = Drawing.Size(84, 30)
        self.btnCancel.Click += self.on_cancel

        self.Controls.Add(self.lblHint)
        self.Controls.Add(self.listBox)
        self.Controls.Add(self.btnSelectAll)
        self.Controls.Add(self.btnClear)
        self.Controls.Add(self.btnOk)
        self.Controls.Add(self.btnCancel)

        for key in sorted(grouped_infos.keys()):
            info_list = grouped_infos[key]
            label = u'{0} | {1}'.format(key, build_mode_breakdown_text(info_list))
            self.listBox.Items.Add(label)

        self._grouped_keys = sorted(grouped_infos.keys())

    def on_select_all(self, sender, args):
        for index in range(self.listBox.Items.Count):
            self.listBox.SetItemChecked(index, True)

    def on_clear(self, sender, args):
        for index in range(self.listBox.Items.Count):
            self.listBox.SetItemChecked(index, False)

    def on_ok(self, sender, args):
        self.selected_keys = []
        for index in range(self.listBox.Items.Count):
            if self.listBox.GetItemChecked(index):
                self.selected_keys.append(self._grouped_keys[index])
        self.DialogResult = Forms.DialogResult.OK
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = Forms.DialogResult.Cancel
        self.Close()


def count_total_build_steps(config_entries):
    total_steps = 0
    for config_entry in config_entries:
        layout_result = build_layout_from_config_entry(config_entry)
        total_steps += max(len(layout_result.items), 1)
    return total_steps


def place_config_entries(state, config_entries):
    transaction = DB.Transaction(revit.doc, u'沿线布置族')
    total_created = 0
    total_failed = []
    total_steps = count_total_build_steps(config_entries)
    step_index = 0
    timer_start = time.time()
    progress_form = BuildProgressForm(total_steps)
    progress_form.Show()
    state.progress_value = 0
    state.progress_text = u'准备生成，共 {0} 个结果。'.format(total_steps)
    state.elapsed_text = u'耗时: 0.0 s'
    progress_form.update_progress(0, state.progress_text, state.elapsed_text)

    try:
        transaction.Start()
        for config_entry in config_entries:
            layout_result = build_layout_from_config_entry(config_entry)
            if not layout_result.valid:
                total_failed.append((config_entry.config_id, u'配置无效'))
                continue

            horizontal_rotation = read_float_text(config_entry.horizontal_rotation_text, u'族水平旋转', allow_blank=True, default=0.0)
            vertical_rotation = read_float_text(config_entry.vertical_rotation_text, u'族垂直旋转', allow_blank=True, default=0.0)
            horizontal_offset_ft = core.mm_to_ft(read_float_text(config_entry.horizontal_offset_text, u'水平偏移', allow_blank=True, default=0.0) or 0.0)
            vertical_offset_ft = core.mm_to_ft(read_float_text(config_entry.vertical_offset_text, u'垂直偏移', allow_blank=True, default=0.0) or 0.0)
            source_label = summarize_target(config_entry)

            if config_entry.mode_text == u'family':
                symbol = revit.doc.GetElement(ElementId(config_entry.symbol_info.symbol_id))
                if symbol is None:
                    total_failed.append((config_entry.config_id, u'族类型不存在'))
                    continue

                for item in layout_result.items:
                    sub_transaction = DB.SubTransaction(revit.doc)
                    try:
                        sub_transaction.Start()
                        element = core.place_symbol_instance(
                            revit.doc,
                            symbol,
                            revit.active_view,
                            item,
                            0.0,
                            horizontal_rotation,
                            vertical_rotation,
                        )
                        core.tag_generated_element(element, u'family', source_label, config_entry.config_id, time.time())
                        sub_transaction.Commit()
                        total_created += 1
                    except Exception as item_ex:
                        logger.error(u'配置 #{0} 第 {1} 个实例失败: {2}'.format(
                            config_entry.config_id,
                            item.index,
                            unicode(item_ex),
                        ))
                        if sub_transaction.HasStarted():
                            sub_transaction.RollBack()
                        total_failed.append((config_entry.config_id, u'实例 {0}'.format(item.index)))
                    finally:
                        step_index += 1
                        elapsed_text = u'耗时: {0}'.format(format_duration(time.time() - timer_start))
                        state.progress_value = int((float(step_index) / float(total_steps or 1)) * 100.0)
                        state.progress_text = build_progress_text(
                            step_index,
                            total_steps,
                            u'配置 #{0} | {1}'.format(config_entry.config_id, source_label),
                            timer_start,
                        )
                        state.elapsed_text = elapsed_text
                        progress_form.update_progress(step_index, state.progress_text, elapsed_text)
                continue

            sub_transaction = DB.SubTransaction(revit.doc)
            horizontal_rotation = read_float_text(config_entry.horizontal_rotation_text, u'族水平旋转', allow_blank=True, default=0.0)
            vertical_rotation = read_float_text(config_entry.vertical_rotation_text, u'族垂直旋转', allow_blank=True, default=0.0)
            try:
                sub_transaction.Start()
                element = core.create_swept_directshape(
                    revit.doc,
                    config_entry.curve_selection.curve,
                    config_entry.profile_selection,
                    horizontal_offset_ft=horizontal_offset_ft,
                    vertical_offset_ft=vertical_offset_ft,
                    horizontal_rotation_deg=horizontal_rotation,
                    vertical_rotation_deg=vertical_rotation,
                    source_label=source_label,
                )
                core.tag_generated_element(element, u'sweep', source_label, config_entry.config_id, time.time())
                sub_transaction.Commit()
                total_created += 1
            except Exception as item_ex:
                logger.error(u'配置 #{0} 放样失败: {1}'.format(config_entry.config_id, unicode(item_ex)))
                if sub_transaction.HasStarted():
                    sub_transaction.RollBack()
                total_failed.append((config_entry.config_id, u'放样'))
            finally:
                step_index += 1
                elapsed_text = u'耗时: {0}'.format(format_duration(time.time() - timer_start))
                state.progress_value = int((float(step_index) / float(total_steps or 1)) * 100.0)
                state.progress_text = build_progress_text(
                    step_index,
                    total_steps,
                    u'配置 #{0} | {1}'.format(config_entry.config_id, source_label),
                    timer_start,
                )
                state.elapsed_text = elapsed_text
                progress_form.update_progress(step_index, state.progress_text, elapsed_text)
        transaction.Commit()
    except Exception as ex:
        logger.error(traceback.format_exc())
        if transaction.HasStarted():
            transaction.RollBack()
        progress_form.Close()
        forms.alert(u'布置失败:\n{0}'.format(unicode(ex)), exitscript=False)
        return False
    finally:
        try:
            progress_form.Close()
        except Exception:
            pass

    if total_failed:
        elapsed_text = format_duration(time.time() - timer_start)
        state.status_text = u'批量生成完成，成功 {0} 个，失败 {1} 个，耗时 {2}。'.format(
            total_created,
            len(total_failed),
            elapsed_text,
        )
        state.status_is_error = True
        state.progress_value = 100
        state.progress_text = u'生成完成。'
        state.elapsed_text = u'耗时: {0}'.format(elapsed_text)
        forms.alert(
            u'批量生成完成，成功 {0} 个，失败 {1} 个，耗时 {2}。\n失败项: {3}'.format(
                total_created,
                len(total_failed),
                elapsed_text,
                u', '.join([u'配置#{0}-{1}'.format(x[0], x[1]) for x in total_failed[:20]]),
            ),
            exitscript=False
        )
        return True

    total_elapsed_text = format_duration(time.time() - timer_start)
    state.status_text = u'批量生成完成，已创建 {0} 个结果，耗时 {1}。'.format(total_created, total_elapsed_text)
    state.status_is_error = False
    state.progress_value = 100
    state.progress_text = u'生成完成。'
    state.elapsed_text = u'耗时: {0}'.format(total_elapsed_text)
    forms.alert(u'已成功创建 {0} 个结果。\n总耗时: {1}'.format(total_created, total_elapsed_text), exitscript=False)
    return True


def delete_generated_elements(state):
    infos = core.collect_generated_elements(revit.doc)
    if not infos:
        forms.alert(u'当前项目中没有找到本工具生成的结果。', exitscript=False)
        return False

    grouped = group_generated_infos_by_category(infos)

    dialog = DeleteGeneratedForm(grouped)
    result = dialog.ShowDialog()
    if result != Forms.DialogResult.OK or not dialog.selected_keys:
        return False

    delete_ids = []
    for key in dialog.selected_keys:
        for info in grouped.get(key, []):
            delete_ids.append(info.element.Id)

    if not delete_ids:
        return False

    transaction = DB.Transaction(revit.doc, u'删除程序生成结果')
    try:
        transaction.Start()
        revit.doc.Delete(List[ElementId](delete_ids))
        transaction.Commit()
    except Exception as ex:
        if transaction.HasStarted():
            transaction.RollBack()
        forms.alert(u'删除失败:\n{0}'.format(unicode(ex)), exitscript=False)
        return False

    state.status_text = u'已删除 {0} 个程序生成结果，涉及 {1} 个类别。'.format(
        len(delete_ids),
        len(dialog.selected_keys),
    )
    state.status_is_error = False
    forms.alert(
        u'已删除 {0} 个程序生成结果，涉及 {1} 个类别。'.format(
            len(delete_ids),
            len(dialog.selected_keys),
        ),
        exitscript=False
    )
    return True


def run_tool():
    state = ToolState()

    while True:
        state.requested_action = None
        window = AlongCurveWindow(state)
        window.ShowDialog()
        action = state.requested_action

        if action in [None, 'cancel']:
            return

        if action == 'pick_curve':
            curve_selection = pick_curve()
            if curve_selection is None:
                state.status_text = u'已取消选择曲线。'
                state.status_is_error = True
            else:
                state.curve_selection = curve_selection
                state.status_text = u'已选择曲线。'
                state.status_is_error = False
            continue

        if action == 'pick_family_type':
            symbol_info = pick_symbol_info_with_winforms(state.symbol_info)
            if symbol_info is None:
                state.status_text = u'已取消选择族类型。'
                state.status_is_error = True
            else:
                state.symbol_info = symbol_info
                state.selected_queue_index = None
                if getattr(state, 'active_prefix', None):
                    state.symbol_infos_by_prefix[state.active_prefix] = symbol_info
                    state.status_text = u'{} 已选择族类型: {} / {}。'.format(
                        state.active_prefix,
                        symbol_info.family_name,
                        symbol_info.type_name,
                    )
                else:
                    state.status_text = u'已选择族类型。'
                state.status_is_error = False
            continue

        if action == 'pick_placed_family':
            symbol_info = pick_family_instance_symbol()
            if symbol_info is None:
                state.status_text = u'已取消选择族实例。'
                state.status_is_error = True
            else:
                state.symbol_info = symbol_info
                state.selected_queue_index = None
                if getattr(state, 'active_prefix', None):
                    state.symbol_infos_by_prefix[state.active_prefix] = symbol_info
                    state.status_text = u'{0} 已从实例 {1} 复用族类型: {2} / {3}。'.format(
                        state.active_prefix,
                        symbol_info.source_instance_id,
                        symbol_info.family_name,
                        symbol_info.type_name,
                    )
                else:
                    state.status_text = u'已从实例 {0} 复用族类型。'.format(symbol_info.source_instance_id)
                state.status_is_error = False
            continue

        if action == 'pick_profile':
            profile_selection = pick_profile()
            if profile_selection is None:
                state.status_text = u'已取消选择封闭轮廓。'
                state.status_is_error = True
            else:
                state.profile_selection = profile_selection
                state.selected_queue_index = None
                if getattr(state, 'active_prefix', None):
                    state.profile_selections_by_prefix[state.active_prefix] = profile_selection
                    state.status_text = u'{} 已选择封闭轮廓。'.format(state.active_prefix)
                else:
                    state.status_text = u'已选择封闭轮廓。'
                state.status_is_error = False
            continue

        if action == 'pick_profile_family':
            profile_selection = pick_profile_family_with_winforms(state.profile_selection)
            if profile_selection is None:
                state.status_text = u'已取消选择轮廓族类型。'
                state.status_is_error = True
            else:
                state.profile_selection = profile_selection
                state.selected_queue_index = None
                if getattr(state, 'active_prefix', None):
                    state.profile_selections_by_prefix[state.active_prefix] = profile_selection
                    state.status_text = u'{} 已选择轮廓族类型。'.format(state.active_prefix)
                else:
                    state.status_text = u'已选择轮廓族类型。'
                state.status_is_error = False
            continue

        if action == 'delete_generated':
            delete_generated_elements(state)
            continue

        if action == 'generate_spline':
            try:
                from pyrevit import revit
                doc = revit.doc
                transaction = DB.Transaction(doc, u'生成线路中心线')
                transaction.Start()
                try:
                    spline = alignment.create_alignment_spline(doc, state.alignment_points)
                    ds = alignment.create_alignment_directshape(doc, spline, name=u"LinerMaster_线路中心线")
                    transaction.Commit()
                    forms.alert(u'成功生成线路中心线 DirectShape，ID: {0}'.format(ds.Id), exitscript=False)
                    state.status_text = u'已生成线路中心线。'
                    state.status_is_error = False
                except Exception as ex:
                    transaction.RollBack()
                    raise ex
            except Exception as e:
                forms.alert(u'生成失败: {0}'.format(unicode(e)), exitscript=False)
                state.status_text = u'生成线路中心线失败。'
                state.status_is_error = True
            continue

        if action == 'place':
            try:
                queue_entries = build_config_entries_from_task_queue(state)
                place_entries = queue_entries if queue_entries else (state.config_entries[:] if state.config_entries else [build_config_entry_from_state(state)])
                for place_entry in place_entries:
                    validate_config_entry(place_entry)
                place_config_entries(state, place_entries)
            except Exception as ex:
                forms.alert(unicode(ex), exitscript=False)
            continue

        if action == 'step_place':
            try:
                queue_entries = build_config_entries_from_task_queue(state, selected_only=True)
                place_entries = queue_entries if queue_entries else [build_config_entry_from_state(state)]
                for place_entry in place_entries:
                    validate_config_entry(place_entry)
                place_config_entries(state, place_entries)
            except Exception as ex:
                forms.alert(unicode(ex), exitscript=False)
            continue


run_tool()
