# -*- coding: utf-8 -*-
"""Core geometry and placement helpers for LinerMaster."""

from __future__ import division

import math

from System import Guid
from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    BuiltInCategory,
    CategoryType,
    CurveElement,
    CurveLoop,
    DirectShape,
    ElementId,
    ElementTransformUtils,
    FamilyInstance,
    FamilyPlacementType,
    FamilySymbol,
    FilteredElementCollector,
    GeometryCreationUtilities,
    GeometryObject,
    Level,
    Line,
    LocationCurve,
    SolidOptions,
    Transform,
    XYZ,
)
from Autodesk.Revit.DB.ExtensibleStorage import (
    AccessLevel,
    Entity,
    ExtensibleStorageFilter,
    Schema,
    SchemaBuilder,
)
from Autodesk.Revit.DB.Structure import StructuralType

try:
    unicode
except NameError:
    unicode = str


MM_PER_FOOT = 304.8
M_PER_FOOT = 0.3048
GEOM_TOLERANCE = 1e-9

WORLD_X = XYZ(1.0, 0.0, 0.0)
WORLD_Y = XYZ(0.0, 1.0, 0.0)
WORLD_Z = XYZ(0.0, 0.0, 1.0)
TRACKING_SCHEMA_GUID = Guid("8D580A5C-3B5D-4A6B-BB3A-8FDFD157C7D9")
TRACKING_VENDOR_ID = "OPENAI"
TRACKING_APP_ID = "LinerMaster"

SUPPORTED_PLACEMENT_TYPES = set([
    FamilyPlacementType.OneLevelBased,
    FamilyPlacementType.TwoLevelsBased,
])


class CurveSelection(object):
    def __init__(self, curve, description, source_element_id, source_kind):
        self.curve = curve
        self.description = description
        self.source_element_id = source_element_id
        self.source_kind = source_kind


class SymbolInfo(object):
    def __init__(self, symbol_id, family_name, type_name, category_name, placement_type, source_instance_id=None):
        self.symbol_id = symbol_id
        self.family_name = family_name
        self.type_name = type_name
        self.category_name = category_name
        self.placement_type = placement_type
        self.source_instance_id = source_instance_id
        self.display_name = u'{0} | {1} | {2} | {3}'.format(
            category_name,
            family_name,
            type_name,
            get_placement_type_label(placement_type),
        )


class ProfileFamilySymbolInfo(object):
    def __init__(self, symbol_id, family_name, type_name):
        self.symbol_id = symbol_id
        self.family_name = family_name
        self.type_name = type_name
        self.display_name = u'{0} | {1}'.format(family_name, type_name)


class ProfileSelection(object):
    def __init__(self, curve_loop, description, source_element_ids):
        self.curve_loop = curve_loop
        self.description = description
        self.source_element_ids = source_element_ids


class PlacementItem(object):
    def __init__(self, index, distance_ft, base_point, target_point, tangent, horizontal, vertical):
        self.index = index
        self.distance_ft = distance_ft
        self.base_point = base_point
        self.target_point = target_point
        self.tangent = tangent
        self.horizontal = horizontal
        self.vertical = vertical


class LayoutResult(object):
    def __init__(self):
        self.items = []
        self.requested_count = 0
        self.resolved_count = 0
        self.max_count = 0
        self.curve_length_ft = 0.0
        self.coverage_ft = 0.0
        self.spacing_ft = 0.0
        self.overflow_ft = 0.0
        self.valid = False
        self.message = u''


class GeneratedElementInfo(object):
    def __init__(self, element, mode, source_label, config_id, created_seconds, category_name=None):
        self.element = element
        self.mode = mode
        self.source_label = source_label
        self.config_id = config_id
        self.created_seconds = created_seconds
        self.category_name = category_name or get_element_category_name(element)


def mm_to_ft(value_mm):
    return value_mm / MM_PER_FOOT


def ft_to_mm(value_ft):
    return value_ft * MM_PER_FOOT


def m_to_ft(value_m):
    return value_m / M_PER_FOOT


def ft_to_m(value_ft):
    return value_ft * M_PER_FOOT


