# -*- coding: utf-8 -*-
"""模型统计：按范围和族/类型筛选，统计族实例数量。"""
from __future__ import division

import os
import traceback

import clr

clr.AddReference('RevitAPI')
clr.AddReference('PresentationFramework')
clr.AddReference('System.IO.Compression')
clr.AddReference('System.Windows.Forms')

from Autodesk.Revit.DB import BuiltInCategory, BuiltInParameter, ElementId, FamilyInstance, FilteredElementCollector, UnitUtils, ViewSheet
from System import Environment
from System.IO import FileMode, FileStream, StreamWriter
from System.IO.Compression import ZipArchive, ZipArchiveMode
from System.Security import SecurityElement
from System.Text import UTF8Encoding
from System.Windows.Forms import DialogResult, SaveFileDialog
from pyrevit import forms, revit, script
from pyrevit.forms import WPFWindow

try:
    from Autodesk.Revit.DB import UnitTypeId
except Exception:
    UnitTypeId = None

try:
    from Autodesk.Revit.DB import DisplayUnitType
except Exception:
    DisplayUnitType = None

try:
    unicode
except NameError:
    unicode = str


doc = revit.doc
uidoc = revit.uidoc
LOGGER = script.get_logger()
PAYLOAD_ROOT = os.path.dirname(os.path.realpath(__file__))
ALL_VALUE = u'全部'
SCOPE_ALL = u'全模型'
SCOPE_VIEW = u'当前视图'
SCOPE_SELECTION = u'当前选择'


def to_text(value):
    if value is None:
        return u''
    if isinstance(value, unicode):
        return value
    try:
        return unicode(value)
    except Exception:
        return unicode(str(value))


def get_element_id_value(element_id):
    try:
        return element_id.IntegerValue
    except Exception:
        return int(element_id.Value)


def get_category_name(element):
    category = element.Category
    if category is None:
        return u''
    return to_text(category.Name).strip()


def get_type_name(element):
    try:
        element_type = doc.GetElement(element.GetTypeId())
    except Exception:
        element_type = None
    if element_type is None:
        return u''
    try:
        name = element_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
        if name:
            return to_text(name).strip()
    except Exception:
        pass
    return to_text(element_type.Name).strip()


def get_family_name(element):
    try:
        symbol = element.Symbol
        family = symbol.Family
        if family is not None:
            return to_text(family.Name).strip()
    except Exception:
        pass
    return u''


def convert_feet_to_meters(value):
    if UnitTypeId is not None:
        return UnitUtils.ConvertFromInternalUnits(value, UnitTypeId.Meters)
    if DisplayUnitType is not None:
        return UnitUtils.ConvertFromInternalUnits(value, DisplayUnitType.DUT_METERS)
    return value * 0.3048


def format_number(value):
    return u'{0}'.format(int(value))


def format_length_meters(value):
    return u'{0:.2f} m'.format(float(value))


class StatisticsCore(object):
    """不依赖 Revit API 的统计和筛选逻辑。"""

    @staticmethod
    def distinct_values(items, key):
        values = set()
        for item in items:
            value = to_text(item.get(key)).strip()
            if value:
                values.add(value)
        return sorted(values, key=lambda value: value.lower())

    @staticmethod
    def filter_items(items, family_name=ALL_VALUE, type_name=ALL_VALUE):
        filtered = []
        for item in items:
            if family_name and family_name != ALL_VALUE and item.get('family_name') != family_name:
                continue
            if type_name and type_name != ALL_VALUE and item.get('type_name') != type_name:
                continue
            filtered.append(item)
        return filtered

    @staticmethod
    def aggregate(items):
        grouped = {}
        for item in items:
            key = (
                item.get('category_name') or u'未分类',
                item.get('family_name') or u'未命名族',
                item.get('type_name') or u'未命名类型',
            )
            if key not in grouped:
                grouped[key] = {
                    'category_name': key[0],
                    'family_name': key[1],
                    'type_name': key[2],
                    'instance_count': 0,
                    'element_ids': [],
                }
            grouped[key]['instance_count'] += 1
            grouped[key]['element_ids'].append(item.get('element_id'))

        rows = list(grouped.values())
        rows.sort(key=lambda row: (
            row['category_name'].lower(),
            row['family_name'].lower(),
            row['type_name'].lower(),
        ))
        return rows


