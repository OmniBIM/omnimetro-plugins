# -*- coding: utf-8 -*-
"""
机电图元所属系统批量指定工具
功能概述:
    选择当前 Revit 中的风管/管道/桥架/线管等机电图元，
    通过 GUI 指定目标 Revit MEP SystemType，批量分配所属系统。

架构说明:
    第 1 层: GUI 交互层       WPFWindow + XAML
    第 2 层: 核心业务算法层    纯 Python：规则校验、状态生成、可移植
    第 3 层: Revit API 适配层  封装 Revit 读取/事务/系统创建与写入
"""

import os
import sys
import traceback
import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import BuiltInCategory, Category, ElementId, ElementSet, FilteredElementCollector, Transaction
from pyrevit import revit, forms
from pyrevit.forms import WPFWindow


# ======================================================================
#  第 2 层：核心业务与算法层（纯 Python，零 Revit API 直接耦合）
# ======================================================================
class CoreAlgorithm:
    """纯 Python 业务算法，后续平移到 Rhino/Blender/国产BIM平台时可原样复用。"""

    # 构件类别标识
    TAG_DUCT = "DUCT"
    TAG_PIPE = "PIPE"
    TAG_CABLE = "CABLE"

    STATUS_READY = "待执行"
    STATUS_SKIP = "跳过"
    STATUS_ERROR = "异常"

    @staticmethod
    def make_preview(row, target_item):
        """
        根据原始数据 + 目标系统，生成前置预览行。
        row: 从宿主层采集出来的纯字典
        target_item: 从系统类型列表中获得的目标系统字典
        """
        preview = dict(row)
        target_name = target_item.get("display_name", "")
        allowed_tags = target_item.get("allowed_tags", [])

        if preview.get("category_tag") not in allowed_tags:
            preview["target_system"] = "—"
            preview["status"] = CoreAlgorithm.STATUS_SKIP
            preview["validation"] = "目标系统类别与构件类别不匹配"
            preview["preview_valid"] = False
        else:
            preview["target_system"] = target_name
            preview["status"] = CoreAlgorithm.STATUS_READY
            preview["validation"] = "系统规则校验通过"
            preview["preview_valid"] = True

        return preview

    @staticmethod
    def count_summary(data_items):
        """统计扫描、待执行、跳过/异常数量。"""
        total = len(data_items)
        ready = len([x for x in data_items if x.get("status") == CoreAlgorithm.STATUS_READY])
        skipped_or_error = total - ready
        return total, ready, skipped_or_error

    @staticmethod
    def build_error_message(errors, max_show=12):
        if not errors:
            return "无错误"
        shown = errors[:max_show]
        more = "" if len(errors) <= max_show else "\n... 其余 {0} 条错误已省略".format(len(errors) - max_show)
        return "\n".join(shown) + more


