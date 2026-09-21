# -*- coding: utf-8 -*-
from __future__ import division

import math
import os
import time
import traceback

import clr
clr.AddReference('RevitAPI')

from Autodesk.Revit.DB import (
    AdaptiveComponentFamilyUtils, AdaptiveComponentInstanceUtils, BuiltInParameter, ElementId, Family,
    FamilyInstance, FamilyPlacementType, FamilySource, FamilySymbol,
    FilteredElementCollector, GeometryInstance, IFamilyLoadOptions,
    Level, Line, Options, Plane, PlanarFace, SketchPlane, Solid, Transform, UnitUtils, ViewDetailLevel, XYZ
)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler
from Autodesk.Revit.UI.Selection import ISelectionFilter
from pyrevit import forms, revit, script
from System.Collections.Generic import List
from System.Windows.Controls import Canvas, TextBlock
from System.Windows.Media import Brushes
from System.Windows.Shapes import Ellipse, Line as WpfLine

try:
    from Autodesk.Revit.DB import UnitTypeId
except Exception:
    UnitTypeId = None

try:
    unicode
except NameError:
    unicode = str


MM_PER_FOOT = 304.8
EDGE_CONNECT_TOLERANCE_FT = 0.33
TOP_EDGE_BAND_FT = 6.56
MAX_ADAPTIVE_SEGMENT_MM = 10000.0
DEFAULT_ADAPTIVE_OVERLAP_MM = 300.0
DEFAULT_SUPPORT_SPACING_MM = 40000.0
LOGGER = script.get_logger()
doc = revit.doc
uidoc = revit.uidoc


class BridgeSelectionFilter(ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, FamilyInstance) and element.Category is not None

    def AllowReference(self, reference, position):
        return False


class Choice(object):
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __str__(self):
        return self.name


class FamilyLoadOptions(IFamilyLoadOptions):
    def OnFamilyFound(self, family_in_use, overwrite_parameter_values):
        overwrite_parameter_values.Value = False
        return True


class WizardApiHandler(IExternalEventHandler):
    def __init__(self, wizard):
        self.wizard = wizard
        self.action = None
        self.error_control = None

    def set_action(self, action, error_control):
        self.action = action
        self.error_control = error_control

    def Execute(self, application):
        action = self.action
        error_control = self.error_control
        self.action = None
        try:
            if action is None:
                raise Exception(u'没有待执行的 Revit API 操作。')
            action()
        except OperationCanceledException:
            self.wizard._set_text(error_control, u'用户取消了当前步骤。')
        except Exception as exception:
            LOGGER.error(traceback.format_exc())
            self.wizard._set_error(error_control, exception)
        finally:
            self.wizard._finish_external_action()

    def GetName(self):
        return u'桥梁接触网布置向导 API 操作'

    def OnSharedFamilyFound(self, shared_family, family_in_use, source, overwrite_parameter_values):
        source.Value = FamilySource.Family
        overwrite_parameter_values.Value = False
        return True


class CurvePath(object):
    def __init__(self, curves):
        self.curves = curves
        self.length = sum([curve.Length for curve in curves])

    def point_at(self, distance):
        if distance <= 0:
            return self.curves[0].GetEndPoint(0)
        remaining = distance
        for curve in self.curves:
            if remaining <= curve.Length:
                return curve.Evaluate(remaining / curve.Length, True)
            remaining -= curve.Length
        return self.curves[-1].GetEndPoint(1)

    def tangent_at(self, distance):
        remaining = max(0.0, distance)
        for curve in self.curves:
            if remaining <= curve.Length:
                return curve.ComputeDerivatives(remaining / curve.Length, True).BasisX.Normalize()
            remaining -= curve.Length
        return self.curves[-1].ComputeDerivatives(1.0, True).BasisX.Normalize()


def first_path_segments(path, count):
    """返回中心线起始的若干桥面连接段，供实际模型预览使用。"""
    if count <= 0 or not path.curves:
        raise Exception(u'拟合中心线没有可用于预览的桥面连接段。')
    return CurvePath(path.curves[:min(count, len(path.curves))])


def create_centerline_model_curves(path):
    """按三维拟合路径创建模型线，供用户在桥面上直接核对中心线。"""
    created_ids = []
    for index, curve in enumerate(path.curves):
        start = curve.GetEndPoint(0)
        tangent = curve.GetEndPoint(1) - start
        horizontal = horizontal_unit(tangent)
        if horizontal is None:
            raise Exception(u'中心线第 {0} 段没有有效的水平投影，无法创建桥面模型线。'.format(index + 1))
        plane_normal = XYZ(-horizontal.Y, horizontal.X, 0.0)
        try:
            sketch_plane = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(plane_normal, start))
            model_curve = doc.Create.NewModelCurve(curve, sketch_plane)
            created_ids.append(model_curve.Id)
        except Exception as exception:
            raise Exception(
                u'创建中心线第 {0} 段模型线失败。起点 Z={1:.3f} ft，终点 Z={2:.3f} ft，错误：{3}'.format(
                    index + 1, start.Z, curve.GetEndPoint(1).Z, text(exception)
                )
            )
    return created_ids


class OffsetPath(object):
    def __init__(self, base_path, horizontal_mm, vertical_mm):
        self.base_path = base_path
        self.horizontal_mm = horizontal_mm
        self.vertical_mm = vertical_mm
        self.length = base_path.length

    def point_at(self, distance):
        point = self.base_path.point_at(distance)
        tangent = self.base_path.tangent_at(distance)
        normal = horizontal_unit(tangent)
        if normal is None:
            raise Exception(u'中心路径在距离 {0:.2f} mm 处没有有效的水平切线。'.format(ft_to_mm(distance)))
        lateral = XYZ(-normal.Y, normal.X, 0.0)
        return point + lateral.Multiply(mm_to_ft(self.horizontal_mm)) + XYZ(0.0, 0.0, mm_to_ft(self.vertical_mm))

    def tangent_at(self, distance):
        return self.base_path.tangent_at(distance)


def mm_to_ft(value):
    return value / MM_PER_FOOT