class RevitHostAdapter(object):
    """Revit API 适配层，向界面提供标准化的族实例记录。"""

    def __init__(self, document, ui_document):
        self.doc = document
        self.uidoc = ui_document

    def _collect_from_scope(self, scope):
        if scope == SCOPE_VIEW:
            return FilteredElementCollector(self.doc, self.doc.ActiveView.Id).OfClass(FamilyInstance).WhereElementIsNotElementType()
        if scope == SCOPE_SELECTION:
            elements = []
            for element_id in self.uidoc.Selection.GetElementIds():
                element = self.doc.GetElement(element_id)
                if element is not None and isinstance(element, FamilyInstance):
                    elements.append(element)
            return elements
        return FilteredElementCollector(self.doc).OfClass(FamilyInstance).WhereElementIsNotElementType()

    def collect_family_instances(self, scope):
        records = []
        for element in self._collect_from_scope(scope):
            records.append({
                'element_id': get_element_id_value(element.Id),
                'category_name': get_category_name(element),
                'family_name': get_family_name(element),
                'type_name': get_type_name(element),
            })
        return records

    def collect_overview(self):
        family_instances = list(
            FilteredElementCollector(self.doc)
            .OfClass(FamilyInstance)
            .WhereElementIsNotElementType()
        )
        family_categories = set()
        for instance in family_instances:
            category_name = get_category_name(instance)
            if category_name:
                family_categories.add(category_name)

        cable_trays = list(
            FilteredElementCollector(self.doc)
            .OfCategory(BuiltInCategory.OST_CableTray)
            .WhereElementIsNotElementType()
        )
        cable_tray_types = set()
        cable_tray_length_feet = 0.0
        cable_trays_without_length = 0
        for cable_tray in cable_trays:
            type_name = get_type_name(cable_tray)
            if type_name:
                cable_tray_types.add(type_name)
            parameter = cable_tray.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH)
            if parameter is None or not parameter.HasValue:
                cable_trays_without_length += 1
            else:
                cable_tray_length_feet += parameter.AsDouble()

        sheets = list(
            FilteredElementCollector(self.doc)
            .OfClass(ViewSheet)
            .WhereElementIsNotElementType()
        )
        return {
            'family_category_count': len(family_categories),
            'family_instance_count': len(family_instances),
            'cable_tray_type_count': len(cable_tray_types),
            'cable_tray_count': len(cable_trays),
            'cable_tray_total_length_m': convert_feet_to_meters(cable_tray_length_feet),
            'cable_trays_without_length': cable_trays_without_length,
            'sheet_count': len(sheets),
        }

    def collect_sheet_rows(self):
        rows = []
        sheets = list(
            FilteredElementCollector(self.doc)
            .OfClass(ViewSheet)
            .WhereElementIsNotElementType()
        )
        for sheet in sheets:
            rows.append({
                'sheet_number': to_text(sheet.SheetNumber).strip(),
                'sheet_name': to_text(sheet.Name).strip(),
            })
        rows.sort(key=lambda row: (
            row['sheet_number'].lower(),
            row['sheet_name'].lower(),
        ))
        return rows


class XlsxExporter(object):
    """使用 .NET 标准库生成不依赖 Excel 的 XLSX 文件。"""

    @staticmethod
    def _xml_text(value):
        text = to_text(value)
        valid_chars = []
        for character in text:
            code = ord(character)
            if code in (9, 10, 13) or code >= 32:
                valid_chars.append(character)
        escaped = SecurityElement.Escape(u''.join(valid_chars))
        return escaped if escaped is not None else u''

    @staticmethod
    def _column_name(index):
        name = u''
        while index > 0:
            index, remainder = divmod(index - 1, 26)
            name = chr(65 + remainder) + name
        return name

    @staticmethod
    def _write_entry(archive, path, content):
        entry = archive.CreateEntry(path)
        writer = StreamWriter(entry.Open(), UTF8Encoding(False))
        try:
            writer.Write(content)
        finally:
            writer.Dispose()

    @classmethod
    def _worksheet_xml(cls, rows):
        xml_rows = [
            u'<row r="1">'
            u'<c r="A1" t="inlineStr"><is><t>图纸编号</t></is></c>'
            u'<c r="B1" t="inlineStr"><is><t>图纸名称</t></is></c>'
            u'</row>'
        ]
        for row_index, row in enumerate(rows, 2):
            number = cls._xml_text(row.get('sheet_number'))
            name = cls._xml_text(row.get('sheet_name'))
            xml_rows.append(
                u'<row r="{0}">'
                u'<c r="A{0}" t="inlineStr"><is><t>{1}</t></is></c>'
                u'<c r="B{0}" t="inlineStr"><is><t>{2}</t></is></c>'
                u'</row>'.format(row_index, number, name)
            )
        return u'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
           xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <dimension ref="A1:B{0}"/>
  <sheetViews><sheetView workbookViewId="0"/></sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols><col min="1" max="1" width="18" customWidth="1"/><col min="2" max="2" width="36" customWidth="1"/></cols>
  <sheetData>{1}</sheetData>