# ======================================================================
#  第 3 层：宿主 API 适配层（Revit API）
# ======================================================================
class RevitHostAdapter:
    """Revit 宿主适配层。未来移植到其他三维 BIM 平台时只需替换本层。"""

    # 尝试加载 Revit API 中与系统类型相关的动态类型
    @staticmethod
    def _safe_import(module_name, type_name):
        try:
            module = __import__(module_name, fromlist=[type_name])
            return getattr(module, type_name)
        except Exception:
            return None

    def __init__(self):
        self.doc = revit.doc
        self.uidoc = revit.uidoc

        # 动态获取 MEP 系统类型 / MEP 系统类
        self._mech_system_type_cls = self._safe_import(
            "Autodesk.Revit.DB.Mechanical", "MechanicalSystemType"
        )
        self._piping_system_type_cls = self._safe_import(
            "Autodesk.Revit.DB.Plumbing", "PipingSystemType"
        )
        self._cable_system_type_cls = self._safe_import(
            "Autodesk.Revit.DB.Electrical", "CableTrayConduitSystemType"
        )

        self._mech_system_cls = self._safe_import(
            "Autodesk.Revit.DB.Mechanical", "MechanicalSystem"
        )
        self._piping_system_cls = self._safe_import(
            "Autodesk.Revit.DB.Plumbing", "PipingSystem"
        )
        self._cable_system_cls = self._safe_import(
            "Autodesk.Revit.DB.Electrical", "CableTrayConduitSystem"
        )

        # 构件类别 -> 所属系统类别
        self._category_tag_map = {}
        self._build_category_tag_map()

    # ------------------------------------------------------------------
    # Revit 类别映射
    # ------------------------------------------------------------------
    def _build_category_tag_map(self):
        category_names = {
            CoreAlgorithm.TAG_DUCT: [
                "OST_DuctCurves",
                "OST_DuctFitting",
                "OST_DuctAccessory",
                "OST_DuctTerminal",
                "OST_FlexDuctCurves",
            ],
            CoreAlgorithm.TAG_PIPE: [
                "OST_PipeCurves",
                "OST_PipeFitting",
                "OST_PipeAccessory",
                "OST_FlexPipeCurves",
            ],
            CoreAlgorithm.TAG_CABLE: [
                "OST_CableTray",
                "OST_CableTrayFitting",
                "OST_Conduit",
                "OST_ConduitFitting",
            ],
        }

        for tag, names in category_names.items():
            for name in names:
                try:
                    if not hasattr(BuiltInCategory, name):
                        continue
                    bic = getattr(BuiltInCategory, name)
                    cat = Category.GetCategory(self.doc, bic)
                    if cat is not None:
                        self._category_tag_map[cat.Id.IntegerValue] = tag
                except Exception:
                    continue

        return self._category_tag_map

    def _get_tag_from_element(self, element):
        if element is None or element.Category is None:
            return None
        cat_id = element.Category.Id.IntegerValue
        return self._category_tag_map.get(cat_id)

    # ------------------------------------------------------------------
    # 采集数据
    # ------------------------------------------------------------------
    def collect_elements(self, source_mode="selection"):
        """
        采集可处理的 MEP 图元原始预览数据。
        source_mode: selection / activeview / allmodel
        """
        doc = self.doc

        if source_mode == "activeview":
            if doc.ActiveView is None:
                return []
            collector = FilteredElementCollector(doc, doc.ActiveView.Id)
        elif source_mode == "allmodel":
            collector = FilteredElementCollector(doc)
        else:
            selected_ids = list(self.uidoc.Selection.GetElementIds())
            if not selected_ids:
                return []
            collector = FilteredElementCollector(doc, selected_ids)

        rows = []
        try:
            elements = collector.WhereElementIsNotElementType().ToElements()
        except Exception:
            elements = []

        for el in elements:
            try:
                tag = self._get_tag_from_element(el)
                if not tag:
                    continue

                original_system = self.get_original_system_name(el)
                type_name = self.get_element_display_name(el)

                rows.append({
                    "id": "ID {}".format(el.Id.IntegerValue),
                    "native_id": el.Id.IntegerValue,
                    "category": el.Category.Name if el.Category else "未分类",
                    "name": type_name,
                    "original_system": original_system,
                    "target_system": "",
                    "status": CoreAlgorithm.STATUS_READY,
                    "validation": "",
                    "category_tag": tag,
                    "native_element": el,
                })
            except Exception:
                continue

        return rows

    def get_element_display_name(self, element):
        type_name = ""
        try:
            type_param = element.get_Parameter(BuiltInCategory.OST_ElemType)
            if type_param is not None:
                type_name = type_param.AsValueString()
        except Exception:
            type_name = ""

        if not type_name:
            try:
                type_name = element.Name
            except Exception:
                type_name = element.GetType().Name

        return type_name or "未知构件"

    def get_original_system_name(self, element):
        """返回构件当前连接的系统名称。"""
        system_names = []
        try:
            mep_model = getattr(element, "MEPModel", None)
            if mep_model is None:
                return "无 MEPModel"

            connector_manager = getattr(mep_model, "ConnectorManager", None)
            if connector_manager is None:
                return "无连接件"

            for conn in connector_manager.Connectors:
                system = getattr(conn, "MEPSystem", None)
                if system is not None:
                    try:
                        system_names.append(system.Name)
                    except Exception:
                        system_names.append("已连接系统")

            if not system_names:
                return "未连接系统"

            return " | ".join(sorted(set(system_names)))
        except Exception:
            return "系统读取失败"

    # ------------------------------------------------------------------
    # 加载可用的 MEP 系统类型
    # ------------------------------------------------------------------
    def load_system_type_items(self):
        system_items = []

        type_groups = [
            (self._mech_system_type_cls, CoreAlgorithm.TAG_DUCT, "风管/机械系统"),
            (self._piping_system_type_cls, CoreAlgorithm.TAG_PIPE, "管道/管路系统"),
            (self._cable_system_type_cls, CoreAlgorithm.TAG_CABLE, "桥架/线管系统"),
        ]

        for cls, tag, prefix in type_groups:
            if cls is None:
                continue
            try:
                for st in FilteredElementCollector(self.doc).OfClass(cls):
                    try:
                        display_name = "{0} | {1}".format(prefix, st.Name)
                        system_items.append({
                            "display_name": display_name,
                            "type_id": st.Id,
                            "allowed_tags": [tag],
                            "tag": tag,
                        })
                    except Exception:
                        continue
            except Exception:
                continue

        system_items.sort(key=lambda x: x["display_name"])
        return system_items

    # ------------------------------------------------------------------
    # 系统判断帮助
    # ------------------------------------------------------------------
    def _get_element_system(self, element):
        try:
            mep_model = getattr(element, "MEPModel", None)
            if mep_model is None:
                return None
            connector_manager = getattr(mep_model, "ConnectorManager", None)
            if connector_manager is None:
                return None
            for conn in connector_manager.Connectors:
                system = getattr(conn, "MEPSystem", None)
                if system is not None:
                    return system
        except Exception:
            return None
        return None

    def _get_system_type_id(self, system):
        try:
            system_type_obj = getattr(system, "SystemType", None)
            if system_type_obj is None:
                return None

            if isinstance(system_type_obj, ElementId):
                return system_type_obj

            if hasattr(system_type_obj, "Id"):
                return system_type_obj.Id

            return system_type_obj
        except Exception:
            return None

    def _is_same_system_type(self, system, target_type_id):
        if system is None or target_type_id is None:
            return False

        system_type_id = self._get_system_type_id(system)
        if system_type_id is None:
            return False

        try:
            if isinstance(system_type_id, ElementId) and isinstance(target_type_id, ElementId):
                return system_type_id == target_type_id
            try:
                return int(system_type_id.IntegerValue) == int(target_type_id.IntegerValue)
            except Exception:
                try:
                    return int(system_type_id) == int(target_type_id)
                except Exception:
                    return False
        except Exception:
            return system_type_id == target_type_id

    # ------------------------------------------------------------------
    # 创建 / 添加系统
    # ------------------------------------------------------------------
    def _create_system(self, tag, system_type_id, element_set):
        if tag == CoreAlgorithm.TAG_DUCT:
            if self._mech_system_cls is None:
                raise RuntimeError("当前 Revit 版本中未找到 MechanicalSystem API，无法创建风管系统。")
            return self._mech_system_cls.Create(self.doc, system_type_id, element_set)

        if tag == CoreAlgorithm.TAG_PIPE:
            if self._piping_system_cls is None:
                raise RuntimeError("当前 Revit 版本中未找到 PipingSystem API，无法创建管道系统。")
            return self._piping_system_cls.Create(self.doc, system_type_id, element_set)

        if tag == CoreAlgorithm.TAG_CABLE:
            if self._cable_system_cls is None:
                raise RuntimeError("当前 Revit 版本中未找到 CableTrayConduitSystem API，无法创建桥架/线管系统。")
            return self._cable_system_cls.Create(self.doc, system_type_id, element_set)

        raise RuntimeError("不支持的机电系统类别：{0}".format(tag))

    # ------------------------------------------------------------------
    # 事务化批量写入
    # ------------------------------------------------------------------
    def apply_modifications(self, data_items, target_type):
        """
        对预览中状态为“待执行”的数据，在事务中统一修改。
        若中途出现错误则整体回滚，保证模型不产生半修改状态。
        """
        if not data_items or not target_type:
            return 0, ["没有可执行的数据或目标系统为空。"]

        doc = self.doc
        target_id = target_type["type_id"]
        allowed_tags = target_type.get("allowed_tags", [])

        valid_items = [
            x for x in data_items
            if x.get("status") == CoreAlgorithm.STATUS_READY
            and x.get("category_tag") in allowed_tags
        ]

        if not valid_items:
            return 0, ["没有与目标系统匹配的可执行图元。"]

        txn = Transaction(doc, "机电图元所属系统批量指定")
        txn.Start()

        created_systems = {}
        errors = []
        success_count = 0

        try:
            for item in valid_items:
                element = item["native_element"]
                tag = item["category_tag"]
                elem_id = item.get("native_id", element.Id.IntegerValue)

                try:
                    old_system = self._get_element_system(element)

                    # 已经属于目标系统类型时，视作成功且无需重复创建
                    if old_system is not None and self._is_same_system_type(old_system, target_id):
                        success_count += 1
                        continue

                    # 先从旧系统移除当前图元
                    if old_system is not None:
                        remove_set = ElementSet()
                        remove_set.Insert(element)
                        old_system.Remove(remove_set)

                    # 优先复用本次操作已创建的同类别系统，避免产生大量冗余系统
                    if tag not in created_systems or created_systems[tag] is None:
                        element_set = ElementSet()
                        element_set.Insert(element)
                        created_systems[tag] = self._create_system(tag, target_id, element_set)
                    else:
                        add_set = ElementSet()
                        add_set.Insert(element)
                        created_systems[tag].Add(add_set)

                    success_count += 1

                except Exception as ex:
                    errors.append("ID {0} 执行失败：{1}".format(elem_id, ex))

            if errors:
                if txn.HasStarted():
                    txn.RollBack()
                return 0, errors

            if txn.HasStarted():
                txn.Commit()

            return success_count, []

        except Exception as ex:
            if txn.HasStarted():
                txn.RollBack()
            return 0, [str(ex)]