def is_curve_element(element):
    if element is None:
        return False
    if isinstance(element, CurveElement):
        return True
    location = getattr(element, 'Location', None)
    return isinstance(location, LocationCurve)


def clamp(value, low, high):
    return max(low, min(high, value))


def safe_normalize(vector):
    if vector is None:
        return None
    try:
        if vector.GetLength() <= GEOM_TOLERANCE:
            return None
        return vector.Normalize()
    except Exception:
        return None


def project_to_plane(vector, plane_normal):
    return vector.Subtract(plane_normal.Multiply(vector.DotProduct(plane_normal)))


def rotate_vector(vector, axis, angle):
    axis = safe_normalize(axis)
    if axis is None or abs(angle) <= GEOM_TOLERANCE:
        return vector
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    term_1 = vector.Multiply(cos_a)
    term_2 = axis.CrossProduct(vector).Multiply(sin_a)
    term_3 = axis.Multiply(axis.DotProduct(vector) * (1.0 - cos_a))
    return term_1.Add(term_2).Add(term_3)


def signed_angle_on_plane(from_vector, to_vector, plane_normal):
    from_projected = safe_normalize(project_to_plane(from_vector, plane_normal))
    to_projected = safe_normalize(project_to_plane(to_vector, plane_normal))
    if from_projected is None or to_projected is None:
        return 0.0
    dot_value = clamp(from_projected.DotProduct(to_projected), -1.0, 1.0)
    angle = math.acos(dot_value)
    cross_value = from_projected.CrossProduct(to_projected)
    if plane_normal.DotProduct(cross_value) < 0.0:
        angle *= -1.0
    return angle


def get_curve_length(curve):
    return curve.Length


def get_curve_from_reference(doc, reference):
    element = doc.GetElement(reference.ElementId)
    geometry_object = None
    if element is not None:
        try:
            geometry_object = element.GetGeometryObjectFromReference(reference)
        except Exception:
            geometry_object = None
    if geometry_object is not None and hasattr(geometry_object, 'AsCurve'):
        curve = geometry_object.AsCurve()
        description = u'几何边 | 元素 {0} | {1}'.format(
            element.Id.IntegerValue,
            curve.GetType().Name,
        )
        return CurveSelection(curve, description, element.Id, u'edge')
    return get_curve_from_element(element)


def get_curve_from_element(element):
    if element is None:
        raise ValueError(u'未选择到有效元素。')
    curve = None
    if isinstance(element, CurveElement):
        curve = element.GeometryCurve
    else:
        location = getattr(element, 'Location', None)
        if isinstance(location, LocationCurve):
            curve = location.Curve
    if curve is None:
        raise ValueError(u'所选元素不包含可用于布置的曲线。')
    description = u'曲线元素 | 元素 {0} | {1}'.format(
        element.Id.IntegerValue,
        curve.GetType().Name,
    )
    return CurveSelection(curve, description, element.Id, u'element')


def get_profile_from_references(doc, references):
    curves = []
    element_ids = []
    for reference in references:
        element = doc.GetElement(reference.ElementId)
        curve = None
        geometry_object = None
        if element is not None:
            try:
                geometry_object = element.GetGeometryObjectFromReference(reference)
            except Exception:
                geometry_object = None
        if geometry_object is not None and hasattr(geometry_object, 'AsCurve'):
            curve = geometry_object.AsCurve()
        else:
            curve = get_curve_from_element(element).curve
        if curve is None:
            raise ValueError(u'所选轮廓中包含无法识别的曲线。')
        curves.append(curve)
        if element is not None:
            element_ids.append(element.Id)

    curve_loop = build_closed_curve_loop(curves)
    description = u'封闭轮廓 | 元素数 {0} | 曲线段 {1}'.format(
        len(element_ids),
        len(curves),
    )
    return ProfileSelection(curve_loop, description, element_ids)