def ft_to_mm(value):
    return value * MM_PER_FOOT


def text(value):
    if value is None:
        return u''
    try:
        return unicode(value)
    except Exception:
        return unicode(str(value))


def activate(symbol):
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()


def is_adaptive(symbol):
    family = doc.GetElement(symbol.Family.Id)
    return family is not None and AdaptiveComponentFamilyUtils.IsAdaptiveComponentFamily(family)


def get_adaptive_symbols():
    symbols = []
    for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
        if is_adaptive(symbol):
            symbols.append(symbol)
    return symbols


def get_support_symbols():
    symbols = []
    for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
        if not is_adaptive(symbol):
            symbols.append(symbol)
    return symbols


def symbol_choice(symbol):
    category_name = symbol.Category.Name if symbol.Category else u'无类别'
    type_name_parameter = symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    type_name = type_name_parameter.AsString() if type_name_parameter is not None else None
    if not type_name:
        type_name = u'类型 Id {0}'.format(symbol.Id.IntegerValue)
    return Choice(u'{0} | {1} : {2}'.format(category_name, symbol.Family.Name, type_name), symbol)


def select_one(choices, title, button_name):
    selected = forms.SelectFromList.show(
        choices, title=title, button_name=button_name, multiselect=False, name_attr='name'
    )
    if selected is None:
        script.exit()
    return selected.value


def family_name_from_path(path):
    return os.path.splitext(os.path.basename(path))[0]


def symbols_in_family(family_name, require_adaptive):
    symbols = []
    for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
        if symbol.Family.Name != family_name:
            continue
        if is_adaptive(symbol) != require_adaptive:
            continue
        symbols.append(symbol)
    return symbols


def load_family_file(role_name, require_adaptive, path):
    expected_name = family_name_from_path(path)
    family_ids_before = set([family.Id.IntegerValue for family in FilteredElementCollector(doc).OfClass(Family)])
    try:
        with revit.Transaction(u'载入{0}族'.format(role_name)):
            loaded = doc.LoadFamily(path, FamilyLoadOptions())
    except Exception as exception:
        raise Exception(u'无法载入{0}族文件：{1}\n文件：{2}'.format(role_name, text(exception), path))
    loaded_families = [
        family for family in FilteredElementCollector(doc).OfClass(Family)
        if family.Id.IntegerValue not in family_ids_before
    ]
    family_names = [family.Name for family in loaded_families]
    if len(family_names) == 1:
        symbols = symbols_in_family(family_names[0], require_adaptive)
    else:
        symbols = symbols_in_family(expected_name, require_adaptive)
    if not symbols:
        kind = u'自适应族' if require_adaptive else u'非宿主点式族'
        raise Exception(
            u'已选择并尝试载入 {0}，但未找到对应的{1}类型。'
            u'文件名推断的族名称：“{2}”；本次新载入族：“{3}”；载入返回值：{4}。'.format(
                role_name, kind, expected_name, u', '.join(family_names) or u'无', loaded
            )
        )
    return select_one([symbol_choice(item) for item in symbols], u'选择{0}类型'.format(role_name), u'确认类型')


def read_number(values, name, label, unit=u'mm'):
    raw_value = values.get(name)
    try:
        return float(raw_value.strip())
    except Exception:
        raise Exception(u'{0}必须输入数值（单位 {1}），当前输入为：{2}'.format(label, unit, text(raw_value)))


def get_path_offset_mm(center_path, edge_path):
    offsets = []
    for ratio in [0.0, 0.5, 1.0]:
        center_point = center_path.point_at(center_path.length * ratio)
        edge_point = edge_path.point_at(edge_path.length * ratio)
        tangent = horizontal_unit(center_path.tangent_at(center_path.length * ratio))
        if tangent is None:
            raise Exception(u'无法计算中心线的水平法向，不能生成两侧族的默认偏移。')
        normal = XYZ(-tangent.Y, tangent.X, 0.0)
        offsets.append((edge_point - center_point).DotProduct(normal))
    return ft_to_mm(sum(offsets) / len(offsets))


def bbox_corners(bbox):
    if bbox is None:
        return []
    points = []
    for x in [bbox.Min.X, bbox.Max.X]:
        for y in [bbox.Min.Y, bbox.Max.Y]:
            for z in [bbox.Min.Z, bbox.Max.Z]:
                points.append(bbox.Transform.OfPoint(XYZ(x, y, z)))
    return points


def median(values):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def bridge_top_surface_center(bridge):
    """从实体上向平面中选取水平投影面积最大的桥面主顶面。"""
    options = Options()
    options.DetailLevel = ViewDetailLevel.Fine
    geometry = bridge.get_Geometry(options)
    if geometry is None:
        raise Exception(u'桥面族 Id {0} 没有可读取的实体几何。'.format(bridge.Id.IntegerValue))
    solids = collect_solids(geometry)
    if not solids:
        raise Exception(u'桥面族 Id {0} 不包含有效实体，无法确定桥面顶面。'.format(bridge.Id.IntegerValue))

    best = None
    for solid in solids:
        for face in solid.Faces:
            if not isinstance(face, PlanarFace) or face.FaceNormal.Z < 0.35:
                continue
            mesh = face.Triangulate()
            vertices = list(mesh.Vertices)
            if len(vertices) < 3:
                continue
            center = XYZ(
                sum([vertex.X for vertex in vertices]) / len(vertices),
                sum([vertex.Y for vertex in vertices]) / len(vertices),
                sum([vertex.Z for vertex in vertices]) / len(vertices)
            )
            projected_area = face.Area * face.FaceNormal.Z
            candidate = (projected_area, center.Z, center)
            if best is None or candidate[0] > best[0] or (candidate[0] == best[0] and candidate[1] > best[1]):
                best = candidate
    if best is None:
        raise Exception(
            u'桥面族 Id {0} 未找到上向的平面实体面。请确认框选的是桥面实体族，'
            u'而不是仅含曲面、链接或仅含梁底几何的族。'.format(bridge.Id.IntegerValue)
        )
    return best[2]