</worksheet>'''.format(len(rows) + 1, u''.join(xml_rows))

    @classmethod
    def export_sheet_names(cls, rows, file_path):
        content_types = u'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>'''
        package_rels = u'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''
        workbook = u'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="图纸名称" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''
        workbook_rels = u'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''
        styles = u'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><color theme="1"/><name val="等线"/><family val="2"/></font>
    <font><b/><sz val="11"/><color theme="1"/><name val="等线"/><family val="2"/></font>
  </fonts>
  <fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/></cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''
        worksheet = cls._worksheet_xml(rows)
        stream = None
        archive = None
        try:
            stream = FileStream(file_path, FileMode.Create)
            archive = ZipArchive(stream, ZipArchiveMode.Create)
            cls._write_entry(archive, '[Content_Types].xml', content_types)
            cls._write_entry(archive, '_rels/.rels', package_rels)
            cls._write_entry(archive, 'xl/workbook.xml', workbook)
            cls._write_entry(archive, 'xl/_rels/workbook.xml.rels', workbook_rels)
            cls._write_entry(archive, 'xl/styles.xml', styles)
            cls._write_entry(archive, 'xl/worksheets/sheet1.xml', worksheet)
        finally:
            if archive is not None:
                archive.Dispose()
            if stream is not None:
                stream.Dispose()


class StatisticRow(object):
    def __init__(self, data):
        self.Category = data['category_name']
        self.FamilyName = data['family_name']
        self.TypeName = data['type_name']
        self.InstanceCount = format_number(data['instance_count'])
        self.ElementIds = u', '.join([to_text(value) for value in data['element_ids']])