def get_profile_from_face_reference(doc, reference):
    element = doc.GetElement(reference.ElementId)
    if element is None:
        raise ValueError(u'未选择到有效的封闭图形面。')

    geometry_object = None
    try:
        geometry_object = element.GetGeometryObjectFromReference(reference)
    except Exception:
        geometry_object = None

    if geometry_object is None or not hasattr(geometry_object, 'GetEdgesAsCurveLoops'):
        raise ValueError(u'所选对象不是可用于放样的封闭图形面。')

    curve_loops = list(geometry_object.GetEdgesAsCurveLoops())
    if not curve_loops:
        raise ValueError(u'所选封闭图形面不包含可识别的轮廓。')

    outer_loop = get_longest_curve_loop(curve_loops)
    curve_loop = build_closed_curve_loop(get_curves_from_loop(outer_loop))
    description = u'面轮廓 | 元素 {0} | 曲线段 {1}'.format(
        element.Id.IntegerValue,
        get_curve_loop_segment_count(curve_loop),
    )
    return ProfileSelection(curve_loop, description, [element.Id])


def get_placement_type_label(placement_type):
    if placement_type == FamilyPlacementType.OneLevelBased:
        return u'单层基于标高'
    if placement_type == FamilyPlacementType.TwoLevelsBased:
        return u'双层基于标高'
    return unicode(placement_type)


def build_closed_curve_loop(curves):
    if not curves:
        raise ValueError(u'未选择任何轮廓曲线。')

    remaining = [curve.Clone() for curve in curves]
    ordered = [remaining.pop(0)]

    while remaining:
        end_point = ordered[-1].GetEndPoint(1)
        found_index = None
        found_curve = None
        for index, curve in enumerate(remaining):
            start_point = curve.GetEndPoint(0)
            close_to_start = end_point.DistanceTo(start_point) <= 1e-6
            if close_to_start:
                found_index = index
                found_curve = curve
                break
            end_point_curve = curve.GetEndPoint(1)
            close_to_end = end_point.DistanceTo(end_point_curve) <= 1e-6
            if close_to_end:
                found_index = index
                found_curve = curve.CreateReversed()
                break
        if found_index is None:
            raise ValueError(u'所选轮廓曲线无法首尾连接成封闭图形。')
        ordered.append(found_curve)
        remaining.pop(found_index)

    start_point = ordered[0].GetEndPoint(0)
    end_point = ordered[-1].GetEndPoint(1)
    if start_point.DistanceTo(end_point) > 1e-6:
        raise ValueError(u'所选轮廓未闭合，请检查曲线端点是否相连。')

    curve_loop = CurveLoop()
    for curve in ordered:
        curve_loop.Append(curve)

    try:
        if not curve_loop.HasPlane():
            raise ValueError(u'封闭轮廓必须共面。')
    except Exception:
        pass

    return curve_loop


def get_curves_from_loop(curve_loop):
    curves = []
    iterator = curve_loop.GetCurveLoopIterator()
    while iterator.MoveNext():
        curves.append(iterator.Current)
    return curves


def get_curve_loop_segment_count(curve_loop):
    return len(get_curves_from_loop(curve_loop))


def get_curve_loop_length(curve_loop):
    total_length = 0.0
    iterator = curve_loop.GetCurveLoopIterator()
    while iterator.MoveNext():
        total_length += iterator.Current.Length
    return total_length


def get_longest_curve_loop(curve_loops):
    longest_loop = None
    longest_length = -1.0
    for curve_loop in curve_loops:
        loop_length = get_curve_loop_length(curve_loop)
        if loop_length > longest_length:
            longest_loop = curve_loop
            longest_length = loop_length
    if longest_loop is None:
        raise ValueError(u'无法识别封闭图形的外轮廓。')
    return longest_loop


def get_model_symbol_infos(doc):
    collector = FilteredElementCollector(doc).OfClass(FamilySymbol)
    infos = []
    for symbol in collector:
        info = create_symbol_info(symbol)
        if info is not None:
            infos.append(info)
    infos.sort(key=lambda x: (
        x.category_name.lower(),
        x.family_name.lower(),
        x.type_name.lower(),
    ))
    return infos


