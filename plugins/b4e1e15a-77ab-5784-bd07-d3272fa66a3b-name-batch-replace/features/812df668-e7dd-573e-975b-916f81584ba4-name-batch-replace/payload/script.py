# -*- coding: utf-8 -*-
import os
import clr

clr.AddReference('RevitAPI')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import (
    ElementId,
    Family,
    FamilySymbol,
    FilteredElementCollector,
    FilteredWorksetCollector,
    Transaction,
    View,
    ViewSheet,
    WorksetId,
    WorksetKind,
    WorksetTable,
)
from pyrevit import forms, revit, script
from System import EventHandler
from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
from System.Windows.Media import Color, SolidColorBrush

try:
    unicode
except NameError:
    unicode = str


doc = revit.doc
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
XAML_FILE = os.path.join(SCRIPT_DIR, 'ui.xaml')
LOGGER = script.get_logger()


LIGHT_THEME = {
    "WindowBg": "#F5F7FA",
    "Surface": "#FFFFFF",
    "SurfaceAlt": "#F8FAFC",
    "Text": "#1F2937",
    "MutedText": "#64748B",
    "Border": "#D7E0EA",
    "Primary": "#1D4ED8",
    "Success": "#15803D",
    "Warning": "#B45309",
    "Danger": "#B91C1C",
}

DARK_THEME = {
    "WindowBg": "#0F172A",
    "Surface": "#111827",
    "SurfaceAlt": "#1F2937",
    "Text": "#E5E7EB",
    "MutedText": "#94A3B8",
    "Border": "#334155",
    "Primary": "#60A5FA",
    "Success": "#4ADE80",
    "Warning": "#F59E0B",
    "Danger": "#F87171",
}


def color_from_hex(hex_value):
    value = (hex_value or '').strip().lstrip('#')
    if len(value) != 6:
        raise ValueError('颜色值必须是 6 位十六进制，当前为: {}'.format(hex_value))
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
        return {"theme": u"浅色", "is_dark": False}
    theme = ctx.get('theme') or u'浅色'
    return {
        "theme": theme,
        "is_dark": bool(ctx.get('is_dark')) or theme == u'深色',
    }


def to_text(value):
    if value is None:
        return u''
    if isinstance(value, unicode):
        return value
    try:
        return unicode(value)
    except Exception:
        return unicode(str(value))


def is_blank(value):
    return not to_text(value).strip()


def collect_families():
    families = []
    for family in FilteredElementCollector(doc).OfClass(Family):
        try:
            name = to_text(family.Name)
        except Exception:
            continue
        if not name:
            continue
        families.append(family)
    return sorted(families, key=lambda x: to_text(x.Name).lower())


def collect_family_types():
    family_types = []
    for family_type in FilteredElementCollector(doc).OfClass(FamilySymbol):
        try:
            name = to_text(family_type.Name)
            family_name = to_text(family_type.Family.Name)
        except Exception:
            continue
        if not name:
            continue
        family_types.append((family_type, family_name))
    return sorted(family_types, key=lambda x: (x[1].lower(), to_text(x[0].Name).lower()))


def collect_user_worksets():
    worksets = list(FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset))
    return sorted(worksets, key=lambda x: to_text(x.Name).lower())


def collect_sheets():
    sheets = list(FilteredElementCollector(doc).OfClass(ViewSheet).WhereElementIsNotElementType())
    return sorted(sheets, key=lambda x: to_text(x.Name).lower())


def collect_views():
    views = []
    for view in FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType():
        if view is None:
            continue
        try:
            if view.IsTemplate:
                continue
        except Exception:
            pass
        if isinstance(view, ViewSheet):
            continue
        try:
            name = to_text(view.Name)
        except Exception:
            continue
        if not name:
            continue
        views.append(view)
    return sorted(views, key=lambda x: to_text(x.Name).lower())