def fit_paths_from_bridge_families(bridges):
    sections = []
    for bridge in bridges:
        corners = bbox_corners(bridge.get_BoundingBox(None))
        if len(corners) != 8:
            raise Exception(u'桥面族 Id {0} 没有有效包围盒，无法拟合中心线。'.format(bridge.Id.IntegerValue))
        # 用户指定以每个框选桥面族的最高标高为拟合基准，避免桥墩、承台等大面积面干扰。
        center_x = sum([point.X for point in corners]) / len(corners)
        center_y = sum([point.Y for point in corners]) / len(corners)
        top_z = max([point.Z for point in corners])
        sections.append({'element': bridge, 'center': XYZ(center_x, center_y, top_z), 'corners': corners})
    if len(sections) < 2:
        raise Exception(u'至少需要选择两个桥面族，才能拟合中心线。')

    mean_x = sum([item['center'].X for item in sections]) / len(sections)
    mean_y = sum([item['center'].Y for item in sections]) / len(sections)
    covariance_xx = sum([(item['center'].X - mean_x) ** 2 for item in sections])
    covariance_yy = sum([(item['center'].Y - mean_y) ** 2 for item in sections])
    covariance_xy = sum([(item['center'].X - mean_x) * (item['center'].Y - mean_y) for item in sections])
    if covariance_xx + covariance_yy < 1e-8:
        raise Exception(u'框选桥面族的平面中心重合，无法确定线路方向。')
    angle = 0.5 * math.atan2(2.0 * covariance_xy, covariance_xx - covariance_yy)
    axis = XYZ(math.cos(angle), math.sin(angle), 0.0)
    # 用线路主方向投影排序，保证桥面段单调连续，避免最近邻在平行跨或缓弯处回跳。
    ordered = sorted(
        sections,
        key=lambda item: (item['center'].X - mean_x) * axis.X + (item['center'].Y - mean_y) * axis.Y
    )

    center_points = [item['center'] for item in ordered]
    center_path = CurvePath([Line.CreateBound(center_points[index], center_points[index + 1]) for index in range(len(center_points) - 1)])
    first_tangent = horizontal_unit(center_path.tangent_at(0.0))
    if first_tangent is None:
        raise Exception(u'拟合中心线没有有效的水平切线。')
    normal = XYZ(-first_tangent.Y, first_tangent.X, 0.0)
    widths = []
    for item in ordered:
        projections = [(point.X - item['center'].X) * normal.X + (point.Y - item['center'].Y) * normal.Y for point in item['corners']]
        width = max(projections) - min(projections)
        if width > 0.1:
            widths.append(width)
    if not widths or median(widths) <= 0.5:
        raise Exception(u'无法从桥面族包围盒计算有效桥宽；请确认框选的是桥面实体族。')
    half_width_mm = ft_to_mm(median(widths) / 2.0)
    edge_a_path = OffsetPath(center_path, -half_width_mm, 0.0)
    edge_b_path = OffsetPath(center_path, half_width_mm, 0.0)
    return center_path, edge_a_path, edge_b_path


def collect_solids(geometry):
    solids = []
    for item in geometry:
        if isinstance(item, Solid) and item.Volume > 0:
            solids.append(item)
        elif isinstance(item, GeometryInstance):
            solids.extend(collect_solids(item.GetInstanceGeometry()))
    return solids


def is_longitudinal(curve):
    start = curve.GetEndPoint(0)
    end = curve.GetEndPoint(1)
    horizontal_length = math.sqrt((end.X - start.X) ** 2 + (end.Y - start.Y) ** 2)
    return curve.Length > 1.0 and horizontal_length / curve.Length > 0.55


def collect_top_edge_curves(bridge):
    options = Options()
    options.DetailLevel = ViewDetailLevel.Fine
    geometry = bridge.get_Geometry(options)
    if geometry is None:
        raise Exception(u'桥梁构件没有可读取的实体几何。')
    solids = collect_solids(geometry)
    if not solids:
        raise Exception(u'桥梁构件未返回有效实体。请确认选择的是实际桥梁实体，而不是链接或组。')

    all_curves = []
    highest_z = None
    for solid in solids:
        for edge in solid.Edges:
            curve = edge.AsCurve()
            if not is_longitudinal(curve):
                continue
            average_z = (curve.GetEndPoint(0).Z + curve.GetEndPoint(1).Z) / 2.0
            highest_z = average_z if highest_z is None else max(highest_z, average_z)
            all_curves.append((curve, average_z))
    if highest_z is None:
        raise Exception(u'未找到具有足够平面投影长度的桥梁边线。')
    return [curve for curve, average_z in all_curves if average_z >= highest_z - TOP_EDGE_BAND_FT]


def point_close(left, right):
    return left.DistanceTo(right) <= EDGE_CONNECT_TOLERANCE_FT


def chain_curves(curves):
    pending = list(curves)
    paths = []
    while pending:
        chain = [pending.pop(0)]
        changed = True
        while changed:
            changed = False
            first = chain[0].GetEndPoint(0)
            last = chain[-1].GetEndPoint(1)
            for index, candidate in enumerate(pending):
                start = candidate.GetEndPoint(0)
                end = candidate.GetEndPoint(1)
                if point_close(last, start):
                    chain.append(candidate)
                elif point_close(last, end):
                    chain.append(candidate.CreateReversed())
                elif point_close(first, end):
                    chain.insert(0, candidate)
                elif point_close(first, start):
                    chain.insert(0, candidate.CreateReversed())
                else:
                    continue
                pending.pop(index)
                changed = True
                break
        paths.append(CurvePath(chain))
    return paths


def horizontal_unit(vector):
    flattened = XYZ(vector.X, vector.Y, 0.0)
    if flattened.GetLength() < 0.0001:
        return None
    return flattened.Normalize()