# ======================================================================
#  第 1 层：GUI 交互层
# ======================================================================
XAML_LAYOUT = r"""
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="机电图元所属系统批量指定工具"
    Height="650"
    Width="1080"
    WindowStartupLocation="CenterScreen"
    FontFamily="Microsoft YaHei"
    FontSize="12">

    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- 头部信息区 -->
        <StackPanel Grid.Row="0" Margin="0,0,0,10">
            <TextBlock Text="机电图元所属系统批量指定工具" FontSize="16" FontWeight="Bold" Foreground="#3A3A3A"/>
            <TextBlock Text="支持风管、管道、桥架、线管等机电图元；执行前提供系统对比预览与异常拦截。" 
                       FontSize="11" Foreground="#808080" Margin="0,4,0,0"/>
        </StackPanel>

        <!-- 参数控制区 -->
        <Border Grid.Row="1" Padding="10" Margin="0,0,0,10" Background="#F5F7FA" BorderBrush="#DDDDDD" BorderThickness="1" CornerRadius="4">
            <StackPanel>
                <StackPanel Orientation="Horizontal" Margin="0,0,0,8">
                    <TextBlock Text="操作范围：" VerticalAlignment="Center" Margin="0,0,8,0"/>
                    <RadioButton x:Name="rb_selection" Content="当前选中图元" GroupName="source_scope" IsChecked="True" VerticalAlignment="Center"/>
                    <RadioButton x:Name="rb_activeview" Content="当前视图可见 MEP 图元" GroupName="source_scope" Margin="18,0,0,0" VerticalAlignment="Center"/>
                    <RadioButton x:Name="rb_allmodel" Content="全模型 MEP 图元" GroupName="source_scope" Margin="18,0,0,0" VerticalAlignment="Center"/>
                    <Button x:Name="btn_refresh" Content="刷新扫描" Padding="14,4" Margin="30,0,0,0" Click="OnRefreshPreview"/>
                </StackPanel>

                <StackPanel Orientation="Horizontal" Margin="0,0,0,4">
                    <TextBlock Text="目标所属系统类型：" VerticalAlignment="Center" Margin="0,0,8,0"/>
                    <ComboBox x:Name="cmb_system"
                              Width="360"
                              Height="26"
                              DisplayMemberPath="display_name"
                              SelectionChanged="OnSystemSelectionChanged"
                              IsTextSearchEnabled="True"/>
                    <TextBlock x:Name="txt_scope_warning"
                               Text=""
                               Foreground="#C06000"
                               VerticalAlignment="Center"
                               Margin="14,0,0,0"/>
                </StackPanel>
            </StackPanel>
        </Border>

        <!-- 数据对比预览区 -->
        <GroupBox Grid.Row="2"
                  Header="执行前系统对比预览"
                  Padding="8"
                  Margin="0,0,0,8">
            <Grid>
                <DataGrid x:Name="dg_preview"
                          AutoGenerateColumns="False"
                          CanUserAddRows="False"
                          IsReadOnly="True"
                          EnableRowVirtualization="False"
                          HeadersVisibility="Column"
                          GridLinesVisibility="Horizontal"
                          AlternatingRowBackground="#FAFAFA"
                          BorderThickness="0">
                    <DataGrid.RowStyle>
                        <Style TargetType="DataGridRow">
                            <Setter Property="MinHeight" Value="28"/>
                            <Style.Triggers>
                                <DataTrigger Binding="{Binding status}" Value="跳过">
                                    <Setter Property="Background" Value="#FFF5E8C1"/>
                                    <Setter Property="Foreground" Value="#8A6D00"/>
                                </DataTrigger>
                                <DataTrigger Binding="{Binding status}" Value="异常">
                                    <Setter Property="Background" Value="#FFE8D9D9"/>
                                    <Setter Property="Foreground" Value="#A00000"/>
                                </DataTrigger>
                            </Style.Triggers>
                        </Style>
                    </DataGrid.RowStyle>

                    <DataGrid.Columns>
                        <DataGridTextColumn Header="图元ID" Binding="{Binding id}" Width="90"/>
                        <DataGridTextColumn Header="类别" Binding="{Binding category}" Width="110"/>
                        <DataGridTextColumn Header="构件/类型名称" Binding="{Binding name}" Width="200"/>
                        <DataGridTextColumn Header="当前所属系统" Binding="{Binding original_system}" Width="180"/>
                        <DataGridTextColumn Header="目标系统预览" Binding="{Binding target_system}" Width="180"/>
                        <DataGridTextColumn Header="状态" Binding="{Binding status}" Width="80"/>
                        <DataGridTextColumn Header="校验说明" Binding="{Binding validation}" Width="*"/>
                    </DataGrid.Columns>
                </DataGrid>
            </Grid>
        </GroupBox>

        <!-- 底部按钮与状态栏 -->
        <StackPanel Grid.Row="3" Orientation="Horizontal" HorizontalAlignment="Stretch">
            <TextBlock x:Name="txt_status"
                       Text="已扫描 0 项 | 待执行 0 项 | 跳过/异常 0 项"
                       VerticalAlignment="Center"
                       Foreground="#606060"
                       Margin="4,0,16,0"/>
            <Button x:Name="btn_execute"
                    Content="确认执行"
                    Padding="18,6"
                    Click="OnExecute"
                    IsEnabled="True"
                    Background="#0E6E4A"
                    Foreground="White"
                    BorderThickness="0"
                    Margin="0,0,10,0"/>
            <Button Content="取消退出"
                    Padding="18,6"
                    IsCancel="True"/>
        </StackPanel>
    </Grid>
</Window>
"""


