# -*- coding: utf-8 -*-
import os
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    FamilyInstance,
    FilteredElementCollector,
    RevitLinkInstance,
    StorageType,
    Transaction,
    XYZ,
)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import forms, revit, script
from System import EventHandler
from System.Collections.Generic import List
from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
from System.Windows.Controls import ComboBoxItem
from System.Windows.Input import Key
from System.Windows.Media import Color, SolidColorBrush

try:
    unicode
except NameError:
    unicode = str


doc = revit.doc
uidoc = revit.uidoc
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
XAML_FILE = os.path.join(SCRIPT_DIR, 'ui.xaml')
SELECTION_OPTIONS_XAML_FILE = os.path.join(SCRIPT_DIR, 'selection_options.xaml')
LOGGER = script.get_logger()
ROOM_CACHE = None
LINK_ROOM_CONTEXTS = None
ROW_TOLERANCE_FEET = 1.0


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


def get_parameter_text(param):
    if param is None:
        return u''
    try:
        value = param.AsString()
        if value:
            return to_text(value)
    except Exception:
        pass
    try:
        value = param.AsValueString()
        if value:
            return to_text(value)
    except Exception:
        pass
    try:
        if param.StorageType == StorageType.Integer:
            return to_text(param.AsInteger())
        if param.StorageType == StorageType.Double:
            return to_text(param.AsDouble())
        if param.StorageType == StorageType.ElementId:
            return to_text(param.AsElementId().IntegerValue)
    except Exception:
        pass
    return u''


def get_symbol(instance):
    try:
        type_id = instance.GetTypeId()
        if type_id and type_id != ElementId.InvalidElementId:
            return doc.GetElement(type_id)
    except Exception:
        pass
    return None


def get_symbol_name(instance, symbol):
    if symbol is None:
        return u''
    try:
        return to_text(symbol.Name)
    except Exception:
        pass
    try:
        return to_text(instance.Name)
    except Exception:
        return u''


def get_family_name(instance, symbol):
    try:
        if symbol is not None and symbol.Family is not None:
            return to_text(symbol.Family.Name)
    except Exception:
        pass
    try:
        return to_text(instance.Symbol.Family.Name)
    except Exception:
        return u''


def get_element_point(element):
    try:
        location = element.Location
    except Exception:
        location = None
    if location is None:
        return None
    try:
        return location.Point
    except Exception:
        pass
    try:
        return location.Curve.Evaluate(0.5, True)
    except Exception:
        pass
    return None


def get_bounding_box_center(element):
    try:
        bbox = element.get_BoundingBox(None)
    except Exception:
        bbox = None
    if bbox is None:
        return None
    try:
        return XYZ(
            (bbox.Min.X + bbox.Max.X) * 0.5,
            (bbox.Min.Y + bbox.Max.Y) * 0.5,
            (bbox.Min.Z + bbox.Max.Z) * 0.5
        )
    except Exception:
        return None


def get_spatial_calc_point(instance):
    try:
        if hasattr(instance, 'HasSpatialElementCalculationPoint') and instance.HasSpatialElementCalculationPoint:
            return instance.GetSpatialElementCalculationPoint()
    except Exception:
        pass
    return None


def get_numbering_point(element):
    point = get_element_point(element)
    if point is not None:
        return point
    return get_bounding_box_center(element)


def get_view_sort_values(element, view):
    point = get_numbering_point(element)
    if point is None:
        raise ValueError(u'未找到定位点或包围盒中心，无法按视图位置排序。')
    try:
        right = view.RightDirection
        up = view.UpDirection
        x_value = point.DotProduct(right)
        y_value = point.DotProduct(up)
        return x_value, y_value
    except Exception as ex:
        raise ValueError(u'无法读取当前视图方向用于排序：{}'.format(to_text(ex)))


def get_view_sort_key(element, view):
    x_value, y_value = get_view_sort_values(element, view)
    return (round(-y_value, 3), round(x_value, 3), element.Id.IntegerValue)


def sort_items_from_left_to_right_top_to_bottom(items, view):
    rows = []
    prepared = []
    for item in items:
        element = doc.GetElement(ElementId(item.ElementIdValue))
        if element is None:
            raise ValueError(u'未找到对应实例，可能已被删除。')
        x_value, y_value = get_view_sort_values(element, view)
        prepared.append((item, x_value, y_value, item.ElementIdValue))

    for data in sorted(prepared, key=lambda x: (-x[2], x[1], x[3])):
        placed = False
        for row in rows:
            if abs(row['y'] - data[2]) <= ROW_TOLERANCE_FEET:
                row['items'].append(data)
                row['y'] = (row['y'] * (len(row['items']) - 1) + data[2]) / len(row['items'])
                placed = True
                break
        if not placed:
            rows.append({'y': data[2], 'items': [data]})

    ordered = []
    for row in sorted(rows, key=lambda x: -x['y']):
        for data in sorted(row['items'], key=lambda x: (x[1], x[3])):
            ordered.append(data[0])
    return ordered


def get_phase_candidates(element):
    phases = []
    try:
        phase_id = element.CreatedPhaseId
        if phase_id and phase_id != ElementId.InvalidElementId:
            phase = doc.GetElement(phase_id)
            if phase is not None:
                phases.append(phase)
    except Exception:
        pass
    try:
        for phase in list(doc.Phases):
            if phase not in phases:
                phases.append(phase)
    except Exception:
        pass
    return phases


def get_room_elements():
    global ROOM_CACHE
    if ROOM_CACHE is not None:
        return ROOM_CACHE
    rooms = []
    try:
        collector = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()
        for room in collector:
            if room is None:
                continue
            rooms.append(room)
    except Exception:
        pass
    ROOM_CACHE = rooms
    return rooms