def get_profile_family_symbol_infos(doc):
    collector = FilteredElementCollector(doc).OfClass(FamilySymbol)
    infos = []
    for symbol in collector:
        if not is_profile_family_symbol(symbol):
            continue
        infos.append(ProfileFamilySymbolInfo(
            symbol.Id.IntegerValue,
            symbol.Family.Name,
            get_symbol_type_name(symbol),
        ))
    infos.sort(key=lambda x: (x.family_name.lower(), x.type_name.lower()))
    return infos


def create_symbol_info(symbol, source_instance_id=None):
    if symbol is None:
        return None
    category = symbol.Category
    if category is None:
        return None
    if category.CategoryType != CategoryType.Model:
        return None
    placement_type = symbol.Family.FamilyPlacementType
    if placement_type not in SUPPORTED_PLACEMENT_TYPES:
        return None
    return SymbolInfo(
        symbol.Id.IntegerValue,
        symbol.Family.Name,
        get_symbol_type_name(symbol),
        category.Name,
        placement_type,
        source_instance_id=source_instance_id,
    )


def is_profile_family_symbol(symbol):
    if symbol is None:
        return False
    family = getattr(symbol, 'Family', None)
    if family is None or not getattr(family, 'IsEditable', False):
        return False

    categories = [
        getattr(symbol, 'Category', None),
        getattr(family, 'FamilyCategory', None),
    ]
    for category in categories:
        category_name = getattr(category, 'Name', None)
        if category_name and looks_like_profile_category_name(category_name):
            return True
    return False


def looks_like_profile_category_name(category_name):
    category_text = unicode(category_name or u'').strip().lower()
    return (u'profile' in category_text) or (u'轮廓' in category_text)


def get_symbol_info_from_instance(instance):
    if instance is None or not isinstance(instance, FamilyInstance):
        raise ValueError(u'所选元素不是族实例。')
    symbol = instance.Symbol
    info = create_symbol_info(symbol, source_instance_id=instance.Id.IntegerValue)
    if info is None:
        raise ValueError(
            u'所选实例的族类型不受支持。当前仅支持非宿主、可按点放置的模型族类型。'
        )
    return info


def get_symbol_type_name(symbol):
    try:
        symbol_name = symbol.Name
        if symbol_name:
            return symbol_name
    except Exception:
        pass
    name_parameter = symbol.LookupParameter(u'类型名称')
    if name_parameter and name_parameter.HasValue:
        return name_parameter.AsString()
    return u'<未命名类型>'


def get_default_level(doc, active_view):
    gen_level = getattr(active_view, 'GenLevel', None)
    if gen_level is not None:
        return gen_level

    level_id = getattr(active_view, 'LevelId', ElementId.InvalidElementId)
    if level_id != ElementId.InvalidElementId:
        level = doc.GetElement(level_id)
        if isinstance(level, Level):
            return level

    levels = list(FilteredElementCollector(doc).OfClass(Level))
    if not levels:
        raise ValueError(u'当前项目内没有可用标高，无法放置基于点的族。')
    levels.sort(key=lambda x: x.Elevation)
    return levels[0]


def get_profile_from_family_symbol(doc, symbol):
    if symbol is None:
        raise ValueError(u'未选择有效的轮廓族类型。')

    family = getattr(symbol, 'Family', None)
    if family is None or not getattr(family, 'IsEditable', False):
        raise ValueError(u'所选轮廓族不可编辑，无法提取放样截面。')

    family_doc = None
    try:
        family_doc = doc.EditFamily(family)
        set_family_doc_current_type(family_doc, get_symbol_type_name(symbol))
        family_doc.Regenerate()

        curves = []
        collector = FilteredElementCollector(family_doc).OfClass(CurveElement)
        for curve_element in collector:
            curve = getattr(curve_element, 'GeometryCurve', None)
            if curve is not None:
                curves.append(curve)

        if not curves:
            raise ValueError(u'轮廓族中没有可识别的闭合曲线。')

        curve_loop = build_closed_curve_loop(curves)
        description = u'轮廓族 | {0} | {1} | 曲线段 {2}'.format(
            family.Name,
            get_symbol_type_name(symbol),
            len(curves),
        )
        return ProfileSelection(curve_loop, description, [symbol.Id])
    finally:
        if family_doc is not None:
            try:
                family_doc.Close(False)
            except Exception:
                pass