class MainToolWindow(WPFWindow):
    """统一 GUI 交互窗口，负责采集、预览、拦截、执行、反馈。"""

    def __init__(self):
        self._loaded = False
        WPFWindow.__init__(self, XAML_LAYOUT, literal_string=True)

        self.adapter = RevitHostAdapter()
        self.raw_data = []
        self.system_items = []
        self.current_target = None
        self._loaded = True

        self.initialize_tool()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def initialize_tool(self):
        try:
            self.raw_data = self.adapter.collect_elements("selection")
            self.system_items = self.adapter.load_system_type_items()

            if not self.system_items:
                self.cmb_system.ItemsSource = []
                self.txt_scope_warning.Text = "当前 Revit 工程中未找到可用的 MEP SystemType，请联系管理员检查模型系统类型配置或选择其他图元。"
                self.update_preview()
                return

            self.cmb_system.ItemsSource = self.system_items
            if self.system_items:
                self.cmb_system.SelectedIndex = 0

            self.update_preview()
        except Exception as ex:
            forms.alert(
                "工具初始化失败：\n{0}\n\n{1}".format(ex, traceback.format_exc()),
                warn=True
            )
            self.Close()

    # ------------------------------------------------------------------
    # 刷新扫描
    # ------------------------------------------------------------------
    def OnRefreshPreview(self, sender, args):
        try:
            source_mode = "selection"
            if self.rb_activeview.IsChecked:
                source_mode = "activeview"
            elif self.rb_allmodel.IsChecked:
                source_mode = "allmodel"

            self.raw_data = self.adapter.collect_elements(source_mode)
            self.update_preview()
        except Exception as ex:
            forms.alert("刷新扫描失败：\n{0}".format(ex), warn=True)

    # ------------------------------------------------------------------
    # 目标系统切换
    # ------------------------------------------------------------------
    def OnSystemSelectionChanged(self, sender, args):
        if not self._loaded:
            return
        self.update_preview()

    # ------------------------------------------------------------------
    # 获取当前目标系统
    # ------------------------------------------------------------------
    def get_current_target(self):
        if not hasattr(self, "cmb_system"):
            return None

        if self.cmb_system is None or self.cmb_system.ItemsSource is None:
            return None

        idx = self.cmb_system.SelectedIndex
        if idx < 0 or idx >= len(self.system_items):
            return None

        return self.system_items[idx]

    # ------------------------------------------------------------------
    # 更新数据对比预览
    # ------------------------------------------------------------------
    def update_preview(self):
        if not self._loaded:
            return

        target_item = self.get_current_target()
        if not target_item:
            self.dg_preview.ItemsSource = []
            self.txt_status.Text = "已扫描 {0} 项 | 请选择目标所属系统".format(len(self.raw_data))
            self.txt_scope_warning.Text = "目标系统为空，请从下拉列表中选择一个系统类型。"
            self.btn_execute.IsEnabled = False
            return

        preview_list = []
        for raw_item in self.raw_data:
            preview_list.append(CoreAlgorithm.make_preview(raw_item, target_item))

        self.dg_preview.ItemsSource = preview_list

        total, ready, skipped = CoreAlgorithm.count_summary(preview_list)
        self.txt_status.Text = "已扫描 {0} 项 | 待执行 {1} 项 | 跳过/异常 {2} 项".format(
            total, ready, skipped
        )
        self.txt_scope_warning.Text = ""
        self.btn_execute.IsEnabled = ready > 0

    # ------------------------------------------------------------------
    # 执行修改
    # ------------------------------------------------------------------
    def OnExecute(self, sender, args):
        target_item = self.get_current_target()
        if not target_item:
            forms.alert("目标所属系统为空，请先选择系统类型。", warn=True)
            return

        preview_list = list(self.dg_preview.ItemsSource or [])
        valid_items = [x for x in preview_list if x.get("status") == CoreAlgorithm.STATUS_READY]

        if not valid_items:
            forms.alert("没有待执行的正常项。", warn=True)
            return

        user_ok = forms.alert(
            "确定将 {0} 个机电图元指定到目标系统：\n\n{1}\n\n执行期间将自动开启 Revit 事务，若发生错误将整体回滚。".format(
                len(valid_items), target_item["display_name"]
            ),
            ok=True,
            cancel=True
        )

        if not user_ok:
            return

        success, errors = self.adapter.apply_modifications(valid_items, target_item)

        if errors:
            msg = CoreAlgorithm.build_error_message(errors)
            forms.alert("执行未完成，已安全回滚：\n{0}".format(msg), warn=True)
            return

        forms.alert(
            "批量指定所属系统完成！\n成功处理：{0} 个图元\n目标系统：{1}".format(
                success, target_item["display_name"]
            ),
            title="执行成功"
        )

        self.Close()


# ======================================================================
#  脚本运行入口
# ======================================================================
window = MainToolWindow()
window.ShowDialog()