# -*- coding: utf-8 -*-
import datetime
import os
import clr

clr.AddReference('RevitAPI')
clr.AddReference('System.Windows.Forms')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import BuiltInCategory, ElementId, FilteredElementCollector, StorageType, Transaction, ViewSchedule, ViewSheet
from pyrevit import forms, revit, script
from System import Activator, EventHandler, Type
from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
from System.Windows.Controls import DataGridEditingUnit
from System.Windows.Media import Color, SolidColorBrush
from System.Runtime.InteropServices import Marshal
from System.Windows.Forms import DialogResult, OpenFileDialog, SaveFileDialog

try:
    unicode
except NameError:
    unicode = str


doc = revit.doc
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
XAML_FILE = os.path.join(SCRIPT_DIR, 'ui.xaml')
LOGGER = script.get_logger()

LIGHT_THEME = {'WindowBg': '#F5F7FA', 'Surface': '#FFFFFF', 'SurfaceAlt': '#F8FAFC', 'Text': '#1F2937', 'MutedText': '#64748B', 'Border': '#D7E0EA', 'Primary': '#1D4ED8'}
DARK_THEME = {'WindowBg': '#0F172A', 'Surface': '#111827', 'SurfaceAlt': '#1F2937', 'Text': '#E5E7EB', 'MutedText': '#94A3B8', 'Border': '#334155', 'Primary': '#60A5FA'}


def text(value):
    if value is None:
        return u''
    if isinstance(value, unicode):
        return value
    try:
        return unicode(value)
    except Exception:
        return unicode(str(value))


def blank(value):
    return not text(value).strip()


def brush(value):
    value = value.strip().lstrip('#')
    result = SolidColorBrush(Color.FromRgb(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)))
    result.Freeze()
    return result


def is_dark_theme():
    ctx = globals().get('__omnimetro__')
    return isinstance(ctx, dict) and (bool(ctx.get('is_dark')) or ctx.get('theme') == u'深色')


def collect_sheets():
    sheets = list(FilteredElementCollector(doc).OfClass(ViewSheet).WhereElementIsNotElementType())
    return sorted(sheets, key=lambda x: (text(x.SheetNumber).lower(), text(x.Name).lower()))


def parameter_value(parameter):
    if parameter.StorageType == StorageType.String:
        return text(parameter.AsString())
    try:
        value = parameter.AsValueString()
        if value is not None:
            return text(value)
    except Exception:
        pass
    if parameter.StorageType == StorageType.Integer:
        return text(parameter.AsInteger())
    if parameter.StorageType == StorageType.Double:
        return text(parameter.AsDouble())
    return text(parameter.AsElementId().IntegerValue)


def set_parameter_value(parameter, value):
    if parameter is None:
        raise ValueError(u'未找到指定的图纸实例参数。')
    if parameter.IsReadOnly:
        raise ValueError(u'参数“{}”为只读参数，Revit 不允许写入。'.format(text(parameter.Definition.Name)))
    if parameter.StorageType == StorageType.String:
        if not parameter.Set(value):
            raise ValueError(u'参数“{}”拒绝了字符串值“{}”。'.format(text(parameter.Definition.Name), value))
        return
    if parameter.StorageType == StorageType.ElementId:
        raise ValueError(u'参数“{}”是元素引用类型，不能用文字批量填写。'.format(text(parameter.Definition.Name)))
    if not parameter.SetValueString(value):
        raise ValueError(u'参数“{}”无法接受值“{}”，请按 Revit 显示格式填写。'.format(text(parameter.Definition.Name), value))


def release_com_object(obj):
    if obj is None:
        return
    try:
        Marshal.FinalReleaseComObject(obj)
    except Exception:
        try:
            Marshal.ReleaseComObject(obj)
        except Exception:
            pass


def excel_app():
    excel_type = Type.GetTypeFromProgID('Excel.Application')
    if excel_type is None:
        raise RuntimeError(u'当前系统没有注册 Excel.Application COM 组件，无法读写 xlsx。请安装桌面版 Excel。')
    try:
        return Activator.CreateInstance(excel_type)
    except Exception as ex:
        raise RuntimeError(u'创建 Excel.Application 失败：{}'.format(text(ex)))