def get_room_elements_from_doc(target_doc):
    rooms = []
    if target_doc is None:
        return rooms
    try:
        collector = FilteredElementCollector(target_doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()
        for room in collector:
            if room is None:
                continue
            rooms.append(room)
    except Exception:
        pass
    return rooms


def get_room_bounding_box(room):
    try:
        return room.get_BoundingBox(None)
    except Exception:
        return None


def is_xy_inside_box(point, bbox, tolerance=0.01):
    if point is None or bbox is None:
        return True
    return (
        bbox.Min.X - tolerance <= point.X <= bbox.Max.X + tolerance
        and bbox.Min.Y - tolerance <= point.Y <= bbox.Max.Y + tolerance
    )


def get_room_probe_points(link_point, room_bbox):
    points = [link_point]
    if room_bbox is None:
        return points

    min_z = room_bbox.Min.Z
    max_z = room_bbox.Max.Z
    height = max_z - min_z
    if height <= 0:
        return points

    inset = min(1.0, height * 0.1)
    probe_z_values = [
        (min_z + max_z) * 0.5,
        min_z + inset,
        max_z - inset,
    ]
    for probe_z in probe_z_values:
        if abs(probe_z - link_point.Z) < 0.001:
            continue
        points.append(XYZ(link_point.X, link_point.Y, probe_z))
    return points


def get_link_room_contexts():
    global LINK_ROOM_CONTEXTS
    if LINK_ROOM_CONTEXTS is not None:
        return LINK_ROOM_CONTEXTS
    contexts = []
    try:
        collector = FilteredElementCollector(doc).OfClass(RevitLinkInstance).WhereElementIsNotElementType()
    except Exception:
        return contexts

    for link_instance in collector:
        if link_instance is None:
            continue
        try:
            link_doc = link_instance.GetLinkDocument()
        except Exception:
            link_doc = None
        if link_doc is None:
            continue

        try:
            total_transform = link_instance.GetTotalTransform()
            inverse_transform = total_transform.Inverse
        except Exception:
            continue

        rooms = get_room_elements_from_doc(link_doc)
        if not rooms:
            continue

        room_contexts = []
        for room in rooms:
            room_contexts.append({
                'room': room,
                'bbox': get_room_bounding_box(room),
            })

        contexts.append({
            'link_name': to_text(link_instance.Name),
            'link_doc': link_doc,
            'inverse_transform': inverse_transform,
            'rooms': room_contexts,
        })
    LINK_ROOM_CONTEXTS = contexts
    return contexts


def try_get_room_from_phase_accessor(instance, accessor_name, phase):
    try:
        accessor = getattr(instance, accessor_name, None)
        if accessor is None:
            return None
        room = accessor(phase)
        if room is not None:
            return room
    except Exception:
        pass
    return None


def try_get_room_from_point(point, phases, rooms):
    if point is None:
        return None

    for phase in phases:
        try:
            room = doc.GetRoomAtPoint(point, phase)
            if room is not None:
                return room
        except Exception:
            continue

    try:
        room = doc.GetRoomAtPoint(point)
        if room is not None:
            return room
    except Exception:
        pass

    for room in rooms:
        try:
            if room.IsPointInRoom(point):
                return room
        except Exception:
            continue

    return None


def try_get_room_from_links(point, link_contexts):
    if point is None:
        return None

    for context in link_contexts:
        try:
            link_point = context['inverse_transform'].OfPoint(point)
        except Exception:
            continue

        for room_context in context['rooms']:
            room = room_context['room']
            room_bbox = room_context['bbox']
            if not is_xy_inside_box(link_point, room_bbox):
                continue
            for probe_point in get_room_probe_points(link_point, room_bbox):
                try:
                    if room.IsPointInRoom(probe_point):
                        return room
                except Exception:
                    continue

    return None


def find_room_for_instance(instance):
    for attr in ['Room', 'FromRoom', 'ToRoom', 'Space']:
        try:
            room = getattr(instance, attr)
            if room is not None:
                return room
        except Exception:
            continue

    phases = get_phase_candidates(instance)
    for phase in phases:
        for accessor_name in ['get_Room', 'get_FromRoom', 'get_ToRoom', 'get_Space']:
            room = try_get_room_from_phase_accessor(instance, accessor_name, phase)
            if room is not None:
                return room

    rooms = get_room_elements()
    candidate_points = []
    for point in [
        get_spatial_calc_point(instance),
        get_element_point(instance),
        get_bounding_box_center(instance),
    ]:
        if point is not None:
            candidate_points.append(point)

    for point in candidate_points:
        room = try_get_room_from_point(point, phases, rooms)
        if room is not None:
            return room

    link_contexts = get_link_room_contexts()
    for point in candidate_points:
        room = try_get_room_from_links(point, link_contexts)
        if room is not None:
            return room

    return None


def get_room_number(instance):
    room = find_room_for_instance(instance)
    if room is None:
        return u''
    try:
        number_param = room.get_Parameter(BuiltInParameter.ROOM_NUMBER)
        number = to_text(get_parameter_text(number_param)).strip()
        if number:
            return number
    except Exception:
        pass
    try:
        number = to_text(room.Number).strip()
        if number:
            return number
    except Exception:
        pass
    try:
        number_param = room.LookupParameter('Number') or room.LookupParameter(u'房间编号')
        return to_text(get_parameter_text(number_param)).strip()
    except Exception:
        return u''


def get_combo_text(combo):
    item = combo.SelectedItem
    if item is None:
        return u''
    if isinstance(item, ComboBoxItem):
        return to_text(item.Content)
    return to_text(item)


def normalize_part(value):
    return to_text(value).strip()


def build_base_code(station, room, scheme, discipline, type_segment):
    parts = [
        normalize_part(station),
        normalize_part(room),
        normalize_part(scheme),
        normalize_part(discipline),
        normalize_part(type_segment),
    ]
    return u'-'.join([x for x in parts if x])


def build_segmented_mark(station, room, discipline, device, number_text):
    parts = [
        normalize_part(station),
        normalize_part(room),
        normalize_part(discipline),
        normalize_part(device),
    ]
    base_code = u'-'.join([x for x in parts if x])
    number_value = normalize_part(number_text)
    if is_blank(number_value):
        raise ValueError(u'编号段为空，无法生成 Mark。')
    if base_code:
        return u'{}.{}'.format(base_code, number_value)
    return number_value


class ModelFamilyInstanceSelectionFilter(ISelectionFilter):
    def __init__(self, parameter_name):
        self.parameter_name = parameter_name

    def AllowElement(self, element):
        try:
            if not isinstance(element, FamilyInstance):
                return False
            category = element.Category
            if category is None:
                return False
            try:
                if to_text(category.CategoryType) != u'Model':
                    return False
            except Exception:
                pass
            return True
        except Exception:
            return False

    def AllowReference(self, reference, point):
        return False


class CandidateItem(INotifyPropertyChanged):
    def __init__(self, element_id, category, family_name, type_name, current_value, is_writable, storage_name):
        self.ElementIdValue = int(element_id)
        self.Category = category
        self.FamilyName = family_name
        self.TypeName = type_name
        self._room_number = u''
        self._current_value = current_value
        self._preview_value = u''
        self._status = u'待预览'
        self._message = u'已扫描，可参与预览。'
        self.IsWritable = is_writable
        self.StorageName = storage_name
        self._pc = None

    def add_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Combine(self._pc, value)

    def remove_PropertyChanged(self, value):
        self._pc = EventHandler[PropertyChangedEventArgs].Remove(self._pc, value)

    def on_property_changed(self, name):
        if self._pc is not None:
            self._pc(self, PropertyChangedEventArgs(name))

    @property
    def RoomNumber(self):
        return self._room_number

    @RoomNumber.setter
    def RoomNumber(self, value):
        self._room_number = to_text(value)
        self.on_property_changed('RoomNumber')

    @property
    def CurrentValue(self):
        return self._current_value

    @CurrentValue.setter
    def CurrentValue(self, value):
        self._current_value = to_text(value)
        self.on_property_changed('CurrentValue')

    @property
    def PreviewValue(self):
        return self._preview_value

    @PreviewValue.setter
    def PreviewValue(self, value):
        self._preview_value = to_text(value)
        self.on_property_changed('PreviewValue')

    @property
    def Status(self):
        return self._status

    @Status.setter
    def Status(self, value):
        self._status = to_text(value)
        self.on_property_changed('Status')

    @property
    def Message(self):
        return self._message

    @Message.setter
    def Message(self, value):
        self._message = to_text(value)
        self.on_property_changed('Message')


class SelectionNumberingOptionsWindow(forms.WPFWindow):
    def __init__(self, xaml_file, selected_items, defaults, theme_context):
        forms.WPFWindow.__init__(self, xaml_file)
        self.theme_context = theme_context
        self.result = None
        self.selected_items = list(selected_items)
        self._refreshing_filters = False
        self.all_categories = sorted(set([item.Category for item in self.selected_items]))
        self.all_families = sorted(set([item.FamilyName for item in self.selected_items]))
        self.all_types = sorted(set([item.TypeName for item in self.selected_items]))
        self.apply_theme()
        self._refresh_filter_lists()
        self.StationTextBox.Text = normalize_part(defaults.get('station'))
        self.RoomTextBox.Text = normalize_part(defaults.get('room'))
        self.DisciplineTextBox.Text = normalize_part(defaults.get('discipline'))
        self.DeviceTextBox.Text = normalize_part(defaults.get('device'))
        self.StartNumberTextBox.Text = normalize_part(defaults.get('start'))
        self.SequenceWidthTextBox.Text = normalize_part(defaults.get('width'))
        self._update_summary()

    def apply_theme(self):
        palette = DARK_THEME if self.theme_context["is_dark"] else LIGHT_THEME
        for key, value in palette.items():
            self.Resources[key + 'Brush'] = brush_from_hex(value)
        self.Background = self.Resources['WindowBgBrush']

    def _get_selected_texts(self, list_box):
        values = []
        try:
            for item in list_box.SelectedItems:
                text_value = normalize_part(item)
                if text_value:
                    values.append(text_value)
        except Exception:
            pass
        return values

    def _filter_values_by_keyword(self, values, keyword):
        keyword = normalize_part(keyword).lower()
        if not keyword:
            return list(values)
        return [value for value in values if keyword in value.lower()]

    def _set_list_items_preserving_selection(self, list_box, values):
        selected = set(self._get_selected_texts(list_box))
        list_box.ItemsSource = values
        try:
            list_box.SelectedItems.Clear()
            for value in values:
                if value in selected:
                    list_box.SelectedItems.Add(value)
        except Exception:
            pass

    def _refresh_filter_lists(self):
        self._refreshing_filters = True
        try:
            self._set_list_items_preserving_selection(
                self.CategoryListBox,
                self._filter_values_by_keyword(self.all_categories, self.CategoryKeywordTextBox.Text)
            )
            self._set_list_items_preserving_selection(
                self.FamilyListBox,
                self._filter_values_by_keyword(self.all_families, self.FamilyKeywordTextBox.Text)
            )
            self._set_list_items_preserving_selection(
                self.TypeListBox,
                self._filter_values_by_keyword(self.all_types, self.TypeKeywordTextBox.Text)
            )
        finally:
            self._refreshing_filters = False

    def _get_filters(self):
        return {
            'categories': self._get_selected_texts(self.CategoryListBox),
            'families': self._get_selected_texts(self.FamilyListBox),
            'types': self._get_selected_texts(self.TypeListBox),
            'category_keyword': normalize_part(self.CategoryKeywordTextBox.Text).lower(),
            'family_keyword': normalize_part(self.FamilyKeywordTextBox.Text).lower(),
            'type_keyword': normalize_part(self.TypeKeywordTextBox.Text).lower(),
        }

    def _item_matches_filters(self, item, filters):
        categories = filters.get('categories') or []
        if categories and item.Category not in categories:
            return False
        families = filters.get('families') or []
        if families and item.FamilyName not in families:
            return False
        types = filters.get('types') or []
        if types and item.TypeName not in types:
            return False
        category_keyword = filters.get('category_keyword')
        if category_keyword and category_keyword not in item.Category.lower():
            return False
        family_keyword = filters.get('family_keyword')
        if family_keyword and family_keyword not in item.FamilyName.lower():
            return False
        type_keyword = filters.get('type_keyword')
        if type_keyword and type_keyword not in item.TypeName.lower():
            return False
        return True

    def _get_matching_items(self):
        filters = self._get_filters()
        return [item for item in self.selected_items if self._item_matches_filters(item, filters)]

    def _get_width(self):
        raw = normalize_part(self.SequenceWidthTextBox.Text)
        if is_blank(raw):
            return 3
        try:
            width = int(raw)
        except Exception:
            raise ValueError(u'编号位数必须是整数，当前为：{}'.format(raw))
        if width <= 0:
            raise ValueError(u'编号位数必须大于 0，当前为：{}'.format(raw))
        if width > 8:
            raise ValueError(u'编号位数不应大于 8，当前为：{}'.format(raw))
        return width

    def _get_start(self):
        raw = normalize_part(self.StartNumberTextBox.Text)
        if is_blank(raw):
            return 1
        try:
            start = int(raw)
        except Exception:
            raise ValueError(u'起始编号必须是整数，当前为：{}'.format(raw))
        if start <= 0:
            raise ValueError(u'起始编号必须大于 0，当前为：{}'.format(raw))
        return start

    def _build_sample(self):
        width = self._get_width()
        start = self._get_start()
        number_text = str(start).zfill(width)
        return build_segmented_mark(
            self.StationTextBox.Text,
            self.RoomTextBox.Text,
            self.DisciplineTextBox.Text,
            self.DeviceTextBox.Text,
            number_text
        )

    def _update_summary(self):
        count = len(self._get_matching_items())
        try:
            sample = self._build_sample()
        except Exception as ex:
            sample = u'示例无法生成：{}'.format(to_text(ex))
        self.CountTextBlock.Text = u'筛选命中 {} / {} 个实例'.format(count, len(self.selected_items))
        self.SampleTextBlock.Text = sample

    def AnyInput_Changed(self, sender, e):
        self._update_summary()

    def FilterInput_Changed(self, sender, e):
        self._refresh_filter_lists()
        self._update_summary()

    def FilterSelection_Changed(self, sender, e):
        if self._refreshing_filters:
            return
        self._update_summary()

    def Confirm_Click(self, sender, e):
        try:
            width = self._get_width()
            start = self._get_start()
            sample = self._build_sample()
        except Exception as ex:
            forms.alert(to_text(ex), title=u'输入不正确')
            return
        if not self._get_matching_items():
            forms.alert(u'当前筛选条件没有命中任何框选实例，请调整类别、族名或类型名关键字。', title=u'筛选结果为空')
            return

        self.result = {
            'categories': self._get_selected_texts(self.CategoryListBox),
            'families': self._get_selected_texts(self.FamilyListBox),
            'types': self._get_selected_texts(self.TypeListBox),
            'category_keyword': normalize_part(self.CategoryKeywordTextBox.Text),
            'family_keyword': normalize_part(self.FamilyKeywordTextBox.Text),
            'type_keyword': normalize_part(self.TypeKeywordTextBox.Text),
            'station': normalize_part(self.StationTextBox.Text),
            'room': normalize_part(self.RoomTextBox.Text),
            'discipline': normalize_part(self.DisciplineTextBox.Text),
            'device': normalize_part(self.DeviceTextBox.Text),
            'start': start,
            'width': width,
            'sample': sample,
        }
        self.DialogResult = True
        self.Close()

    def Cancel_Click(self, sender, e):
        self.result = None
        self.DialogResult = False
        self.Close()


class MarkBatchWindow(forms.WPFWindow):
    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file)
        self.theme_context = get_omnimetro_theme_context()
        self.apply_theme()
        self.items = []
        self.visible_items = ObservableCollection[CandidateItem]()
        self.ItemsDataGrid.ItemsSource = self.visible_items
        self.log_lines = []
        self.CategoryComboBox.ItemsSource = [u'全部']
        self.CategoryComboBox.SelectedIndex = 0
        self._write_log(u'请输入目标参数名，点击“扫描目标实例”开始。')

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

    def _reset_visible_items(self, new_items):
        self.visible_items.Clear()
        for item in new_items:
            self.visible_items.Add(item)

    def _remove_items_from_preview(self, target_items):
        if not target_items:
            return 0
        remove_ids = set([item.ElementIdValue for item in target_items])
        self.items = [item for item in self.items if item.ElementIdValue not in remove_ids]
        remaining_visible = [item for item in self.visible_items if item.ElementIdValue not in remove_ids]
        self._reset_visible_items(remaining_visible)
        self._update_categories()
        return len(remove_ids)

    def _get_selected_preview_items(self):
        selected = []
        try:
            for item in self.ItemsDataGrid.SelectedItems:
                if isinstance(item, CandidateItem):
                    selected.append(item)
        except Exception:
            pass
        if selected:
            return selected
        try:
            item = self.ItemsDataGrid.SelectedItem
            if isinstance(item, CandidateItem):
                return [item]
        except Exception:
            pass
        return []

    def _get_target_parameter_name(self):
        return normalize_part(self.TargetParameterTextBox.Text)

    def _update_categories(self):
        category_names = [u'全部'] + sorted(set([item.Category for item in self.items]))
        self.CategoryComboBox.ItemsSource = category_names
        self.CategoryComboBox.SelectedIndex = 0

    def _create_candidate_item(self, instance, parameter_name):
        try:
            category = instance.Category
        except Exception:
            category = None
        if category is None:
            return None
        try:
            if to_text(category.CategoryType) != u'Model':
                return None
        except Exception:
            pass

        try:
            param = instance.LookupParameter(parameter_name)
        except Exception:
            param = None
        if param is None:
            return None

        symbol = get_symbol(instance)
        family_name = get_family_name(instance, symbol)
        type_name = get_symbol_name(instance, symbol)
        current_value = get_parameter_text(param)
        storage_name = to_text(param.StorageType)
        return CandidateItem(
            instance.Id.IntegerValue,
            to_text(category.Name),
            family_name,
            type_name,
            current_value,
            not param.IsReadOnly,
            storage_name
        )

    def _collect_candidates(self, parameter_name):
        candidates = []
        total_instances = 0
        for instance in FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType():
            total_instances += 1
            item = self._create_candidate_item(instance, parameter_name)
            if item is not None:
                candidates.append(item)
        return candidates, total_instances

    def _get_filtered_items(self):
        category = get_combo_text(self.CategoryComboBox)
        family_keyword = normalize_part(self.FamilyFilterTextBox.Text).lower()
        type_keyword = normalize_part(self.TypeFilterTextBox.Text).lower()

        result = []
        for item in self.items:
            if category and category != u'全部' and item.Category != category:
                continue
            if family_keyword and family_keyword not in item.FamilyName.lower():
                continue
            if type_keyword and type_keyword not in item.TypeName.lower():
                continue
            result.append(item)
        return result

    def _apply_filter(self):
        filtered = self._get_filtered_items()
        self._reset_visible_items(filtered)
        self._set_summary(u'筛选结果：{0} / {1} 个实例'.format(len(filtered), len(self.items)))
        self._write_log(u'已应用筛选：当前显示 {0} 个实例。'.format(len(filtered)))

    def _get_type_segment(self, instance, item):
        mode = get_combo_text(self.TypeSourceComboBox)
        source_value = normalize_part(self.TypeSourceValueTextBox.Text)
        symbol = get_symbol(instance)

        if mode == u'类型名称':
            return normalize_part(item.TypeName)
        if mode == u'族名称':
            return normalize_part(item.FamilyName)
        if mode == u'固定文本':
            return source_value
        if mode == u'类型参数':
            if is_blank(source_value):
                raise ValueError(u'类型段来源选择了“类型参数”，但没有填写参数名。')
            if symbol is None:
                raise ValueError(u'未找到元素类型，无法读取类型参数。')
            param = symbol.LookupParameter(source_value)
            if param is None:
                raise ValueError(u'类型参数“{}”不存在。'.format(source_value))
            value = normalize_part(get_parameter_text(param))
            if is_blank(value):
                raise ValueError(u'类型参数“{}”为空。'.format(source_value))
            return value
        if mode == u'实例参数':
            if is_blank(source_value):
                raise ValueError(u'类型段来源选择了“实例参数”，但没有填写参数名。')
            param = instance.LookupParameter(source_value)
            if param is None:
                raise ValueError(u'实例参数“{}”不存在。'.format(source_value))
            value = normalize_part(get_parameter_text(param))
            if is_blank(value):
                raise ValueError(u'实例参数“{}”为空。'.format(source_value))
            return value

        raise ValueError(u'未识别的类型段来源：{}'.format(mode))

    def _get_sequence_width(self):
        raw = normalize_part(self.SequenceWidthTextBox.Text)
        if is_blank(raw):
            return 4
        try:
            width = int(raw)
        except Exception:
            raise ValueError(u'序号位数必须是整数，当前为：{}'.format(raw))
        if width <= 0:
            raise ValueError(u'序号位数必须大于 0，当前为：{}'.format(raw))
        if width > 8:
            raise ValueError(u'序号位数不应大于 8，当前为：{}'.format(raw))
        return width

    def _get_sequence_start(self, raw_value):
        raw = normalize_part(raw_value)
        if is_blank(raw):
            return 1
        try:
            start = int(raw)
        except Exception:
            raise ValueError(u'起始编号必须是整数，当前为：{}'.format(raw))
        if start <= 0:
            raise ValueError(u'起始编号必须大于 0，当前为：{}'.format(raw))
        return start

    def _generate_category_sequence_preview(self, target_items, sequence_width, start_number):
        grouped = {}
        fail_count = 0
        preview_ok = 0

        for item in target_items:
            item.RoomNumber = u''
            item.PreviewValue = u''
            try:
                if not item.IsWritable:
                    raise ValueError(u'目标参数存在但为只读，无法写入。')
                if item.StorageName != u'String':
                    raise ValueError(u'目标参数存储类型为 {}，当前版本只支持字符串参数。'.format(item.StorageName))

                instance = doc.GetElement(ElementId(item.ElementIdValue))
                if instance is None:
                    raise ValueError(u'未找到对应实例，可能已被删除。')
                get_view_sort_key(instance, doc.ActiveView)

                grouped.setdefault(item.Category, []).append(item)
                item.Status = u'待编号'
                item.Message = u'已按类别纳入编号，等待分配序号。'
            except Exception as ex:
                item.Status = u'失败'
                item.Message = to_text(ex)
                fail_count += 1

        for category, group_items in grouped.items():
            ordered_items = sort_items_from_left_to_right_top_to_bottom(group_items, doc.ActiveView)
            for offset, item in enumerate(ordered_items):
                number_value = start_number + offset
                item.PreviewValue = str(number_value).zfill(sequence_width)
                item.Status = u'待写入'
                item.Message = u'按类别“{}”从左到右、从上到下生成编号。'.format(category)
                preview_ok += 1

        return preview_ok, fail_count

    def _generate_segmented_selection_preview(self, target_items, options):
        fail_count = 0
        preview_ok = 0

        for item in target_items:
            item.RoomNumber = normalize_part(options.get('room'))
            item.PreviewValue = u''
            try:
                if not item.IsWritable:
                    raise ValueError(u'目标参数存在但为只读，无法写入。')
                if item.StorageName != u'String':
                    raise ValueError(u'目标参数存储类型为 {}，当前版本只支持字符串参数。'.format(item.StorageName))

                instance = doc.GetElement(ElementId(item.ElementIdValue))
                if instance is None:
                    raise ValueError(u'未找到对应实例，可能已被删除。')
                get_view_sort_key(instance, doc.ActiveView)

                item.Status = u'待编号'
                item.Message = u'已纳入框选区域编号，等待分配序号。'
            except Exception as ex:
                item.Status = u'失败'
                item.Message = to_text(ex)
                fail_count += 1

        valid_items = [item for item in target_items if item.Status == u'待编号']
        ordered_items = sort_items_from_left_to_right_top_to_bottom(valid_items, doc.ActiveView) if valid_items else []
        start_number = int(options.get('start'))
        sequence_width = int(options.get('width'))

        for offset, item in enumerate(ordered_items):
            number_text = str(start_number + offset).zfill(sequence_width)
            try:
                item.PreviewValue = build_segmented_mark(
                    options.get('station'),
                    options.get('room'),
                    options.get('discipline'),
                    options.get('device'),
                    number_text
                )
                item.Status = u'待写入'
                item.Message = u'框选区域按当前视图从左到右、从上到下生成编号。'
                preview_ok += 1
            except Exception as ex:
                item.Status = u'失败'
                item.Message = to_text(ex)
                fail_count += 1

        return preview_ok, fail_count

    def _generate_preview(self):
        if not self.items:
            forms.alert(u'请先扫描目标实例。', title=u'无法预览')
            return

        target_items = self._get_filtered_items()
        if not target_items:
            forms.alert(u'当前筛选结果为空。请先调整筛选条件。', title=u'无法预览')
            return

        parameter_name = self._get_target_parameter_name()
        if is_blank(parameter_name):
            forms.alert(u'目标参数名不能为空。', title=u'输入不完整')
            return

        try:
            sequence_width = self._get_sequence_width()
        except Exception as ex:
            forms.alert(to_text(ex), title=u'输入不正确')
            return

        preview_ok, fail_count = self._generate_category_sequence_preview(target_items, sequence_width, 1)

        self._reset_visible_items(target_items)
        self._set_summary(u'预览完成：成功 {0}，失败 {1}。'.format(preview_ok, fail_count))
        self._write_log(u'预览完成：共处理 {0} 个实例，成功生成 {1} 个编码，失败 {2} 个。'.format(
            len(target_items), preview_ok, fail_count
        ))

    def Scan_Click(self, sender, e):
        parameter_name = self._get_target_parameter_name()
        if is_blank(parameter_name):
            forms.alert(u'请先填写目标参数名，例如 Mark。', title=u'输入不完整')
            return

        candidates, total_instances = self._collect_candidates(parameter_name)
        self.items = candidates
        self._update_categories()
        self._reset_visible_items(candidates)

        self._set_summary(u'扫描完成：在 {0} 个族实例中找到 {1} 个包含参数“{2}”的实例。'.format(
            total_instances, len(candidates), parameter_name
        ))
        self._write_log(u'扫描完成：共检查 {0} 个族实例，命中 {1} 个包含参数“{2}”的实例。'.format(
            total_instances, len(candidates), parameter_name
        ))

        if not candidates:
            forms.alert(u'未找到包含参数“{}”的族实例。'.format(parameter_name), title=u'扫描结果')

    def ApplyFilter_Click(self, sender, e):
        if not self.items:
            forms.alert(u'请先扫描目标实例。', title=u'无法筛选')
            return
        self._apply_filter()

    def ClearFilter_Click(self, sender, e):
        self.FamilyFilterTextBox.Text = u''
        self.TypeFilterTextBox.Text = u''
        if self.CategoryComboBox.Items.Count > 0:
            self.CategoryComboBox.SelectedIndex = 0
        if self.items:
            self._reset_visible_items(self.items)
            self._set_summary(u'已清空筛选：当前显示全部 {0} 个实例。'.format(len(self.items)))
            self._write_log(u'已清空筛选。')

    def ClearPreview_Click(self, sender, e):
        if not self.items and self.visible_items.Count == 0:
            forms.alert(u'预览列表已经为空。', title=u'无需清空')
            return
        confirmed = forms.alert(
            u'确认清空当前所有预览列表记录？此操作不会修改模型参数。',
            title=u'清空预览列表',
            yes=True,
            no=True
        )
        if not confirmed:
            return
        removed_count = len(self.items)
        self.items = []
        self.visible_items.Clear()
        self._update_categories()
        self._set_summary(u'已清空预览列表。')
        self._write_log(u'已清空预览列表：删除 {0} 条记录，模型参数未修改。'.format(removed_count))

    def DeletePreviewRows_Click(self, sender, e):
        selected_items = self._get_selected_preview_items()
        if not selected_items:
            forms.alert(u'请先在预览列表中选择要删除的记录。', title=u'没有选中记录')
            return
        removed_count = self._remove_items_from_preview(selected_items)
        self._set_summary(u'已删除 {0} 条预览记录，当前剩余 {1} 条。'.format(removed_count, self.visible_items.Count))
        self._write_log(u'已删除 {0} 条预览记录，模型参数未修改。'.format(removed_count))

    def ItemsDataGrid_KeyDown(self, sender, e):
        try:
            if e.Key != Key.Delete:
                return
        except Exception:
            return
        selected_items = self._get_selected_preview_items()
        if not selected_items:
            return
        removed_count = self._remove_items_from_preview(selected_items)
        self._set_summary(u'已删除 {0} 条预览记录，当前剩余 {1} 条。'.format(removed_count, self.visible_items.Count))
        self._write_log(u'已通过 Delete 键删除 {0} 条预览记录，模型参数未修改。'.format(removed_count))
        try:
            e.Handled = True
        except Exception:
            pass

    def ItemsDataGrid_MouseDoubleClick(self, sender, e):
        try:
            item = self.ItemsDataGrid.SelectedItem
            if not isinstance(item, CandidateItem):
                return
            element_id = ElementId(item.ElementIdValue)
            instance = doc.GetElement(element_id)
            if instance is None:
                raise ValueError(u'未找到对应实例，可能已被删除。')

            selected_ids = List[ElementId]()
            selected_ids.Add(element_id)
            uidoc.Selection.SetElementIds(selected_ids)
            uidoc.ShowElements(element_id)

            self.Hide()
            try:
                uidoc.Selection.PickObject(
                    ObjectType.Element,
                    u'已放大并选中该族实例。按 Esc 返回 Mark 编码预览表格。'
                )
            except OperationCanceledException:
                pass
            finally:
                self.Show()
                try:
                    self.Activate()
                except Exception:
                    pass
                try:
                    self.ItemsDataGrid.SelectedItem = item
                    self.ItemsDataGrid.ScrollIntoView(item)
                except Exception:
                    pass
        except Exception as ex:
            try:
                self.Show()
                self.Activate()
            except Exception:
                pass
            detail = to_text(ex)
            self._write_log(u'定位预览记录失败：' + detail)
            forms.alert(u'定位预览记录失败：\n{}'.format(detail), title=u'定位失败')

    def Preview_Click(self, sender, e):
        self._generate_preview()

    def RenumberSelection_Click(self, sender, e):
        parameter_name = self._get_target_parameter_name()
        if is_blank(parameter_name):
            forms.alert(u'请先填写目标参数名，例如 Mark。', title=u'输入不完整')
            return

        prompt = u'框选需要重新编号的模型族实例。'
        selected_elements = None
        try:
            self.Hide()
            selected_elements = uidoc.Selection.PickElementsByRectangle(
                ModelFamilyInstanceSelectionFilter(parameter_name),
                prompt
            )
        except OperationCanceledException:
            self.Show()
            self._write_log(u'已取消框选区域重编号。')
            return
        except Exception as ex:
            self.Show()
            detail = to_text(ex)
            self._write_log(u'框选区域重编号失败：' + detail)
            forms.alert(u'框选区域重编号失败：\n{}'.format(detail), title=u'选择失败')
            return
        finally:
            try:
                self.Show()
            except Exception:
                pass

        selected_elements_list = list(selected_elements)
        selected_count = len(selected_elements_list)
        if selected_count == 0:
            forms.alert(u'框选范围内没有模型族实例。', title=u'选择结果')
            return

        items = []
        skipped_count = 0
        seen_ids = set()
        for element in selected_elements_list:
            try:
                element_id = element.Id.IntegerValue
            except Exception:
                skipped_count += 1
                continue
            if element_id in seen_ids:
                continue
            seen_ids.add(element_id)
            item = self._create_candidate_item(element, parameter_name)
            if item is None:
                skipped_count += 1
                continue
            items.append(item)

        if not items:
            forms.alert(u'框选范围内没有包含参数“{}”的模型族实例。'.format(parameter_name), title=u'选择结果')
            self._write_log(u'框选完成：选中 {0} 个模型族实例，但没有实例包含参数“{1}”。'.format(
                selected_count, parameter_name
            ))
            return

        defaults = {
            'station': normalize_part(self.StationCodeTextBox.Text),
            'room': normalize_part(self.RoomCodeTextBox.Text),
            'discipline': normalize_part(self.DisciplineCodeTextBox.Text),
            'device': normalize_part(self.TypeSourceValueTextBox.Text),
            'start': u'1',
            'width': normalize_part(self.SequenceWidthTextBox.Text) or u'4',
        }
        options_window = SelectionNumberingOptionsWindow(
            SELECTION_OPTIONS_XAML_FILE,
            items,
            defaults,
            self.theme_context
        )
        try:
            options_window.Owner = self
        except Exception:
            pass
        dialog_result = options_window.ShowDialog()
        if not dialog_result or options_window.result is None:
            self._write_log(u'已取消框选区域编号设置。')
            return

        options = options_window.result
        selected_categories = options.get('categories') or []
        selected_families = options.get('families') or []
        selected_types = options.get('types') or []
        category_keyword = normalize_part(options.get('category_keyword')).lower()
        family_keyword = normalize_part(options.get('family_keyword')).lower()
        type_keyword = normalize_part(options.get('type_keyword')).lower()
        target_items = []
        for item in items:
            if selected_categories and item.Category not in selected_categories:
                continue
            if selected_families and item.FamilyName not in selected_families:
                continue
            if selected_types and item.TypeName not in selected_types:
                continue
            if category_keyword and category_keyword not in item.Category.lower():
                continue
            if family_keyword and family_keyword not in item.FamilyName.lower():
                continue
            if type_keyword and type_keyword not in item.TypeName.lower():
                continue
            target_items.append(item)

        if not target_items:
            forms.alert(u'当前处理范围内没有可编号实例。', title=u'无法生成预览')
            return

        preview_ok, fail_count = self._generate_segmented_selection_preview(target_items, options)
        self.items = items
        self._update_categories()
        self._reset_visible_items(target_items)

        self._set_summary(u'框选重编号预览完成：成功 {0}，失败 {1}，跳过 {2}。'.format(preview_ok, fail_count, skipped_count))
        filter_text = u'类别选择：{0}；族名选择：{1}；类型名选择：{2}；类别关键字：{3}；族名关键字：{4}；类型名关键字：{5}'.format(
            u'、'.join(selected_categories) if selected_categories else u'不限',
            u'、'.join(selected_families) if selected_families else u'不限',
            u'、'.join(selected_types) if selected_types else u'不限',
            normalize_part(options.get('category_keyword')) or u'无',
            normalize_part(options.get('family_keyword')) or u'无',
            normalize_part(options.get('type_keyword')) or u'无'
        )
        self._write_log(u'框选重编号预览完成：选中 {0} 个模型族实例，包含目标参数 {1} 个，筛选后 {2} 个，成功 {3}，失败 {4}，跳过 {5}。{6}。示例：{7}'.format(
            selected_count, len(items), len(target_items), preview_ok, fail_count, skipped_count, filter_text, options['sample']
        ))

    def Write_Click(self, sender, e):
        if self.visible_items.Count == 0:
            forms.alert(u'当前没有可见实例。请先扫描并筛选。', title=u'无法写入')
            return

        target_parameter_name = self._get_target_parameter_name()
        if is_blank(target_parameter_name):
            forms.alert(u'目标参数名不能为空。', title=u'无法写入')
            return

        writable_items = [item for item in self.visible_items if item.Status == u'待写入' and not is_blank(item.PreviewValue)]
        if not writable_items:
            forms.alert(u'当前没有已生成预览且可写入的实例。请先执行“预览编码”。', title=u'无法写入')
            return

        tx = Transaction(doc, u'Mark编码批量填写')
        success_count = 0
        fail_count = 0
        tx_started = False

        try:
            tx.Start()
            tx_started = True
            for item in writable_items:
                try:
                    instance = doc.GetElement(ElementId(item.ElementIdValue))
                    if instance is None:
                        raise ValueError(u'未找到对应实例，可能已被删除。')

                    param = instance.LookupParameter(target_parameter_name)
                    if param is None:
                        raise ValueError(u'目标参数“{}”不存在。'.format(target_parameter_name))
                    if param.IsReadOnly:
                        raise ValueError(u'目标参数为只读。')
                    if param.StorageType != StorageType.String:
                        raise ValueError(u'目标参数存储类型为 {}，无法写入字符串编码。'.format(to_text(param.StorageType)))

                    param.Set(item.PreviewValue)
                    item.CurrentValue = item.PreviewValue
                    item.Status = u'成功'
                    item.Message = u'编码已写入。'
                    success_count += 1
                except Exception as ex:
                    item.Status = u'失败'
                    item.Message = to_text(ex)
                    fail_count += 1
                    LOGGER.exception('Mark编码写入失败: %s -> %s', item.ElementIdValue, item.PreviewValue)
            tx.Commit()
        except Exception as ex:
            if tx_started:
                tx.RollBack()
            detail = to_text(ex)
            self._write_log(u'事务执行失败：' + detail)
            forms.alert(u'批量写入事务执行失败：\n{}'.format(detail), title=u'写入失败')
            return

        self._set_summary(u'写入完成：成功 {0}，失败 {1}。'.format(success_count, fail_count))
        self._write_log(u'写入完成：成功 {0}，失败 {1}。'.format(success_count, fail_count))
        for item in writable_items:
            if item.Status == u'失败':
                self._write_log(u'失败 - [{0}] {1}/{2}：{3}'.format(
                    item.Category, item.FamilyName, item.TypeName, item.Message
                ))

        if fail_count:
            forms.alert(u'写入完成：成功 {0}，失败 {1}。\n\n详细失败原因已写入下方日志。'.format(success_count, fail_count), title=u'执行结束')
        else:
            forms.alert(u'写入完成：成功 {0}，失败 {1}。'.format(success_count, fail_count), title=u'执行结束')

    def Close_Click(self, sender, e):
        self.Close()


def main():
    window = MarkBatchWindow(XAML_FILE)
    window.ShowDialog()


if __name__ == '__main__':
    main()