def set_family_doc_current_type(family_doc, target_type_name):
    family_manager = getattr(family_doc, 'FamilyManager', None)
    if family_manager is None:
        return

    try:
        family_types = family_manager.Types
    except Exception:
        family_types = None
    if family_types is None:
        return

    try:
        iterator = family_types.ForwardIterator()
        iterator.Reset()
        while iterator.MoveNext():
            family_type = iterator.Current
            if family_type is None:
                continue
            if unicode(getattr(family_type, 'Name', u'')) == unicode(target_type_name or u''):
                family_manager.CurrentType = family_type
                return
    except Exception:
        return


def build_layout(curve, spacing_ft, requested_count, horizontal_offset_ft, vertical_offset_ft, start_distance_ft=0.0, end_distance_ft=None):
    layout = LayoutResult()
    layout.spacing_ft = spacing_ft
    layout.requested_count = requested_count
    layout.curve_length_ft = get_curve_length(curve)

    if spacing_ft <= GEOM_TOLERANCE:
        layout.message = u'间距必须大于 0。'
        return layout
    if layout.curve_length_ft <= GEOM_TOLERANCE:
        layout.message = u'所选曲线长度为 0。'
        return layout

    layout.max_count = int(math.floor((layout.curve_length_ft + GEOM_TOLERANCE) / spacing_ft)) + 1
    if requested_count and requested_count > 0:
        layout.resolved_count = requested_count
    else:
        layout.resolved_count = layout.max_count

    layout.coverage_ft = 0.0
    if layout.resolved_count > 1:
        layout.coverage_ft = spacing_ft * (layout.resolved_count - 1)
    layout.overflow_ft = layout.coverage_ft - layout.curve_length_ft

    if layout.resolved_count <= 0:
        layout.message = u'数量必须为正整数。'
        return layout

    if layout.overflow_ft > GEOM_TOLERANCE:
        layout.message = u'当前数量与间距组合会超出曲线长度，最大可布置数量为 {0}。'.format(layout.max_count)
        return layout

    for index in range(layout.resolved_count):
        distance_ft = start_distance_ft + spacing_ft * index
        if end_distance_ft is not None and distance_ft > end_distance_ft + GEOM_TOLERANCE:
            break
        frame = get_curve_frame(curve, distance_ft)
        target_point = frame['origin']
        if abs(horizontal_offset_ft) > GEOM_TOLERANCE:
            target_point = target_point.Add(frame['horizontal'].Multiply(horizontal_offset_ft))
        if abs(vertical_offset_ft) > GEOM_TOLERANCE:
            target_point = target_point.Add(frame['vertical'].Multiply(vertical_offset_ft))
        layout.items.append(PlacementItem(
            index + 1,
            distance_ft,
            frame['origin'],
            target_point,
            frame['tangent'],
            frame['horizontal'],
            frame['vertical'],
        ))

    layout.valid = True
    layout.message = u'预览已更新。'
    return layout


def get_curve_frame(curve, distance_ft):
    length_ft = get_curve_length(curve)
    if length_ft <= GEOM_TOLERANCE:
        raise ValueError(u'曲线长度为 0。')
    normalized_param = clamp(distance_ft / length_ft, 0.0, 1.0)
    derivatives = curve.ComputeDerivatives(normalized_param, True)
    origin = derivatives.Origin
    tangent = safe_normalize(derivatives.BasisX)
    if tangent is None:
        raise ValueError(u'无法计算曲线切向。')

    vertical = safe_normalize(project_to_plane(WORLD_Z, tangent))
    if vertical is None:
        vertical = safe_normalize(project_to_plane(WORLD_X, tangent))
    if vertical is None:
        vertical = safe_normalize(project_to_plane(WORLD_Y, tangent))
    if vertical is None:
        raise ValueError(u'无法为当前曲线建立法向平面坐标系。')

    horizontal = safe_normalize(tangent.CrossProduct(vertical))
    if horizontal is None:
        raise ValueError(u'无法计算法向平面的水平轴。')
    vertical = safe_normalize(horizontal.CrossProduct(tangent))

    return {
        'origin': origin,
        'tangent': tangent,
        'horizontal': horizontal,
        'vertical': vertical,
    }