def pair_score(left, right):
    if left.length < 3.0 or right.length < 3.0:
        return None
    left_tangent = horizontal_unit(left.tangent_at(0.0))
    right_tangent = horizontal_unit(right.tangent_at(0.0))
    if left_tangent is None or right_tangent is None:
        return None
    parallel = abs(left_tangent.DotProduct(right_tangent))
    if parallel < 0.75:
        return None
    short_length = min(left.length, right.length)
    ratios = [0.0, 0.5, 1.0]
    distances = []
    for ratio in ratios:
        a = left.point_at(left.length * ratio)
        b = right.point_at(right.length * ratio)
        distances.append(math.sqrt((a.X - b.X) ** 2 + (a.Y - b.Y) ** 2))
    mean_distance = sum(distances) / len(distances)
    if mean_distance < 1.0:
        return None
    variation = max(distances) - min(distances)
    if variation > mean_distance * 0.75:
        return None
    return short_length * parallel * mean_distance


def find_outer_paths(bridges):
    candidate_curves = []
    bridge_ids = []
    for bridge in bridges:
        candidate_curves.extend(collect_top_edge_curves(bridge))
        bridge_ids.append(text(bridge.Id.IntegerValue))
    paths = chain_curves(candidate_curves)
    best = None
    for left_index in range(len(paths)):
        for right_index in range(left_index + 1, len(paths)):
            score = pair_score(paths[left_index], paths[right_index])
            if score is not None and (best is None or score > best[0]):
                best = (score, paths[left_index], paths[right_index])
    if best is None:
        raise Exception(
            u'无法从框选桥面族的顶面边线可靠识别两侧外边。候选连续路径数：{0}；框选族数：{1}；族 Id：{2}。'
            u'请检查框选范围是否覆盖完整桥面、相邻梁面是否相接，且两侧边线位于顶面附近。'.format(
                len(paths), len(bridges), u', '.join(bridge_ids)
            )
        )
    return best[1], best[2]


def evenly_spaced_distances(length, maximum_segment_ft):
    count = max(1, int(math.ceil(length / maximum_segment_ft)))
    return [length * index / count for index in range(count + 1)]


def build_center_path(left, right):
    segment_length = mm_to_ft(MAX_ADAPTIVE_SEGMENT_MM)
    count = max(1, int(math.ceil(max(left.length, right.length) / segment_length)))
    points = []
    for index in range(count + 1):
        ratio = float(index) / count
        a = left.point_at(left.length * ratio)
        b = right.point_at(right.length * ratio)
        points.append(XYZ((a.X + b.X) / 2.0, (a.Y + b.Y) / 2.0, (a.Z + b.Z) / 2.0))
    return CurvePath([Line.CreateBound(points[index], points[index + 1]) for index in range(len(points) - 1)])


def placement_point_count(symbol):
    instance = AdaptiveComponentInstanceUtils.CreateAdaptiveComponentInstance(doc, symbol)
    point_ids = AdaptiveComponentInstanceUtils.GetInstancePlacementPointElementRefIds(instance)
    doc.Delete(instance.Id)
    return point_ids.Count


def create_adaptive(symbol, points):
    instance = AdaptiveComponentInstanceUtils.CreateAdaptiveComponentInstance(doc, symbol)
    point_ids = AdaptiveComponentInstanceUtils.GetInstancePlacementPointElementRefIds(instance)
    if point_ids.Count != len(points):
        raise Exception(u'自适应点数量不一致：族需要 {0} 点，当前提供 {1} 点。'.format(point_ids.Count, len(points)))
    for index, point_id in enumerate(point_ids):
        reference_point = doc.GetElement(point_id)
        reference_point.Position = points[index]
    return instance


def adaptive_instance_count(path, point_count):
    if point_count < 2:
        raise Exception(u'自适应族必须至少包含 2 个自适应点，当前为 {0}。'.format(point_count))
    if point_count == 2:
        return len(evenly_spaced_distances(path.length, mm_to_ft(MAX_ADAPTIVE_SEGMENT_MM))) - 1
    return 1


def place_adaptive_along_path(symbol, path, label, overlap_mm, created_ids, point_count=None, progress_callback=None):
    activate(symbol)
    point_count = point_count if point_count is not None else placement_point_count(symbol)
    if point_count < 2:
        raise Exception(u'{0} 必须至少包含 2 个自适应点，当前为 {1}。'.format(label, point_count))
    if point_count == 2:
        distances = evenly_spaced_distances(path.length, mm_to_ft(MAX_ADAPTIVE_SEGMENT_MM))
        for index in range(len(distances) - 1):
            overlap = mm_to_ft(overlap_mm) / 2.0
            start_distance = max(0.0, distances[index] - overlap)
            end_distance = min(path.length, distances[index + 1] + overlap)
            if end_distance - start_distance < mm_to_ft(1.0):
                raise Exception(u'{0} 的第 {1} 段搭接后长度不足 1 mm。'.format(label, index + 1))
            instance = create_adaptive(symbol, [path.point_at(start_distance), path.point_at(end_distance)])
            created_ids.append(instance.Id)
            if progress_callback is not None:
                progress_callback()
        return
    points = [path.point_at(path.length * index / float(point_count - 1)) for index in range(point_count)]
    instance = create_adaptive(symbol, points)
    created_ids.append(instance.Id)
    if progress_callback is not None:
        progress_callback()


def validate_support_symbol(symbol):
    family = doc.GetElement(symbol.Family.Id)
    placement_type = family.FamilyPlacementType
    supported_types = [FamilyPlacementType.OneLevelBased, FamilyPlacementType.WorkPlaneBased]
    if placement_type not in supported_types:
        raise Exception(
            u'接触网支柱族必须是“基于标高”或“基于工作平面”的普通点式族；当前族的放置类型为：{0}。'
            u'请使用可按点放置的常规模型族。'.format(placement_type)
        )
    return placement_type


def nearest_level(point):
    levels = list(FilteredElementCollector(doc).OfClass(Level))
    if not levels:
        raise Exception(u'当前项目没有标高，无法放置接触网支柱。')
    return min(levels, key=lambda level: abs(level.Elevation - point.Z))