def open_excel_file_dialog(title, save=False, default_filename=None):
    dialog = SaveFileDialog() if save else OpenFileDialog()
    dialog.Title = title
    dialog.Filter = u'Excel 工作簿 (*.xlsx)|*.xlsx|所有文件 (*.*)|*.*'
    if save:
        dialog.DefaultExt = 'xlsx'
        dialog.AddExtension = True
        dialog.OverwritePrompt = True
        if default_filename:
            dialog.FileName = default_filename
    if dialog.ShowDialog() == DialogResult.OK:
        return text(dialog.FileName)
    return None


def normalize_header(value):
    return text(value).strip().replace(u'（', u'(').replace(u'）', u')').lower()


def excel_cell_text(sheet, row, column):
    try:
        value = sheet.Cells(row, column).Value2
    except Exception:
        value = None
    return text(value).strip()


def excel_element_id_text(sheet, row, column):
    value = excel_cell_text(sheet, row, column)
    if value.endswith(u'.0') and value[:-2].isdigit():
        return value[:-2]
    return value


class SheetRow(INotifyPropertyChanged):
    def __init__(self, sheet, target_number, target_name, parameter_name=u'', parameter_source=u'', parameter_target=u'', error=u''):
        self.ElementIdValue = sheet.Id.IntegerValue
        self.OriginalSheetNumber = text(sheet.SheetNumber)
        self.OriginalSheetName = text(sheet.Name)
        self._sheet_number = target_number
        self._sheet_name = target_name
        self.ParameterName = parameter_name
        self.ParameterSource = parameter_source
        self.ParameterTarget = parameter_target
        self.Status = u'失败' if error else u'待确认'
        self.Message = error or u'可直接编辑编号、名称；确认后执行。'
        self._pc = None

    def add_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Combine(self._pc, value)

    def remove_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Remove(self._pc, value)

    def _changed(self, name):
        if self._pc is not None:
            self._pc(self, PropertyChangedEventArgs(name))

    @property
    def SheetNumber(self):
        return self._sheet_number

    @SheetNumber.setter
    def SheetNumber(self, value):
        self._sheet_number = text(value)
        self._changed('SheetNumber')

    @property
    def SheetName(self):
        return self._sheet_name

    @SheetName.setter
    def SheetName(self, value):
        self._sheet_name = text(value)
        self._changed('SheetName')

    @property
    def HasNumberChange(self):
        return self.SheetNumber != self.OriginalSheetNumber

    @property
    def HasNameChange(self):
        return self.SheetName != self.OriginalSheetName

    @property
    def HasParameterChange(self):
        return bool(self.ParameterName) and self.ParameterTarget != self.ParameterSource

    def update(self, status, message):
        self.Status = status
        self.Message = message
        self._changed('Status')
        self._changed('Message')

    def apply_excel_values(self, sheet_number, sheet_name, parameter_target):
        self.SheetNumber = sheet_number
        self.SheetName = sheet_name
        self.ParameterTarget = text(parameter_target)
        self.Status = u'待确认'
        self.Message = u'已从 Excel 导入，需重新确认后执行。'
        self._changed('ParameterTarget')
        self._changed('Status')
        self._changed('Message')


class SourceSheetRow(object):
    def __init__(self, sheet):
        self.ElementIdValue = sheet.Id.IntegerValue
        self.DisplayName = u'{} | {}'.format(text(sheet.SheetNumber), text(sheet.Name))


class SheetParameterRow(INotifyPropertyChanged):
    def __init__(self, parameter):
        self.ParameterIdValue = parameter.Id.IntegerValue
        self.Name = text(parameter.Definition.Name)
        self.Value = parameter_value(parameter)
        self.StorageTypeName = text(parameter.StorageType)
        self.IsWritable = not parameter.IsReadOnly
        self._selected = False
        self._pc = None

    def add_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Combine(self._pc, value)

    def remove_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Remove(self._pc, value)

    def _changed(self, name):
        if self._pc is not None:
            self._pc(self, PropertyChangedEventArgs(name))

    @property
    def Selected(self):
        return self._selected

    @Selected.setter
    def Selected(self, value):
        self._selected = bool(value)
        self._changed('Selected')


class CopyTargetRow(INotifyPropertyChanged):
    def __init__(self, sheet):
        self.ElementIdValue = sheet.Id.IntegerValue
        self.SheetNumber = text(sheet.SheetNumber)
        self.SheetName = text(sheet.Name)
        self._selected = False
        self.Status = u'未选择'
        self.Message = u'勾选后可接收所选源属性。'
        self._pc = None

    def add_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Combine(self._pc, value)

    def remove_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Remove(self._pc, value)

    def _changed(self, name):
        if self._pc is not None:
            self._pc(self, PropertyChangedEventArgs(name))

    @property
    def Selected(self):
        return self._selected

    @Selected.setter
    def Selected(self, value):
        self._selected = bool(value)
        self._changed('Selected')

    def update(self, status, message):
        self.Status = status
        self.Message = message
        self._changed('Status')
        self._changed('Message')