def ensure_symbol_active(doc, symbol):
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()


def place_symbol_instance(doc, symbol, active_view, placement_item, angle_deg, horizontal_rotation_deg=0.0, vertical_rotation_deg=0.0):
    ensure_symbol_active(doc, symbol)
    placement_type = symbol.Family.FamilyPlacementType

    if placement_type in set([FamilyPlacementType.OneLevelBased, FamilyPlacementType.TwoLevelsBased]):
        instance = None
        try:
            instance = doc.Create.NewFamilyInstance(
                placement_item.target_point,
                symbol,
                StructuralType.NonStructural,
            )
        except Exception:
            level = get_default_level(doc, active_view)
            instance = doc.Create.NewFamilyInstance(
                placement_item.target_point,
                symbol,
                level,
                StructuralType.NonStructural,
            )
        doc.Regenerate()
        orient_point_based_instance(
            doc,
            instance.Id,
            placement_item.target_point,
            placement_item.tangent,
            angle_deg,
        )
        apply_secondary_rotations(
            doc,
            instance.Id,
            placement_item.target_point,
            placement_item.horizontal,
            placement_item.vertical,
            horizontal_rotation_deg,
            vertical_rotation_deg,
        )
        return instance

    raise ValueError(
        u'族类型 "{0} : {1}" 的放置方式为 {2}，该工具当前不支持。'.format(
            symbol.Family.Name,
            get_symbol_type_name(symbol),
            get_placement_type_label(placement_type),
        )
    )


def orient_point_based_instance(doc, instance_id, origin, tangent, angle_deg):
    tangent = safe_normalize(tangent)
    if tangent is None:
        return

    plan_tangent = safe_normalize(project_to_plane(tangent, WORLD_Z))
    if plan_tangent is None:
        total_angle = math.radians(angle_deg)
    else:
        align_angle = signed_angle_on_plane(WORLD_X, plan_tangent, WORLD_Z)
        total_angle = align_angle + math.radians(angle_deg)

    if abs(total_angle) > GEOM_TOLERANCE:
        _rotate_instance_around_axis(doc, instance_id, origin, WORLD_Z, total_angle)


def apply_secondary_rotations(doc, instance_id, origin, horizontal_axis, vertical_axis, horizontal_rotation_deg, vertical_rotation_deg):
    horizontal_angle = math.radians(horizontal_rotation_deg or 0.0)
    vertical_angle = math.radians(vertical_rotation_deg or 0.0)

    if abs(horizontal_angle) > GEOM_TOLERANCE:
        _rotate_instance_around_axis(doc, instance_id, origin, horizontal_axis, horizontal_angle)

    if abs(vertical_angle) > GEOM_TOLERANCE:
        _rotate_instance_around_axis(doc, instance_id, origin, vertical_axis, vertical_angle)


def _rotate_instance_around_axis(doc, instance_id, origin, axis_direction, angle):
    axis_direction = safe_normalize(axis_direction)
    if axis_direction is None or abs(angle) <= GEOM_TOLERANCE:
        return
    axis = Line.CreateBound(origin, origin.Add(axis_direction))
    ElementTransformUtils.RotateElement(doc, instance_id, axis, angle)


def format_xyz_mm(point):
    return u'X {0:.1f} / Y {1:.1f} / Z {2:.1f} mm'.format(
        ft_to_mm(point.X),
        ft_to_mm(point.Y),
        ft_to_mm(point.Z),
    )


def get_loop_centroid(curve_loop):
    points = []
    iterator = curve_loop.GetCurveLoopIterator()
    while iterator.MoveNext():
        curve = iterator.Current
        points.append(curve.GetEndPoint(0))
    if not points:
        raise ValueError(u'轮廓中没有可用点。')
    x_value = sum([point.X for point in points]) / len(points)
    y_value = sum([point.Y for point in points]) / len(points)
    z_value = sum([point.Z for point in points]) / len(points)
    return XYZ(x_value, y_value, z_value)