def set_instance_elevation(instance, point, level):
    """使基于标高的支柱基点精确落在拟合出的桥面顶面。"""
    elevation_parameter = instance.get_Parameter(BuiltInParameter.INSTANCE_ELEVATION_PARAM)
    if elevation_parameter is None or elevation_parameter.IsReadOnly:
        raise Exception(
            u'接触网支柱实例 Id {0} 没有可写的“标高偏移”参数，无法把支柱定位到桥面顶面。'
            u'请选择“基于标高”的非宿主点式族。'.format(instance.Id.IntegerValue)
        )
    elevation_parameter.Set(point.Z - level.Elevation)
    set_instance_location(instance, point)


def set_instance_location(instance, point):
    """校验普通族的位置点，避免 Revit 按默认工作平面或标高偏移到桥下。"""
    doc.Regenerate()
    location = instance.Location
    if location is None or not hasattr(location, 'Point'):
        raise Exception(u'接触网支柱实例 Id {0} 没有可编辑的位置点。'.format(instance.Id.IntegerValue))
    location.Point = point
    doc.Regenerate()
    actual_point = location.Point
    if actual_point.DistanceTo(point) > mm_to_ft(1.0):
        raise Exception(
            u'接触网支柱实例 Id {0} 未能落到桥面顶面。目标 Z={1:.3f} ft，实际 Z={2:.3f} ft。'.format(
                instance.Id.IntegerValue, point.Z, actual_point.Z
            )
        )


def rotate_support(instance, tangent, rotation_x, rotation_y, rotation_z, side_rotation_sign):
    horizontal = horizontal_unit(tangent)
    if horizontal is None:
        raise Exception(u'接触网支柱位置没有有效的线路水平切线，无法确定旋转方向。')
    point = instance.Location.Point
    from Autodesk.Revit.DB import ElementTransformUtils
    rotations = [
        (XYZ(1, 0, 0), math.radians(rotation_x), u'X'),
        (XYZ(0, 1, 0), math.radians(rotation_y), u'Y'),
        # 支柱横臂朝向中心线：左侧相对线路切线 +90 度，右侧 -90 度。
        (XYZ(0, 0, 1), math.atan2(horizontal.Y, horizontal.X) + side_rotation_sign * (math.pi / 2.0 + math.radians(rotation_z)), u'Z'),
    ]
    for direction, angle, axis_name in rotations:
        if abs(angle) < 0.000001:
            continue
        try:
            axis = Line.CreateBound(point, point + direction.Multiply(10.0))
            ElementTransformUtils.RotateElement(doc, instance.Id, axis, angle)
        except Exception as exception:
            raise Exception(u'接触网支柱实例 Id {0} 绕 {1} 轴旋转失败：{2}'.format(
                instance.Id.IntegerValue, axis_name, text(exception)
            ))


def support_distances(path_length, spacing_mm, force_end=False):
    spacing = mm_to_ft(spacing_mm)
    distances = []
    distance = 0.0
    while distance <= path_length + 0.001:
        distances.append(min(distance, path_length))
        distance += spacing
    if force_end and path_length - distances[-1] > mm_to_ft(1.0):
        distances.append(path_length)
    elif path_length - distances[-1] > spacing * 0.25:
        distances.append(path_length)
    return distances


def place_supports(symbol, path, spacing_mm, rotation_x, rotation_y, rotation_z, side_rotation_sign, created_ids, force_end=False, progress_callback=None):
    placement_type = validate_support_symbol(symbol)
    activate(symbol)
    distances = support_distances(path.length, spacing_mm, force_end)
    for distance in distances:
        point = path.point_at(distance)
        if placement_type == FamilyPlacementType.OneLevelBased:
            level = nearest_level(point)
            instance = doc.Create.NewFamilyInstance(point, symbol, level, StructuralType.NonStructural)
            set_instance_elevation(instance, point, level)
        else:
            work_plane = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, point))
            instance = doc.Create.NewFamilyInstance(point, symbol, work_plane, StructuralType.NonStructural)
            set_instance_location(instance, point)
        rotate_support(instance, path.tangent_at(distance), rotation_x, rotation_y, rotation_z, side_rotation_sign)
        created_ids.append(instance.Id)
        if progress_callback is not None:
            progress_callback()