class MainToolWindow(WPFWindow):
    def __init__(self):
        xaml_path = os.path.join(PAYLOAD_ROOT, 'ui.xaml')
        WPFWindow.__init__(self, xaml_path)
        self.adapter = RevitHostAdapter(doc, uidoc)
        self.raw_items = []
        self.current_scope = SCOPE_ALL
        self._load_scope_options()
        self._load_overview()
        self._scan()

    def _set_items(self, control, values):
        control.ItemsSource = None
        control.ItemsSource = values
        if values:
            control.SelectedIndex = 0

    def _load_scope_options(self):
        self._set_items(self.ScopeComboBox, [SCOPE_ALL, SCOPE_VIEW, SCOPE_SELECTION])

    def _load_overview(self):
        stats = self.adapter.collect_overview()
        self.FamilyCategoryCountTextBlock.Text = format_number(stats['family_category_count'])
        self.FamilyInstanceCountTextBlock.Text = format_number(stats['family_instance_count'])
        self.CableTrayCountTextBlock.Text = format_number(stats['cable_tray_count'])
        self.SheetCountTextBlock.Text = format_number(stats['sheet_count'])
        self.OverviewDetailTextBlock.Text = u'电缆桥架类型 {0} 个 | 总长度 {1}'.format(
            format_number(stats['cable_tray_type_count']),
            format_length_meters(stats['cable_tray_total_length_m']),
        )
        if stats['cable_trays_without_length'] > 0:
            self._append_log(u'提示：{0} 个电缆桥架缺少可读取长度，未计入总长度。'.format(
                format_number(stats['cable_trays_without_length'])
            ))

    def _scope(self):
        value = self.ScopeComboBox.SelectedItem
        return to_text(value) if value else SCOPE_ALL

    def _scan(self):
        self.current_scope = self._scope()
        self.raw_items = self.adapter.collect_family_instances(self.current_scope)
        families = [ALL_VALUE] + StatisticsCore.distinct_values(self.raw_items, 'family_name')
        self._set_items(self.FamilyComboBox, families)
        self._load_types()
        self._apply_filter()
        self._append_log(u'扫描完成：{0} 范围内找到 {1} 个族实例。'.format(
            self.current_scope, format_number(len(self.raw_items))
        ))

    def _load_types(self, sender=None, args=None):
        family_name = to_text(self.FamilyComboBox.SelectedItem) if self.FamilyComboBox.SelectedItem else ALL_VALUE
        family_items = StatisticsCore.filter_items(self.raw_items, family_name=family_name)
        types = [ALL_VALUE] + StatisticsCore.distinct_values(family_items, 'type_name')
        self._set_items(self.TypeComboBox, types)

    def _apply_filter(self, sender=None, args=None):
        family_name = to_text(self.FamilyComboBox.SelectedItem) if self.FamilyComboBox.SelectedItem else ALL_VALUE
        type_name = to_text(self.TypeComboBox.SelectedItem) if self.TypeComboBox.SelectedItem else ALL_VALUE
        filtered = StatisticsCore.filter_items(self.raw_items, family_name, type_name)
        rows = [StatisticRow(row) for row in StatisticsCore.aggregate(filtered)]
        self.ResultsDataGrid.ItemsSource = rows
        self.SelectedCountTextBlock.Text = format_number(len(filtered))
        self.ResultGroupCountTextBlock.Text = format_number(len(rows))
        self.FilterSummaryTextBlock.Text = u'范围：{0} | 族：{1} | 类型：{2}'.format(
            self.current_scope, family_name, type_name
        )
        self.StatusTextBlock.Text = u'当前结果：{0} 个族实例，{1} 个族/类型组合。'.format(
            format_number(len(filtered)), format_number(len(rows))
        )

    def _append_log(self, message):
        if not hasattr(self, 'LogTextBox'):
            return
        old_text = to_text(self.LogTextBox.Text)
        self.LogTextBox.Text = (old_text + u'\n' if old_text else u'') + message
        self.LogTextBox.ScrollToEnd()

    def ScopeComboBox_SelectionChanged(self, sender, args):
        self._scan()

    def FamilyComboBox_SelectionChanged(self, sender, args):
        self._load_types()
        self._apply_filter()

    def TypeComboBox_SelectionChanged(self, sender, args):
        self._apply_filter()

    def Scan_Click(self, sender, args):
        try:
            self._scan()
        except Exception as ex:
            self._show_error(ex)

    def _choose_export_path(self):
        dialog = SaveFileDialog()
        dialog.Title = u'导出图纸名称'
        dialog.Filter = u'Excel 工作簿 (*.xlsx)|*.xlsx'
        dialog.DefaultExt = u'xlsx'
        dialog.AddExtension = True
        dialog.OverwritePrompt = True
        dialog.FileName = u'图纸名称.xlsx'
        documents = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments)
        if documents and os.path.isdir(documents):
            dialog.InitialDirectory = documents
        try:
            if dialog.ShowDialog() != DialogResult.OK:
                return None
            return to_text(dialog.FileName)
        finally:
            dialog.Dispose()

    def ExportSheets_Click(self, sender, args):
        try:
            output_path = self._choose_export_path()
            if not output_path:
                self._append_log(u'已取消图纸名称导出。')
                return
            rows = self.adapter.collect_sheet_rows()
            XlsxExporter.export_sheet_names(rows, output_path)
            self._append_log(u'图纸名称导出完成：{0} 个图纸，文件：{1}'.format(
                format_number(len(rows)), output_path
            ))
            forms.alert(
                u'已导出 {0} 个图纸名称。\n\n文件：{1}'.format(
                    format_number(len(rows)), output_path
                ),
                title=u'导出完成'
            )
        except Exception as ex:
            self._show_error(ex)

    def RefreshOverview_Click(self, sender, args):
        try:
            self._load_overview()
            self._scan()
        except Exception as ex:
            self._show_error(ex)

    def Close_Click(self, sender, args):
        self.Close()

    def _show_error(self, ex):
        detail = traceback.format_exc()
        LOGGER.error(detail)
        self._append_log(u'统计失败：{0}'.format(to_text(ex)))
        forms.alert(
            u'模型统计失败：\n{0}\n\n详细错误：\n{1}'.format(to_text(ex), to_text(detail)),
            title=u'模型统计失败'
        )


def main():
    if doc is None:
        forms.alert(u'当前没有打开的 Revit 文档，无法统计模型信息。', title=u'模型统计')
        return
    try:
        window = MainToolWindow()
        window.ShowDialog()
    except Exception as ex:
        detail = traceback.format_exc()
        LOGGER.error(detail)
        forms.alert(
            u'模型统计启动失败：\n{0}\n\n详细错误：\n{1}'.format(to_text(ex), to_text(detail)),
            title=u'模型统计失败'
        )


if __name__ == '__main__':
    main()