def collect_view_templates():
    templates = []
    for view in FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType():
        try:
            if not view.IsTemplate:
                continue
            name = to_text(view.Name)
        except Exception:
            continue
        if name:
            templates.append(view)
    return sorted(templates, key=lambda x: to_text(x.Name).lower())


class RenamePreviewItem(INotifyPropertyChanged):
    def __init__(self, category, element_id, source_name, target_name, status, message):
        self.Category = category
        self.ElementIdValue = int(element_id)
        self._source_name = source_name
        self._target_name = target_name
        self._status = status
        self._message = message
        self._pc = None

    def add_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Combine(self._pc, value)

    def remove_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Remove(self._pc, value)

    def on_property_changed(self, name):
        if self._pc is not None:
            self._pc(self, PropertyChangedEventArgs(name))

    @property
    def SourceName(self):
        return self._source_name

    @SourceName.setter
    def SourceName(self, value):
        self._source_name = value
        self.on_property_changed('SourceName')

    @property
    def TargetName(self):
        return self._target_name

    @TargetName.setter
    def TargetName(self, value):
        self._target_name = value
        self.on_property_changed('TargetName')

    @property
    def Status(self):
        return self._status

    @Status.setter
    def Status(self, value):
        self._status = value
        self.on_property_changed('Status')

    @property
    def Message(self):
        return self._message

    @Message.setter
    def Message(self, value):
        self._message = value
        self.on_property_changed('Message')

    @property
    def CanExecute(self):
        return self.Status == u'待执行'