class BridgePlacementWizard(forms.WPFWindow):
    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file)
        self.bridges = []
        self.center_path = None
        self.edge_a_offset_mm = 0.0
        self.edge_b_offset_mm = 0.0
        self.symbols = {}
        self.preview_ids = []
        self.centerline_ids = []
        self.api_handler = WizardApiHandler(self)
        self.api_event = ExternalEvent.Create(self.api_handler)
        self._set_text(self.BridgeStatus, u'未选择。可多次框选同一段桥面族。')

    def _set_text(self, control, value):
        control.Text = text(value)

    def _symbol_text(self, symbol):
        family_name = text(symbol.Family.Name)
        type_parameter = symbol.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        type_name = type_parameter.AsString() if type_parameter is not None else None
        return u'{0} | {1}'.format(family_name, type_name or u'类型 Id {0}'.format(symbol.Id.IntegerValue))

    def _profile_number(self, control):
        try:
            return float(control.Text.strip())
        except Exception:
            return 0.0

    def _profile_marker(self, x, y, label, brush):
        marker = Ellipse()
        marker.Width = 12
        marker.Height = 12
        marker.Fill = brush
        Canvas.SetLeft(marker, x - 6)
        Canvas.SetTop(marker, y - 6)
        self.ProfileCanvas.Children.Add(marker)
        caption = TextBlock()
        caption.Text = label
        caption.Foreground = brush
        Canvas.SetLeft(caption, x + 8)
        Canvas.SetTop(caption, y - 10)
        self.ProfileCanvas.Children.Add(caption)

    def UpdateProfile(self, sender, args):
        try:
            canvas = self.ProfileCanvas
            canvas.Children.Clear()
            width = max(float(canvas.ActualWidth), 600.0)
            height = max(float(canvas.ActualHeight), 190.0)
            origin_x = width / 2.0
            origin_y = height * 0.62
            horizontal_scale = max(
                abs(self._profile_number(self.RailH)),
                abs(self._profile_number(self.BarrierAH)),
                abs(self._profile_number(self.BarrierBH)),
                abs(self._profile_number(self.SupportH)),
                1000.0
            )
            vertical_scale = max(
                abs(self._profile_number(self.RailV)),
                abs(self._profile_number(self.BarrierAV)),
                abs(self._profile_number(self.BarrierBV)),
                abs(self._profile_number(self.SupportV)),
                1000.0
            )
            horizontal_half_width = width * 0.42
            vertical_half_height = height * 0.32
            axis = WpfLine()
            axis.X1 = 24
            axis.X2 = width - 24
            axis.Y1 = origin_y
            axis.Y2 = origin_y
            axis.Stroke = Brushes.Gray
            axis.StrokeDashArray.Add(3)
            canvas.Children.Add(axis)
            if self.center_path is not None:
                deck = WpfLine()
                deck.X1 = origin_x - self.edge_a_offset_mm / horizontal_scale * horizontal_half_width
                deck.X2 = origin_x - self.edge_b_offset_mm / horizontal_scale * horizontal_half_width
                deck.Y1 = origin_y
                deck.Y2 = origin_y
                deck.Stroke = Brushes.LightGray
                deck.StrokeThickness = 8
                canvas.Children.Add(deck)
            title = TextBlock()
            title.Text = u'拟合线路法向剖面（中心线为 0，向上为正）'
            title.Foreground = Brushes.DimGray
            Canvas.SetLeft(title, 10)
            Canvas.SetTop(title, 8)
            canvas.Children.Add(title)
            items = [
                (u'轨道 A', -self._profile_number(self.RailH), self._profile_number(self.RailV), Brushes.DarkBlue),
                (u'轨道 B', self._profile_number(self.RailH), self._profile_number(self.RailV), Brushes.DarkBlue),
                (u'挡板 A', self._profile_number(self.BarrierAH), self._profile_number(self.BarrierAV), Brushes.DarkOrange),
                (u'挡板 B', self._profile_number(self.BarrierBH), self._profile_number(self.BarrierBV), Brushes.DarkOrange),
                (u'支柱 A', -self._profile_number(self.SupportH), self._profile_number(self.SupportV), Brushes.DarkGreen),
                (u'支柱 B', self._profile_number(self.SupportH), self._profile_number(self.SupportV), Brushes.DarkGreen),
            ]
            for label, horizontal, vertical, brush in items:
                x = origin_x + horizontal / horizontal_scale * horizontal_half_width
                y = origin_y - vertical / vertical_scale * vertical_half_height
                self._profile_marker(x, y, u'{0} ({1:.0f},{2:.0f})'.format(label, horizontal, vertical), brush)
            if self.center_path is not None:
                spacing = self._profile_number(self.SupportSpacing)
                count = int(math.floor(ft_to_mm(self.center_path.length) / spacing)) + 1 if spacing > 0 else 0
                self._set_text(self.PreviewStatus, u'中心线 {0:.2f} m；按当前间距预计每侧 {1} 根支柱。'.format(
                    self.center_path.length * 0.3048, count
                ))
        except Exception:
            # WPF may raise TextChanged while the XAML tree is still initializing.
            pass

    def _set_error(self, control, exception):
        self._set_text(control, u'失败：{0}'.format(exception))
        self._set_text(self.ResultStatus, u'请根据上方错误信息修正后重试。\n\n{0}'.format(traceback.format_exc()))

    def _update_start_state(self):
        has_center = self.center_path is not None
        self.RailButton.IsEnabled = has_center
        self.BarrierAButton.IsEnabled = has_center
        self.BarrierBButton.IsEnabled = has_center
        self.SupportButton.IsEnabled = has_center
        self.ParameterGroup.IsEnabled = has_center
        self.StartButton.IsEnabled = self.center_path is not None and len(self.symbols) == 4
        self.PreviewButton.IsEnabled = self.StartButton.IsEnabled

    def _run_external_action(self, action, error_control):
        self.api_handler.set_action(action, error_control)
        # 不能设置 WindowState=Minimized：该窗口与 Revit 关联时会连带最小化 Revit 主窗口。
        # 隐藏向导可释放 Revit 界面进行框选，完成后再显示本向导。
        self.Hide()
        try:
            self.api_event.Raise()
        except Exception as exception:
            LOGGER.error(traceback.format_exc())
            self._set_error(error_control, exception)
            self._finish_external_action()

    def _finish_external_action(self):
        self._update_start_state()
        self.Show()
        self.Activate()

    def SelectBridges(self, sender, args):
        def action():
            bridges_by_id = dict([(bridge.Id.IntegerValue, bridge) for bridge in self.bridges])
            while True:
                selected = list(uidoc.Selection.PickElementsByRectangle(
                    BridgeSelectionFilter(), u'框选本批桥面族；完成后可继续框选其他批次。'
                ))
                for bridge in selected:
                    bridges_by_id[bridge.Id.IntegerValue] = bridge
                if not bridges_by_id:
                    raise Exception(u'未框选到桥面族。请框选至少一个同一高架桥段的桥面族。')
                self._set_text(self.BridgeStatus, u'已选 {0} 个桥面族；可点击“继续框选”按钮再次补选。'.format(len(bridges_by_id)))
                if not forms.alert(
                    u'本次框选 {0} 个，累计 {1} 个。\n\n是否继续框选其他桥面族？'.format(len(selected), len(bridges_by_id)),
                    title=u'桥面族选择', yes=True, no=True, exitscript=False
                ):
                    break
            self.bridges = list(bridges_by_id.values())
            self.center_path, edge_a_path, edge_b_path = fit_paths_from_bridge_families(self.bridges)
            self.edge_a_offset_mm = get_path_offset_mm(self.center_path, edge_a_path)
            self.edge_b_offset_mm = get_path_offset_mm(self.center_path, edge_b_path)
            with revit.Transaction(u'绘制桥面拟合中心线模型线'):
                self._delete_preview_in_transaction()
                self.preview_ids = []
                self._delete_centerline_in_transaction()
                self.centerline_ids = create_centerline_model_curves(self.center_path)
            self._set_text(self.FitStatus, u'完成：已在拟合路径上绘制 {0} 段桥面中心线模型线（{1:.2f} m）；边线 A/B 默认水平偏移 {2:.0f} / {3:.0f} mm。请先在 Revit 中核对中心线是否贴合桥面。'.format(
                len(self.centerline_ids), self.center_path.length * 0.3048, self.edge_a_offset_mm, self.edge_b_offset_mm
            ))
            self.PreviewStatus.Text = u'中心线已拟合，可编辑偏移并预览预计布置。'
            self.BarrierAH.Text = u'{0:.0f}'.format(self.edge_a_offset_mm)
            self.BarrierBH.Text = u'{0:.0f}'.format(self.edge_b_offset_mm)
            self.SupportH.Text = u'{0:.0f}'.format(abs(self.edge_a_offset_mm))
            self.UpdateProfile(None, None)
            self._update_start_state()
        self._run_external_action(action, self.FitStatus)

    def _load_role(self, role_name, key, require_adaptive, status_control):
        self.Hide()
        try:
            path = forms.pick_file(file_ext='rfa', title=u'选择{0}族文件'.format(role_name))
        except Exception as exception:
            self._set_error(status_control, exception)
            self.Show()
            self.Activate()
            return
        if not path:
            self._set_text(status_control, u'未选择文件。')
            self.Show()
            self.Activate()
            return

        def action():
            symbol = load_family_file(role_name, require_adaptive, path)
            self.symbols[key] = symbol
            self._set_text(status_control, u'完成：{0}'.format(self._symbol_text(symbol)))
        self._run_external_action(action, status_control)

    def LoadRail(self, sender, args):
        self._load_role(u'轨道自适应', 'rail', True, self.RailStatus)

    def LoadBarrierA(self, sender, args):
        self._load_role(u'桥边挡板 A 自适应', 'barrier_a', True, self.BarrierAStatus)

    def LoadBarrierB(self, sender, args):
        self._load_role(u'桥边挡板 B 自适应', 'barrier_b', True, self.BarrierBStatus)

    def LoadSupport(self, sender, args):
        self._load_role(u'接触网支柱', 'support', False, self.SupportStatus)

    def _settings(self):
        values = {
            'rail_h': self.RailH.Text, 'rail_v': self.RailV.Text,
            'barrier_a_h': self.BarrierAH.Text, 'barrier_a_v': self.BarrierAV.Text,
            'barrier_b_h': self.BarrierBH.Text, 'barrier_b_v': self.BarrierBV.Text,
            'support_h': self.SupportH.Text, 'support_v': self.SupportV.Text,
            'support_spacing': self.SupportSpacing.Text,
            'support_rotation_x': self.SupportRotationX.Text,
            'support_rotation_y': self.SupportRotationY.Text,
            'support_rotation_z': self.SupportRotationZ.Text,
            'adaptive_overlap': self.AdaptiveOverlap.Text,
        }
        settings = dict([(key, read_number(values, key, label)) for key, label in [
            ('rail_h', u'轨道距中心线水平距离'), ('rail_v', u'轨道垂直偏移'),
            ('barrier_a_h', u'挡板 A 水平偏移'), ('barrier_a_v', u'挡板 A 垂直偏移'),
            ('barrier_b_h', u'挡板 B 水平偏移'), ('barrier_b_v', u'挡板 B 垂直偏移'),
            ('support_h', u'支柱距中心线水平距离'), ('support_v', u'支柱垂直偏移'),
            ('support_spacing', u'支柱间距'), ('adaptive_overlap', u'自适应构件端部搭接量'),
        ]])
        settings['support_rotation_x'] = read_number(values, 'support_rotation_x', u'支柱绕 X 轴旋转角', u'度')
        settings['support_rotation_y'] = read_number(values, 'support_rotation_y', u'支柱绕 Y 轴旋转角', u'度')
        settings['support_rotation_z'] = read_number(values, 'support_rotation_z', u'支柱绕 Z 轴旋转角', u'度')
        if settings['support_spacing'] <= 0:
            raise Exception(u'接触网支柱间距必须大于 0 mm。')
        if settings['rail_h'] < 0:
            raise Exception(u'轨道距中心线水平距离不能小于 0 mm。')
        if settings['support_h'] < 0:
            raise Exception(u'支柱距中心线水平距离不能小于 0 mm。')
        if settings['adaptive_overlap'] < 0:
            raise Exception(u'自适应构件端部搭接量不能小于 0 mm。')
        return settings

    def _layout_paths(self, base_path, settings):
        return (
            OffsetPath(base_path, -settings['rail_h'], settings['rail_v']),
            OffsetPath(base_path, settings['rail_h'], settings['rail_v']),
            OffsetPath(base_path, settings['barrier_a_h'], settings['barrier_a_v']),
            OffsetPath(base_path, settings['barrier_b_h'], settings['barrier_b_v']),
            OffsetPath(base_path, -settings['support_h'], settings['support_v']),
            OffsetPath(base_path, settings['support_h'], settings['support_v'])
        )

    def _estimate_layout_instances(self, paths, settings, preview):
        rail_a_path, rail_b_path, barrier_a_path, barrier_b_path, support_a_path, support_b_path = paths
        point_counts = [
            placement_point_count(self.symbols['rail']),
            placement_point_count(self.symbols['rail']),
            placement_point_count(self.symbols['barrier_a']),
            placement_point_count(self.symbols['barrier_b'])
        ]
        adaptive_paths = [rail_a_path, rail_b_path, barrier_a_path, barrier_b_path]
        adaptive_count = sum([
            adaptive_instance_count(adaptive_paths[index], point_counts[index])
            for index in range(len(adaptive_paths))
        ])
        support_count = len(support_distances(support_a_path.length, settings['support_spacing'], preview))
        support_count += len(support_distances(support_b_path.length, settings['support_spacing'], preview))
        return point_counts, adaptive_count + support_count, support_count

    def _place_layout(self, paths, settings, created_ids, preview=False, point_counts=None, progress_callback=None):
        rail_a_path, rail_b_path, barrier_a_path, barrier_b_path, support_a_path, support_b_path = paths
        point_counts = point_counts or [None, None, None, None]
        place_adaptive_along_path(self.symbols['rail'], rail_a_path, u'轨道 A 自适应族', settings['adaptive_overlap'], created_ids, point_counts[0], progress_callback)
        place_adaptive_along_path(self.symbols['rail'], rail_b_path, u'轨道 B 自适应族', settings['adaptive_overlap'], created_ids, point_counts[1], progress_callback)
        place_adaptive_along_path(self.symbols['barrier_a'], barrier_a_path, u'桥边挡板 A 自适应族', settings['adaptive_overlap'], created_ids, point_counts[2], progress_callback)
        place_adaptive_along_path(self.symbols['barrier_b'], barrier_b_path, u'桥边挡板 B 自适应族', settings['adaptive_overlap'], created_ids, point_counts[3], progress_callback)
        support_start = len(created_ids)
        place_supports(self.symbols['support'], support_a_path, settings['support_spacing'], settings['support_rotation_x'], settings['support_rotation_y'], settings['support_rotation_z'], 1.0, created_ids, preview, progress_callback)
        place_supports(self.symbols['support'], support_b_path, settings['support_spacing'], settings['support_rotation_x'], settings['support_rotation_y'], settings['support_rotation_z'], -1.0, created_ids, preview, progress_callback)
        return len(created_ids) - support_start

    def _delete_preview_in_transaction(self):
        valid_ids = [element_id for element_id in self.preview_ids if doc.GetElement(element_id) is not None]
        if not valid_ids:
            return 0
        ids = List[ElementId]()
        for element_id in valid_ids:
            ids.Add(element_id)
        doc.Delete(ids)
        return len(valid_ids)

    def _delete_centerline_in_transaction(self):
        valid_ids = [element_id for element_id in self.centerline_ids if doc.GetElement(element_id) is not None]
        if not valid_ids:
            return 0
        ids = List[ElementId]()
        for element_id in valid_ids:
            ids.Add(element_id)
        doc.Delete(ids)
        return len(valid_ids)

    def _select_created(self, created_ids):
        selected_ids = List[ElementId]()
        for element_id in created_ids:
            selected_ids.Add(element_id)
        uidoc.Selection.SetElementIds(selected_ids)

    def PreviewPlacement(self, sender, args):
        def action():
            settings = self._settings()
            preview_base_path = first_path_segments(self.center_path, 2)
            paths = self._layout_paths(preview_base_path, settings)
            created_ids = []
            with revit.Transaction(u'桥梁接触网布置预览（前两段）'):
                removed_count = self._delete_preview_in_transaction()
                support_count = self._place_layout(paths, settings, created_ids, preview=True)
            self.preview_ids = list(created_ids)
            self._select_created(created_ids)
            self._set_text(self.ResultStatus, u'预览完成：已在拟合中心线前 {0} 段（{1:.2f} m）生成 {2} 个构件，其中接触网支柱 {3} 根（预览段首尾均布置）；已替换上一批预览 {4} 个。确认无误后点击“开始全部布置”。'.format(
                len(preview_base_path.curves), preview_base_path.length * 0.3048, len(created_ids), support_count, removed_count
            ))
        self._run_external_action(action, self.ResultStatus)

    def StartPlacement(self, sender, args):
        def action():
            settings = self._settings()
            paths = self._layout_paths(self.center_path, settings)
            created_ids = []
            with forms.ProgressBar(title=u'正在计算全部布置数量...', cancellable=False, step=1) as progress_bar:
                with revit.Transaction(u'桥梁接触网、轨道与挡板自动布置'):
                    point_counts, total_count, expected_support_count = self._estimate_layout_instances(paths, settings, False)
                    if total_count <= 0:
                        raise Exception(u'预计生成构件数量为 0，无法开始全部布置。')
                    progress_bar.update_progress(0, total_count)
                    started_at = time.time()
                    completed_count = [0]

                    def update_progress():
                        completed_count[0] += 1
                        elapsed = time.time() - started_at
                        remaining = elapsed * (total_count - completed_count[0]) / completed_count[0]
                        progress_bar.title = u'正在全部布置 {0}/{1}，预计剩余 {2:.0f} 秒'.format(
                            completed_count[0], total_count, max(0.0, remaining)
                        )
                        progress_bar.update_progress(completed_count[0], total_count)

                    removed_count = self._delete_preview_in_transaction()
                    support_count = self._place_layout(paths, settings, created_ids, point_counts=point_counts, progress_callback=update_progress)
                    if support_count != expected_support_count:
                        raise Exception(u'接触网支柱实际创建数量 {0} 与预估数量 {1} 不一致。'.format(
                            support_count, expected_support_count
                        ))
            self.preview_ids = []
            self._select_created(created_ids)
            self._set_text(self.ResultStatus, u'全部布置完成：框选桥面族 {0} 个，新建构件 {1} 个，其中接触网支柱 {2} 根；已清除预览 {3} 个；双侧轨道距中心线 {4:.0f} mm；双侧支柱距中心线 {5:.0f} mm，间距 {6:.2f} m，旋转 X/Y/Z={7:.1f}/{8:.1f}/{9:.1f}°。'.format(
                len(self.bridges), len(created_ids), support_count, removed_count, settings['rail_h'], settings['support_h'], settings['support_spacing'] / 1000.0, settings['support_rotation_x'], settings['support_rotation_y'], settings['support_rotation_z']
            ))
            self.StartButton.IsEnabled = False
            self.PreviewButton.IsEnabled = False
        self._run_external_action(action, self.ResultStatus)

    def CloseWizard(self, sender, args):
        self.Close()


def run():
    wizard = BridgePlacementWizard(os.path.join(os.path.dirname(__file__), 'wizard.xaml'))
    wizard.show_dialog()


try:
    run()
except OperationCanceledException:
    pass
except Exception as exception:
    details = traceback.format_exc()
    LOGGER.error(details)
    forms.alert(u'桥梁接触网布置失败：\n{0}\n\n完整错误信息：\n{1}'.format(text(exception), details), title=u'桥梁接触网布置', exitscript=False)