class SheetManager(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, XAML_FILE)
        palette = DARK_THEME if is_dark_theme() else LIGHT_THEME
        for key, value in palette.items():
            self.Resources[key + 'Brush'] = brush(value)
        self.Background = self.Resources['WindowBgBrush']
        self.rows = ObservableCollection[SheetRow]()
        self.source_sheets = ObservableCollection[SourceSheetRow]()
        self.parameter_rows = ObservableCollection[SheetParameterRow]()
        self.copy_targets = ObservableCollection[CopyTargetRow]()
        self.PreviewDataGrid.ItemsSource = self.rows
        self.SourceSheetComboBox.ItemsSource = self.source_sheets
        self.SourceSheetComboBox.DisplayMemberPath = 'DisplayName'
        self.PropertyDataGrid.ItemsSource = self.parameter_rows
        self.CopyTargetDataGrid.ItemsSource = self.copy_targets
        for sheet in collect_sheets():
            self.source_sheets.Add(SourceSheetRow(sheet))
            self.copy_targets.Add(CopyTargetRow(sheet))
        self.logs = []
        self._log(u'可不勾选任何规则，直接点击“生成预览”查看并逐行修改全部图纸。')
        self._log(u'属性复制：选择源图纸，加载属性后勾选属性和目标图纸，再执行复制。')

    def _log(self, message):
        self.logs.append(text(message))
        self.LogTextBox.Text = u'\n'.join(self.logs)
        try:
            self.LogTextBox.ScrollToEnd()
        except Exception:
            pass

    def _summary(self, message):
        self.SummaryTextBlock.Text = text(message)

    def _export_headers(self):
        return [
            u'ElementId',
            u'原图纸编号',
            u'原图纸名称',
            u'目标图纸编号',
            u'目标图纸名称',
            u'属性名称',
            u'属性原值',
            u'属性目标值',
            u'状态',
            u'说明',
        ]

    def _export_row_values(self, row):
        return [
            row.ElementIdValue,
            row.OriginalSheetNumber,
            row.OriginalSheetName,
            row.SheetNumber,
            row.SheetName,
            row.ParameterName,
            row.ParameterSource,
            row.ParameterTarget,
            row.Status,
            row.Message,
        ]

    def _export_rows_to_excel(self, path):
        excel = workbook = sheet = None
        try:
            excel = excel_app()
            excel.Visible = False
            excel.DisplayAlerts = False
            workbook = excel.Workbooks.Add()
            sheet = workbook.Worksheets(1)
            sheet.Name = u'图纸预览'
            sheet.Cells.NumberFormat = '@'
            headers = self._export_headers()
            for col_index, header in enumerate(headers, 1):
                sheet.Cells(1, col_index).Value2 = header
            for row_index, row in enumerate(self.rows, 2):
                values = self._export_row_values(row)
                for col_index, value in enumerate(values, 1):
                    sheet.Cells(row_index, col_index).Value2 = text(value)
            used = sheet.UsedRange
            used.NumberFormat = '@'
            sheet.Range(sheet.Cells(1, 1), sheet.Cells(1, len(headers))).Font.Bold = True
            used.EntireColumn.AutoFit()
            if os.path.exists(path):
                os.remove(path)
            workbook.SaveAs(path)
            workbook.Close(False)
            excel.Quit()
        except Exception as ex:
            raise RuntimeError(u'导出 Excel 失败：{}'.format(text(ex)))
        finally:
            release_com_object(sheet)
            release_com_object(workbook)
            release_com_object(excel)

    def _import_rows_from_excel(self, path):
        excel = workbook = sheet = None
        try:
            excel = excel_app()
            excel.Visible = False
            excel.DisplayAlerts = False
            workbook = excel.Workbooks.Open(path)
            try:
                sheet = workbook.Worksheets(u'图纸预览')
            except Exception:
                sheet = workbook.Worksheets(1)
            used = sheet.UsedRange
            row_count = int(used.Rows.Count)
            column_count = int(used.Columns.Count)
            if row_count < 2:
                raise ValueError(u'Excel 表格没有数据行，至少需要 1 行表头和 1 行数据。')
            headers = {}
            for col_index in range(1, column_count + 1):
                header = normalize_header(excel_cell_text(sheet, 1, col_index))
                if header:
                    headers[header] = col_index
            required = {
                u'elementid': u'ElementId',
                u'目标图纸编号': u'目标图纸编号',
                u'目标图纸名称': u'目标图纸名称',
                u'属性目标值': u'属性目标值',
            }
            missing = [label for key, label in required.items() if key not in headers]
            if missing:
                raise ValueError(u'Excel 缺少必要列：{}。'.format(u'、'.join(missing)))
            row_map = dict((str(row.ElementIdValue), row) for row in self.rows)
            seen_ids = set()
            updated = 0
            errors = []
            for row_index in range(2, row_count + 1):
                element_id_text = excel_element_id_text(sheet, row_index, headers[u'elementid'])
                if blank(element_id_text):
                    continue
                if element_id_text in seen_ids:
                    errors.append(u'第 {} 行 ElementId 重复：{}。'.format(row_index, element_id_text))
                    continue
                seen_ids.add(element_id_text)
                row = row_map.get(element_id_text)
                if row is None:
                    errors.append(u'第 {} 行找不到对应的预览记录，ElementId：{}。'.format(row_index, element_id_text))
                    continue
                row.apply_excel_values(
                    excel_cell_text(sheet, row_index, headers[u'目标图纸编号']),
                    excel_cell_text(sheet, row_index, headers[u'目标图纸名称']),
                    excel_cell_text(sheet, row_index, headers[u'属性目标值']),
                )
                updated += 1
            missing_ids = [row.ElementIdValue for row in self.rows if str(row.ElementIdValue) not in seen_ids]
            if missing_ids:
                errors.append(u'Excel 缺少 {} 张当前预览中的图纸记录，例如 ElementId：{}。'.format(len(missing_ids), missing_ids[0]))
            if errors:
                raise ValueError(u'；'.join(errors))
            return updated
        except Exception as ex:
            raise RuntimeError(u'导入 Excel 失败：{}'.format(text(ex)))
        finally:
            try:
                if workbook is not None:
                    workbook.Close(False)
                if excel is not None:
                    excel.Quit()
            except Exception:
                pass
            release_com_object(sheet)
            release_com_object(workbook)
            release_com_object(excel)

    def _request(self):
        return {
            'number_filter': text(self.NumberFilterTextBox.Text), 'name_filter': text(self.NameFilterTextBox.Text),
            'change_name': bool(self.ChangeNameCheckBox.IsChecked), 'name_mode': self.NameModeComboBox.SelectedIndex,
            'name_find': text(self.NameFindTextBox.Text), 'name_value': text(self.NameValueTextBox.Text),
            'change_number': bool(self.ChangeNumberCheckBox.IsChecked), 'number_mode': self.NumberModeComboBox.SelectedIndex,
            'number_find': text(self.NumberFindTextBox.Text), 'number_value': text(self.NumberValueTextBox.Text),
            'change_parameter': bool(self.ChangeParameterCheckBox.IsChecked), 'parameter_name': text(self.ParameterNameTextBox.Text),
            'parameter_mode': self.ParameterModeComboBox.SelectedIndex, 'parameter_find': text(self.ParameterFindTextBox.Text),
            'parameter_value': text(self.ParameterValueTextBox.Text),
        }

    def _validate(self, req):
        errors = []
        for prefix, label in [('name', u'图纸名称'), ('number', u'图纸编号'), ('parameter', u'图纸属性')]:
            if req['change_' + prefix] and req[prefix + '_mode'] == 0 and blank(req[prefix + '_find']):
                errors.append(u'{}的“查找内容”不能为空。'.format(label))
        if req['change_parameter'] and blank(req['parameter_name']):
            errors.append(u'图纸属性的“参数名称”不能为空。')
        if req['change_name'] and req['name_mode'] == 1 and blank(req['name_value']):
            errors.append(u'图纸名称不能整体填写为空。')
        if req['change_number'] and req['number_mode'] == 1 and blank(req['number_value']):
            errors.append(u'图纸编号不能整体填写为空。')
        return errors

    def _target(self, source, mode, find, value):
        return source.replace(find, value) if mode == 0 else value

    def _selected_sheets(self, req):
        result = []
        for sheet in collect_sheets():
            if req['number_filter'] and req['number_filter'] not in text(sheet.SheetNumber):
                continue
            if req['name_filter'] and req['name_filter'] not in text(sheet.Name):
                continue
            result.append(sheet)
        return result

    def _category_name(self, schedule):
        try:
            category_id = schedule.Definition.CategoryId
            if category_id is None or category_id == ElementId.InvalidElementId:
                return u'无单一类别'
            category = doc.Settings.Categories.get_Item(category_id)
            return text(category.Name) if category is not None else u'类别 Id {}'.format(category_id.IntegerValue)
        except Exception as ex:
            return u'类别读取失败：{}'.format(text(ex))

    def RefreshDrawingList_Click(self, sender, e):
        keyword = text(self.DrawingListKeywordTextBox.Text).strip()
        if blank(keyword):
            forms.alert(u'请输入 Drawing List 明细表名称中的关键字。', title=u'无法更新')
            return
        matches = []
        for schedule in FilteredElementCollector(doc).OfClass(ViewSchedule):
            try:
                if schedule.IsTemplate or keyword.lower() not in text(schedule.Name).lower():
                    continue
                matches.append(schedule)
            except Exception as ex:
                self._log(u'读取一个明细表时失败：{}'.format(text(ex)))
        if not matches:
            message = u'未找到名称包含“{}”的明细表。请检查名称关键字。'.format(keyword)
            self._log(message)
            forms.alert(message, title=u'未找到 Drawing List')
            return
        sheet_category_id = int(BuiltInCategory.OST_Sheets)
        sheet_schedules = []
        other_schedules = []
        for schedule in matches:
            try:
                if schedule.Definition.CategoryId.IntegerValue == sheet_category_id:
                    sheet_schedules.append(schedule)
                else:
                    other_schedules.append(schedule)
            except Exception as ex:
                other_schedules.append(schedule)
                self._log(u'无法判断明细表“{}”的数据类别：{}'.format(text(schedule.Name), text(ex)))
        if sheet_schedules:
            tx = Transaction(doc, u'更新 Drawing List')
            tx_started = False
            try:
                tx.Start()
                tx_started = True
                doc.Regenerate()
                tx.Commit()
            except Exception as ex:
                if tx_started:
                    tx.RollBack()
                message = u'Drawing List 刷新失败：{}'.format(text(ex))
                self._log(message)
                forms.alert(message, title=u'刷新失败')
                return
        lines = []
        if sheet_schedules:
            lines.append(u'已刷新 {} 个图纸明细表：{}。它们现在会按最新图纸编号、图纸名称和自身筛选规则显示。'.format(
                len(sheet_schedules), u'、'.join([text(x.Name) for x in sheet_schedules])
            ))
        if other_schedules:
            details = [u'{}（{}）'.format(text(x.Name), self._category_name(x)) for x in other_schedules]
            lines.append(u'以下匹配项不是图纸明细表，不能依据图纸信息自动更新行数据：{}。'.format(u'、'.join(details)))
        message = u'\n'.join(lines)
        self._log(message)
        forms.alert(message, title=u'Drawing List 更新结果')

    def ExportExcel_Click(self, sender, e):
        if self.rows.Count == 0:
            forms.alert(u'请先点击“生成预览”加载图纸清单后再导出。', title=u'无法导出')
            return
        default_name = u'批量图纸管理_{}.xlsx'.format(datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
        path = open_excel_file_dialog(u'导出 Excel', save=True, default_filename=default_name)
        if blank(path):
            return
        if not path.lower().endswith(u'.xlsx'):
            path += u'.xlsx'
        try:
            self._export_rows_to_excel(path)
        except Exception as ex:
            message = text(ex)
            self._log(message)
            forms.alert(message, title=u'导出失败')
            return
        message = u'已导出 Excel：{}'.format(path)
        self._log(message)
        self._summary(message)
        forms.alert(message, title=u'导出完成')

    def ImportExcel_Click(self, sender, e):
        if self.rows.Count == 0:
            forms.alert(u'请先点击“生成预览”加载图纸清单后再导入。', title=u'无法导入')
            return
        path = open_excel_file_dialog(u'导入 Excel', save=False)
        if blank(path):
            return
        try:
            updated = self._import_rows_from_excel(path)
        except Exception as ex:
            message = text(ex)
            self._log(message)
            forms.alert(message, title=u'导入失败')
            return
        summary = u'已从 Excel 导入 {} 张图纸的编辑值，可继续执行修改。'.format(updated)
        self._summary(summary)
        self._log(summary)
        forms.alert(summary, title=u'导入完成')

    def LoadSourceProperties_Click(self, sender, e):
        source = self.SourceSheetComboBox.SelectedItem
        if source is None:
            forms.alert(u'请先选择一张源图纸。', title=u'无法加载属性')
            return
        sheet = doc.GetElement(ElementId(source.ElementIdValue))
        if sheet is None:
            message = u'所选源图纸已不存在，请重新打开此工具。'
            self._log(message)
            forms.alert(message, title=u'无法加载属性')
            return
        self.parameter_rows.Clear()
        errors = []
        for parameter in sheet.Parameters:
            try:
                self.parameter_rows.Add(SheetParameterRow(parameter))
            except Exception as ex:
                errors.append(text(ex))
        summary = u'已从图纸“{}”加载 {} 个属性；可勾选一个或多个属性进行复制。'.format(source.DisplayName, self.parameter_rows.Count)
        self._summary(summary)
        self._log(summary)
        if errors:
            self._log(u'有 {} 个属性无法显示：{}。'.format(len(errors), u'；'.join(errors[:3])))

    def SelectAllProperties_Click(self, sender, e):
        for row in self.parameter_rows:
            row.Selected = True

    def ClearProperties_Click(self, sender, e):
        for row in self.parameter_rows:
            row.Selected = False

    def SelectAllTargets_Click(self, sender, e):
        source = self.SourceSheetComboBox.SelectedItem
        source_id = source.ElementIdValue if source is not None else None
        for row in self.copy_targets:
            row.Selected = row.ElementIdValue != source_id

    def ClearTargets_Click(self, sender, e):
        for row in self.copy_targets:
            row.Selected = False

    def _find_same_parameter(self, sheet, property_row):
        """Avoid IronPython selecting Element.get_Parameter(Guid) for an ElementId."""
        candidates = list(sheet.GetParameters(property_row.Name))
        for parameter in candidates:
            if parameter.Id.IntegerValue == property_row.ParameterIdValue:
                return parameter
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _copy_parameter_value(self, source_parameter, target_parameter):
        if target_parameter is None:
            raise ValueError(u'目标图纸不存在同一属性。')
        if target_parameter.IsReadOnly:
            raise ValueError(u'目标属性“{}”为只读。'.format(text(target_parameter.Definition.Name)))
        if source_parameter.StorageType != target_parameter.StorageType:
            raise ValueError(u'源属性类型为 {}，目标属性类型为 {}，不能复制。'.format(text(source_parameter.StorageType), text(target_parameter.StorageType)))
        if source_parameter.StorageType == StorageType.String:
            value = source_parameter.AsString()
            if not target_parameter.Set(value or u''):
                raise ValueError(u'Revit 拒绝写入字符串值。')
        elif source_parameter.StorageType == StorageType.Integer:
            if not target_parameter.Set(source_parameter.AsInteger()):
                raise ValueError(u'Revit 拒绝写入整数值。')
        elif source_parameter.StorageType == StorageType.Double:
            if not target_parameter.Set(source_parameter.AsDouble()):
                raise ValueError(u'Revit 拒绝写入数值。')
        elif source_parameter.StorageType == StorageType.ElementId:
            if not target_parameter.Set(source_parameter.AsElementId()):
                raise ValueError(u'Revit 拒绝写入元素引用值。')
        else:
            raise ValueError(u'不支持的参数存储类型：{}。'.format(text(source_parameter.StorageType)))

    def CopyProperties_Click(self, sender, e):
        source = self.SourceSheetComboBox.SelectedItem
        if source is None:
            forms.alert(u'请先选择源图纸并加载属性。', title=u'无法复制')
            return
        selected_properties = [row for row in self.parameter_rows if row.Selected]
        selected_targets = [row for row in self.copy_targets if row.Selected]
        if not selected_properties:
            forms.alert(u'请至少勾选一个要复制的属性。', title=u'无法复制')
            return
        if not selected_targets:
            forms.alert(u'请至少勾选一张目标图纸。', title=u'无法复制')
            return
        source_sheet = doc.GetElement(ElementId(source.ElementIdValue))
        if source_sheet is None:
            forms.alert(u'源图纸已不存在，请重新选择。', title=u'无法复制')
            return
        if any(row.ElementIdValue == source.ElementIdValue for row in selected_targets):
            forms.alert(u'源图纸不能同时作为目标图纸，请取消勾选源图纸。', title=u'无法复制')
            return
        tx = Transaction(doc, u'复制图纸属性')
        tx_started = False
        succeeded = 0
        failed = 0
        try:
            tx.Start()
            tx_started = True
            for target_row in selected_targets:
                target_sheet = doc.GetElement(ElementId(target_row.ElementIdValue))
                if target_sheet is None:
                    target_row.update(u'失败', u'目标图纸已不存在。')
                    failed += 1
                    continue
                row_errors = []
                row_success = 0
                for property_row in selected_properties:
                    try:
                        source_parameter = self._find_same_parameter(source_sheet, property_row)
                        if source_parameter is None:
                            raise ValueError(u'源图纸未找到属性“{}”（参数 Id：{}）。'.format(property_row.Name, property_row.ParameterIdValue))
                        target_parameter = self._find_same_parameter(target_sheet, property_row)
                        self._copy_parameter_value(source_parameter, target_parameter)
                        row_success += 1
                    except Exception as ex:
                        row_errors.append(u'{}：{}'.format(property_row.Name, text(ex)))
                if row_errors:
                    failed += 1
                    target_row.update(u'部分失败' if row_success else u'失败', u'；'.join(row_errors))
                else:
                    succeeded += 1
                    target_row.update(u'成功', u'已复制 {} 个属性。'.format(row_success))
            tx.Commit()
        except Exception as ex:
            if tx_started:
                tx.RollBack()
            message = u'属性复制事务失败，所有本次写入均已回滚：{}'.format(text(ex))
            self._log(message)
            LOGGER.error(message)
            forms.alert(message, title=u'复制失败')
            return
        summary = u'属性复制完成：成功 {0} 张，存在失败或跳过 {1} 张。'.format(succeeded, failed)
        self._summary(summary)
        self._log(summary)
        forms.alert(summary, title=u'图纸属性复制')

    def Preview_Click(self, sender, e):
        req = self._request()
        errors = self._validate(req)
        if errors:
            message = u'\n'.join(errors)
            self._log(message)
            forms.alert(message, title=u'输入不完整')
            return
        self.rows.Clear()
        sheets = self._selected_sheets(req)
        for sheet in sheets:
            source_name = text(sheet.Name)
            source_number = text(sheet.SheetNumber)
            target_name = self._target(source_name, req['name_mode'], req['name_find'], req['name_value']) if req['change_name'] else source_name
            target_number = self._target(source_number, req['number_mode'], req['number_find'], req['number_value']) if req['change_number'] else source_number
            param_name = u''
            param_source = u''
            param_target = u''
            error = u''
            if req['change_parameter']:
                param_name = req['parameter_name']
                parameter = sheet.LookupParameter(param_name)
                if parameter is None:
                    error = u'未找到实例参数“{}”。请确认名称与 Revit 显示名称完全一致。'.format(param_name)
                elif parameter.IsReadOnly:
                    error = u'参数“{}”为只读，无法写入。'.format(param_name)
                else:
                    param_source = parameter_value(parameter)
                    param_target = self._target(param_source, req['parameter_mode'], req['parameter_find'], req['parameter_value'])
            self.rows.Add(SheetRow(sheet, target_number, target_name, param_name, param_source, param_target, error))
        changed = len([x for x in self.rows if x.HasNumberChange or x.HasNameChange or x.HasParameterChange])
        summary = u'已加载 {0} 张图纸，其中 {1} 张存在批量规则预填的修改。可直接在表格中逐行编辑编号和名称。'.format(self.rows.Count, changed)
        self._summary(summary)
        self._log(summary)
        if not sheets:
            forms.alert(u'按当前筛选条件未找到图纸。请检查筛选关键字。', title=u'预览结果')

    def _commit_grid_edit(self):
        try:
            self.PreviewDataGrid.CommitEdit(DataGridEditingUnit.Cell, True)
            self.PreviewDataGrid.CommitEdit(DataGridEditingUnit.Row, True)
        except Exception as ex:
            raise ValueError(u'表格编辑值无法提交：{}'.format(text(ex)))

    def _validate_rows(self):
        errors = []
        rows = list(self.rows)
        selected_ids = set(row.ElementIdValue for row in rows)
        existing_numbers = dict((text(sheet.SheetNumber), sheet.Id.IntegerValue) for sheet in collect_sheets())
        targets = {}
        for row in rows:
            if blank(row.SheetNumber):
                errors.append(u'图纸“{}”的编号不能为空。'.format(row.OriginalSheetName))
            if blank(row.SheetName):
                errors.append(u'图纸编号“{}”的名称不能为空。'.format(row.OriginalSheetNumber))
            if row.SheetNumber in targets:
                errors.append(u'图纸编号“{}”在表格中重复。'.format(row.SheetNumber))
            else:
                targets[row.SheetNumber] = row
            owner = existing_numbers.get(row.SheetNumber)
            if owner is not None and owner not in selected_ids:
                errors.append(u'目标图纸编号“{}”已被筛选范围外的图纸占用。'.format(row.SheetNumber))
        return errors

    def _execute_numbers(self, rows):
        staged = []
        for row in rows:
            try:
                sheet = doc.GetElement(ElementId(row.ElementIdValue))
                sheet.SheetNumber = u'__TMP_SHEET_{}__'.format(row.ElementIdValue)
                staged.append(row)
            except Exception as ex:
                row.update(u'失败', u'临时编号写入失败：{}'.format(text(ex)))
        for row in staged:
            try:
                doc.GetElement(ElementId(row.ElementIdValue)).SheetNumber = row.SheetNumber
            except Exception as ex:
                try:
                    doc.GetElement(ElementId(row.ElementIdValue)).SheetNumber = row.OriginalSheetNumber
                    row.update(u'失败', u'最终编号写入失败，已恢复原编号：{}'.format(text(ex)))
                except Exception as restore_ex:
                    row.update(u'失败', u'最终编号写入失败：{}；原编号恢复失败：{}'.format(text(ex), text(restore_ex)))

    def Execute_Click(self, sender, e):
        if self.rows.Count == 0:
            forms.alert(u'请先点击“生成预览”加载图纸清单。', title=u'无法执行')
            return
        try:
            self._commit_grid_edit()
        except Exception as ex:
            forms.alert(text(ex), title=u'无法执行')
            return
        errors = self._validate_rows()
        if errors:
            message = u'\n'.join(errors[:12])
            if len(errors) > 12:
                message += u'\n另有 {} 项编号或名称错误。'.format(len(errors) - 12)
            self._log(message)
            forms.alert(message, title=u'请先修正表格')
            return
        number_rows = [x for x in self.rows if x.HasNumberChange]
        name_rows = [x for x in self.rows if x.HasNameChange]
        parameter_rows = [x for x in self.rows if x.HasParameterChange and x.Status != u'失败']
        if not number_rows and not name_rows and not parameter_rows:
            forms.alert(u'表格内没有任何修改，无需执行。', title=u'无需执行')
            return
        tx = Transaction(doc, u'批量图纸管理')
        tx_started = False
        try:
            tx.Start()
            tx_started = True
            self._execute_numbers(number_rows)
            for row in name_rows:
                if row.Status == u'失败':
                    continue
                try:
                    doc.GetElement(ElementId(row.ElementIdValue)).Name = row.SheetName
                except Exception as ex:
                    row.update(u'失败', u'图纸名称写入失败：{}'.format(text(ex)))
            for row in parameter_rows:
                if row.Status == u'失败':
                    continue
                try:
                    set_parameter_value(doc.GetElement(ElementId(row.ElementIdValue)).LookupParameter(row.ParameterName), row.ParameterTarget)
                except Exception as ex:
                    row.update(u'失败', u'属性“{}”写入失败：{}'.format(row.ParameterName, text(ex)))
            tx.Commit()
        except Exception as ex:
            if tx_started:
                tx.RollBack()
            message = u'事务失败，所有本次写入均已回滚：{}'.format(text(ex))
            self._log(message)
            LOGGER.error(message)
            forms.alert(message, title=u'执行失败')
            return
        for row in self.rows:
            if row.Status != u'失败':
                if row.HasNumberChange or row.HasNameChange or row.HasParameterChange:
                    row.update(u'成功', u'已按表格最终值更新。')
                else:
                    row.update(u'未修改', u'编号、名称和属性均未改变。')
        success = len([x for x in self.rows if x.Status == u'成功'])
        failed = len([x for x in self.rows if x.Status == u'失败'])
        summary = u'执行完成：成功更新 {0} 张图纸，失败 {1} 张。'.format(success, failed)
        self._summary(summary)
        self._log(summary)
        forms.alert(summary, title=u'批量图纸管理')

    def Close_Click(self, sender, e):
        self.Close()


if __name__ == '__main__':
    SheetManager().ShowDialog()