class RenameToolWindow(forms.WPFWindow):
    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file)
        self.theme_context = get_omnimetro_theme_context()
        self.apply_theme()
        self.preview_items = ObservableCollection[RenamePreviewItem]()
        self.PreviewDataGrid.ItemsSource = self.preview_items
        self.log_lines = []
        self._write_log(u'已加载当前文档。请输入需要替换的字符串后先执行预览。')

    def apply_theme(self):
        palette = DARK_THEME if self.theme_context["is_dark"] else LIGHT_THEME
        for key, value in palette.items():
            self.Resources[key + 'Brush'] = brush_from_hex(value)
        self.Background = self.Resources['WindowBgBrush']

    def _write_log(self, line):
        self.log_lines.append(to_text(line))
        self.LogTextBox.Text = u'\n'.join(self.log_lines)
        try:
            self.LogTextBox.ScrollToEnd()
        except Exception:
            pass

    def _set_summary(self, text):
        self.SummaryTextBlock.Text = to_text(text)

    def _clear_preview(self):
        self.preview_items.Clear()

    def _get_inputs(self):
        return {
            'find': to_text(self.FindTextBox.Text),
            'replace': to_text(self.ReplaceTextBox.Text),
        }

    def _get_selected_categories(self):
        return {
            'families': bool(self.FamilyCheckBox.IsChecked),
            'types': bool(self.TypeCheckBox.IsChecked),
            'sheets': bool(self.SheetCheckBox.IsChecked),
            'views': bool(self.ViewCheckBox.IsChecked),
            'templates': bool(self.ViewTemplateCheckBox.IsChecked),
            'worksets': bool(self.WorksetCheckBox.IsChecked),
        }

    def _validate_request(self, selected):
        values = self._get_inputs()
        errors = []
        if is_blank(values['find']):
            errors.append(u'“查找字符串”不能为空。')
        if not any(selected.values()):
            errors.append(u'至少需要勾选一个替换类别。')
        return values, errors

    def _build_type_preview(self, find_text, replace_text):
        family_types = collect_family_types()
        names_by_family = {}
        planned_by_family = {}
        items = []

        for family_type, family_name in family_types:
            family_id = family_type.Family.Id.IntegerValue
            names_by_family.setdefault(family_id, set()).add(to_text(family_type.Name))

        for family_type, family_name in family_types:
            source_name = to_text(family_type.Name)
            if find_text not in source_name:
                continue

            family_id = family_type.Family.Id.IntegerValue
            target_name = source_name.replace(find_text, replace_text)
            status = u'待执行'
            message = u'匹配成功，执行时将重命名族“{0}”中的类型。'.format(family_name)
            planned_names = planned_by_family.setdefault(family_id, {})

            if is_blank(target_name):
                status = u'跳过'
                message = u'替换后名称为空，请调整替换字符串。'
            elif target_name == source_name:
                status = u'跳过'
                message = u'替换后名称未发生变化。'
            elif target_name in names_by_family[family_id] and target_name != source_name:
                status = u'冲突'
                message = u'族“{0}”中已存在目标类型名称。'.format(family_name)
            elif target_name in planned_names and planned_names[target_name] != source_name:
                status = u'冲突'
                message = u'族“{0}”中的多个类型会被替换成同一个名称。'.format(family_name)
            else:
                planned_names[target_name] = source_name

            items.append(RenamePreviewItem(
                u'类型', family_type.Id.IntegerValue, source_name, target_name, status, message
            ))

        return items

    def _build_family_preview(self, find_text, replace_text):
        families = collect_families()
        existing_names = set([to_text(f.Name) for f in families])
        planned_names = {}
        items = []

        for family in families:
            source_name = to_text(family.Name)
            if find_text not in source_name:
                continue

            target_name = source_name.replace(find_text, replace_text)
            status = u'待执行'
            message = u'匹配成功，执行时将重命名族。'

            if getattr(family, 'IsInPlace', False):
                status = u'跳过'
                message = u'族为内建模型族，通常不应批量重命名。'
            elif hasattr(family, 'IsEditable') and not family.IsEditable:
                status = u'跳过'
                message = u'族不可编辑，Revit 可能不允许直接重命名。'
            elif is_blank(target_name):
                status = u'跳过'
                message = u'替换后名称为空，请调整替换字符串。'
            elif target_name == source_name:
                status = u'跳过'
                message = u'替换后名称未发生变化。'
            elif target_name in existing_names and target_name != source_name:
                status = u'冲突'
                message = u'目标名称已存在于当前文档的其他族中。'
            elif target_name in planned_names and planned_names[target_name] != source_name:
                status = u'冲突'
                message = u'多个族会被替换成同一个名称。'
            else:
                planned_names[target_name] = source_name

            items.append(RenamePreviewItem(u'族', family.Id.IntegerValue, source_name, target_name, status, message))

        return items

    def _build_workset_preview(self, find_text, replace_text):
        worksets = collect_user_worksets()
        existing_names = set([to_text(w.Name) for w in worksets])
        planned_names = {}
        items = []

        for workset in worksets:
            source_name = to_text(workset.Name)
            if find_text not in source_name:
                continue

            target_name = source_name.replace(find_text, replace_text)
            status = u'待执行'
            message = u'匹配成功，执行时将重命名工作集。'

            if is_blank(target_name):
                status = u'跳过'
                message = u'替换后名称为空，请调整替换字符串。'
            elif target_name == source_name:
                status = u'跳过'
                message = u'替换后名称未发生变化。'
            elif target_name in existing_names and target_name != source_name:
                status = u'冲突'
                message = u'目标名称已存在于当前文档的其他用户工作集中。'
            elif target_name in planned_names and planned_names[target_name] != source_name:
                status = u'冲突'
                message = u'多个工作集会被替换成同一个名称。'
            else:
                planned_names[target_name] = source_name

            items.append(RenamePreviewItem(u'工作集', workset.Id.IntegerValue, source_name, target_name, status, message))

        return items

    def _build_sheet_preview(self, find_text, replace_text):
        sheets = collect_sheets()
        items = []

        for sheet in sheets:
            source_name = to_text(sheet.Name)
            if find_text not in source_name:
                continue

            target_name = source_name.replace(find_text, replace_text)
            status = u'待执行'
            message = u'匹配成功，执行时将重命名图纸名称。'

            if is_blank(target_name):
                status = u'跳过'
                message = u'替换后名称为空，请调整替换字符串。'
            elif target_name == source_name:
                status = u'跳过'
                message = u'替换后名称未发生变化。'

            items.append(RenamePreviewItem(u'图纸', sheet.Id.IntegerValue, source_name, target_name, status, message))

        return items

    def _build_view_preview(self, find_text, replace_text):
        views = collect_views()
        existing_names = set([to_text(v.Name) for v in views + collect_view_templates()])
        planned_names = {}
        items = []

        for view in views:
            source_name = to_text(view.Name)
            if find_text not in source_name:
                continue

            target_name = source_name.replace(find_text, replace_text)
            status = u'待执行'
            message = u'匹配成功，执行时将重命名视图名称。'

            if is_blank(target_name):
                status = u'跳过'
                message = u'替换后名称为空，请调整替换字符串。'
            elif target_name == source_name:
                status = u'跳过'
                message = u'替换后名称未发生变化。'
            elif target_name in existing_names and target_name != source_name:
                status = u'冲突'
                message = u'目标名称已存在于当前文档的其他视图中。'
            elif target_name in planned_names and planned_names[target_name] != source_name:
                status = u'冲突'
                message = u'多个视图会被替换成同一个名称。'
            else:
                planned_names[target_name] = source_name

            items.append(RenamePreviewItem(u'视图', view.Id.IntegerValue, source_name, target_name, status, message))

        return items

    def _build_view_template_preview(self, find_text, replace_text):
        templates = collect_view_templates()
        existing_names = set([to_text(v.Name) for v in collect_views() + templates])
        planned_names = {}
        items = []

        for template in templates:
            source_name = to_text(template.Name)
            if find_text not in source_name:
                continue

            target_name = source_name.replace(find_text, replace_text)
            status = u'待执行'
            message = u'匹配成功，执行时将重命名视图样板。'

            if is_blank(target_name):
                status = u'跳过'
                message = u'替换后名称为空，请调整替换字符串。'
            elif target_name == source_name:
                status = u'跳过'
                message = u'替换后名称未发生变化。'
            elif target_name in existing_names and target_name != source_name:
                status = u'冲突'
                message = u'目标名称已存在于当前文档的其他视图样板中。'
            elif target_name in planned_names and planned_names[target_name] != source_name:
                status = u'冲突'
                message = u'多个视图样板会被替换成同一个名称。'
            else:
                planned_names[target_name] = source_name

            items.append(RenamePreviewItem(
                u'视图样板', template.Id.IntegerValue, source_name, target_name, status, message
            ))

        return items

    def _mark_cross_view_conflicts(self, items):
        planned = {}
        for item in items:
            if item.Category not in (u'视图', u'视图样板') or item.Status != u'待执行':
                continue
            planned.setdefault(item.TargetName, []).append(item)

        for target_name, target_items in planned.items():
            if len(target_items) < 2:
                continue
            for item in target_items:
                item.Status = u'冲突'
                item.Message = u'普通视图与视图样板中有多个对象会被替换成名称“{0}”。'.format(target_name)

    def _preview(self):
        selected = self._get_selected_categories()
        values, errors = self._validate_request(selected)
        if errors:
            message = u'\n'.join(errors)
            self._write_log(message)
            forms.alert(message, title=u'输入不完整')
            return

        self._clear_preview()
        items = []

        find_text = values['find']
        replace_text = values['replace']
        if selected['families']:
            items.extend(self._build_family_preview(find_text, replace_text))
        if selected['types']:
            items.extend(self._build_type_preview(find_text, replace_text))
        if selected['sheets']:
            items.extend(self._build_sheet_preview(find_text, replace_text))
        if selected['views']:
            items.extend(self._build_view_preview(find_text, replace_text))
        if selected['templates']:
            items.extend(self._build_view_template_preview(find_text, replace_text))
        if selected['worksets']:
            items.extend(self._build_workset_preview(find_text, replace_text))

        self._mark_cross_view_conflicts(items)

        for item in sorted(items, key=lambda x: (x.Category, x.SourceName.lower())):
            self.preview_items.Add(item)

        ready_count = len([x for x in items if x.Status == u'待执行'])
        skip_count = len([x for x in items if x.Status == u'跳过'])
        conflict_count = len([x for x in items if x.Status == u'冲突'])

        if not items:
            self._set_summary(u'未找到任何匹配项。')
            self._write_log(u'预览完成：未找到任何匹配项。')
            forms.alert(u'未找到任何匹配项。请检查查找字符串是否正确。', title=u'预览结果')
            return

        summary = u'共 {0} 项，待执行 {1}，跳过 {2}，冲突 {3}'.format(
            len(items), ready_count, skip_count, conflict_count
        )
        self._set_summary(summary)
        self._write_log(u'预览完成：' + summary)

    def Preview_Click(self, sender, e):
        self._preview()

    def Execute_Click(self, sender, e):
        if self.preview_items.Count == 0:
            forms.alert(u'请先生成预览，再执行替换。', title=u'无法执行')
            return

        executable_items = [item for item in self.preview_items if item.CanExecute]
        if not executable_items:
            forms.alert(u'当前预览中没有可执行项。请先调整替换条件。', title=u'无法执行')
            return

        success_count = 0
        fail_count = 0
        tx = Transaction(doc, u'名称批量替换')
        tx_started = False

        try:
            tx.Start()
            tx_started = True
            for item in executable_items:
                try:
                    if item.Category == u'族':
                        family = doc.GetElement(ElementId(item.ElementIdValue))
                        if family is None:
                            raise ValueError(u'未找到对应的族元素，可能已被删除。')
                        family.Name = item.TargetName
                    elif item.Category == u'类型':
                        family_type = doc.GetElement(ElementId(item.ElementIdValue))
                        if family_type is None:
                            raise ValueError(u'未找到对应的族类型元素，可能已被删除。')
                        family_type.Name = item.TargetName
                    elif item.Category == u'图纸':
                        sheet = doc.GetElement(ElementId(item.ElementIdValue))
                        if sheet is None:
                            raise ValueError(u'未找到对应的图纸元素，可能已被删除。')
                        sheet.Name = item.TargetName
                    elif item.Category in (u'视图', u'视图样板'):
                        view = doc.GetElement(ElementId(item.ElementIdValue))
                        if view is None:
                            raise ValueError(u'未找到对应的视图元素，可能已被删除。')
                        view.Name = item.TargetName
                    else:
                        WorksetTable.RenameWorkset(doc, WorksetId(item.ElementIdValue), item.TargetName)

                    item.Status = u'成功'
                    item.Message = u'已完成重命名。'
                    success_count += 1
                except Exception as ex:
                    item.Status = u'失败'
                    item.Message = to_text(ex)
                    fail_count += 1
                    LOGGER.exception('名称批量替换失败: %s -> %s', item.SourceName, item.TargetName)
            tx.Commit()
        except Exception as ex:
            if tx_started:
                tx.RollBack()
            detail = to_text(ex)
            self._write_log(u'事务执行失败：' + detail)
            forms.alert(u'批量替换事务执行失败：\n{}'.format(detail), title=u'执行失败')
            return

        summary = u'执行完成：成功 {0}，失败 {1}。'.format(success_count, fail_count)
        self._set_summary(summary)
        self._write_log(summary)

        for item in self.preview_items:
            if item.Status == u'失败':
                self._write_log(u'失败 - {0} - 元素 ID {1} - {2} -> {3}：{4}'.format(
                    item.Category, item.ElementIdValue, item.SourceName, item.TargetName, item.Message
                ))

        if fail_count:
            forms.alert(summary + u'\n\n详细失败原因已写入下方日志。', title=u'执行结束')
        else:
            forms.alert(summary, title=u'执行结束')

    def Close_Click(self, sender, e):
        self.Close()


def main():
    window = RenameToolWindow(XAML_FILE)
    window.ShowDialog()


if __name__ == '__main__':
    main()