def create_transform_between_frames(source_origin, source_x, source_y, source_z, target_origin, target_x, target_y, target_z):
    source_x = safe_normalize(source_x)
    source_y = safe_normalize(source_y)
    source_z = safe_normalize(source_z)
    target_x = safe_normalize(target_x)
    target_y = safe_normalize(target_y)
    target_z = safe_normalize(target_z)
    if None in [source_x, source_y, source_z, target_x, target_y, target_z]:
        raise ValueError(u'无法建立轮廓到路径的坐标变换。')

    transform = Transform.Identity
    transform.Origin = target_origin
    transform.BasisX = target_x
    transform.BasisY = target_y
    transform.BasisZ = target_z

    source_transform = Transform.Identity
    source_transform.Origin = source_origin
    source_transform.BasisX = source_x
    source_transform.BasisY = source_y
    source_transform.BasisZ = source_z

    return transform.Multiply(source_transform.Inverse)


def transform_curve_loop(curve_loop, transform):
    transformed_loop = CurveLoop()
    iterator = curve_loop.GetCurveLoopIterator()
    while iterator.MoveNext():
        transformed_loop.Append(iterator.Current.CreateTransformed(transform))
    return transformed_loop


def create_swept_directshape(doc, path_curve, profile_selection, horizontal_offset_ft=0.0, vertical_offset_ft=0.0, horizontal_rotation_deg=0.0, vertical_rotation_deg=0.0, source_label=None, start_distance_ft=0.0, end_distance_ft=None, segment_length_ft=None):
    
    total_length = get_curve_length(path_curve)
    actual_end = min(end_distance_ft, total_length) if end_distance_ft else total_length
    actual_start = max(0.0, start_distance_ft)
    
    # If segment_length is provided, we should recursively/iteratively create multiple DirectShapes.
    # To avoid changing the return type signature for single sweep, we just slice the path_curve here 
    # to the start and end. If segmentation is needed, script.py should call this method multiple times.
    
    cloned_curve = path_curve.Clone()
    if actual_start > GEOM_TOLERANCE or actual_end < total_length - GEOM_TOLERANCE:
        try:
            # For curves where parameter is normalized [0, 1] like HermiteSpline
            p0 = cloned_curve.ComputeNormalizedParameter(actual_start / total_length) if total_length > 0 else 0
            p1 = cloned_curve.ComputeNormalizedParameter(actual_end / total_length) if total_length > 0 else 1
            cloned_curve.MakeBound(p0, p1)
        except Exception:
            pass # fallback to full curve if bounding fails
            
    path_curve_loop = CurveLoop()
    path_curve_loop.Append(cloned_curve)

    profile_loop = profile_selection.curve_loop
    profile_plane = profile_loop.GetPlane()
    profile_origin = get_loop_centroid(profile_loop)

    first_curve = get_first_curve_from_loop(profile_loop)
    profile_x = safe_normalize(project_to_plane(first_curve.GetEndPoint(1).Subtract(first_curve.GetEndPoint(0)), profile_plane.Normal))
    if profile_x is None:
        profile_x = WORLD_X
    profile_z = safe_normalize(profile_plane.Normal)
    profile_y = safe_normalize(profile_z.CrossProduct(profile_x))

    frame = get_curve_frame(path_curve, 0.0)
    target_origin = frame['origin']
    if abs(horizontal_offset_ft) > GEOM_TOLERANCE:
        target_origin = target_origin.Add(frame['horizontal'].Multiply(horizontal_offset_ft))
    if abs(vertical_offset_ft) > GEOM_TOLERANCE:
        target_origin = target_origin.Add(frame['vertical'].Multiply(vertical_offset_ft))

    target_x = frame['horizontal']
    target_y = frame['vertical']
    target_z = frame['tangent']
    horizontal_angle = math.radians(horizontal_rotation_deg or 0.0)
    vertical_angle = math.radians(vertical_rotation_deg or 0.0)
    if abs(horizontal_angle) > GEOM_TOLERANCE:
        target_x = rotate_vector(target_x, target_y, horizontal_angle)
        target_z = rotate_vector(target_z, target_y, horizontal_angle)
    if abs(vertical_angle) > GEOM_TOLERANCE:
        target_y = rotate_vector(target_y, target_x, vertical_angle)
        target_z = rotate_vector(target_z, target_x, vertical_angle)
    target_x = safe_normalize(target_x)
    target_y = safe_normalize(target_y)
    target_z = safe_normalize(target_z)

    transform = create_transform_between_frames(
        profile_origin,
        profile_x,
        profile_y,
        profile_z,
        target_origin,
        target_x,
        target_y,
        target_z,
    )
    transformed_profile = transform_curve_loop(profile_loop, transform)
    profile_loops = List[CurveLoop]()
    profile_loops.Add(transformed_profile)

    solid = GeometryCreationUtilities.CreateSweptGeometry(
        path_curve_loop,
        0,
        0.0,
        profile_loops,
        SolidOptions(ElementId.InvalidElementId, ElementId.InvalidElementId),
    )
    direct_shape = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel))
    geometry_objects = List[GeometryObject]()
    geometry_objects.Add(solid)
    direct_shape.SetShape(geometry_objects)
    if source_label:
        try:
            direct_shape.Name = source_label
        except Exception:
            pass
    return direct_shape


def get_tracking_schema():
    schema = Schema.Lookup(TRACKING_SCHEMA_GUID)
    if schema is not None:
        return schema

    schema_builder = SchemaBuilder(TRACKING_SCHEMA_GUID)
    schema_builder.SetSchemaName("LinerMasterTracking")
    schema_builder.SetReadAccessLevel(AccessLevel.Public)
    schema_builder.SetWriteAccessLevel(AccessLevel.Public)
    schema_builder.SetVendorId(TRACKING_VENDOR_ID)
    schema_builder.SetApplicationGUID(TRACKING_SCHEMA_GUID)
    schema_builder.AddSimpleField("mode", str)
    schema_builder.AddSimpleField("source_label", str)
    schema_builder.AddSimpleField("config_id", int)
    schema_builder.AddSimpleField("created_seconds", str)
    return schema_builder.Finish()


def tag_generated_element(element, mode, source_label, config_id, created_seconds):
    schema = get_tracking_schema()
    entity = Entity(schema)
    entity.Set[str](schema.GetField("mode"), mode or u"")
    entity.Set[str](schema.GetField("source_label"), source_label or u"")
    entity.Set[int](schema.GetField("config_id"), int(config_id or 0))
    entity.Set[str](schema.GetField("created_seconds"), unicode(created_seconds))
    element.SetEntity(entity)


def get_generated_element_info(element):
    schema = get_tracking_schema()
    entity = element.GetEntity(schema)
    if not entity.IsValid():
        return None
    return GeneratedElementInfo(
        element=element,
        mode=entity.Get[str](schema.GetField("mode")),
        source_label=entity.Get[str](schema.GetField("source_label")),
        config_id=entity.Get[int](schema.GetField("config_id")),
        created_seconds=entity.Get[str](schema.GetField("created_seconds")),
        category_name=get_element_category_name(element),
    )


def collect_generated_elements(doc):
    schema = get_tracking_schema()
    collector = FilteredElementCollector(doc).WherePasses(ExtensibleStorageFilter(schema.GUID))
    infos = []
    for element in collector:
        info = get_generated_element_info(element)
        if info is not None:
            infos.append(info)
    return infos


def get_element_category_name(element):
    category = getattr(element, 'Category', None)
    if category is not None:
        try:
            if category.Name:
                return category.Name
        except Exception:
            pass
    return u'<无类别>'


def get_first_curve_from_loop(curve_loop):
    iterator = curve_loop.GetCurveLoopIterator()
    if iterator.MoveNext():
        return iterator.Current
    raise ValueError(u'轮廓中没有可用曲线。')
