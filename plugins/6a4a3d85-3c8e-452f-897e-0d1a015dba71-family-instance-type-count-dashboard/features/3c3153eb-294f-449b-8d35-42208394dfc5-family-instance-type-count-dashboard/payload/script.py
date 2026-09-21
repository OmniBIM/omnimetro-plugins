# -*- coding: utf-8 -*-
"""
工具名称: 族实例数量统计浏览器
功能描述: 按 类别 -> 族 -> 族类型 统计并浏览族实例
修复说明: 修复 WPF XAML 中 TreeView.VerticalScrollBarVisibility 未知成员异常
架构规范: 三层解耦标准 (UI层 -> 核心算法层 -> 宿主适配层)
"""

import sys
import traceback


# =====================================================================
# 第 2 层：核心业务与数据算法层
# 100% 纯 Python，禁止引用 Revit API
# =====================================================================
class CoreAlgorithm:
    """纯业务逻辑，不依赖 Revit，可跨平台移植。"""

    @staticmethod
    def _norm_name(value):
        """将空值统一显示为 <未命名>"""
        if value is None or value == "":
            return u"<未命名>"
        return value

    @staticmethod
    def filter_records(records, category_name=None, keyword=None):
        """按类别与关键字过滤实例记录。"""
        category_filter = (category_name or u"").strip()
        lower_keyword = (keyword or u"").strip().lower()

        result = []
        for record in records:
            if category_filter:
                if (record.get("category") or u"") != category_filter:
                    continue

            if lower_keyword:
                search_text = u"{} {} {} {}".format(
                    record.get("category") or u"",
                    record.get("family") or u"",
                    record.get("family_type") or u"",
                    record.get("element_id") or u""
                ).lower()

                if lower_keyword not in search_text:
                    continue

            result.append(record)

        return result

    @staticmethod
    def build_grouped_data(records):
        """
        将实例记录按 类别 -> 族 -> 族类型 分层聚合。

        返回格式：
        [
            {
                "name": "门",
                "count": 10,
                "records": [...],
                "children": [
                    {
                        "name": "单扇平开门",
                        "count": 10,
                        "records": [...],
                        "children": [
                            {
                                "name": "900x2100",
                                "count": 5,
                                "records": [...]
                            }
                        ]
                    }
                ]
            }
        ]
        """
        grouped = {}

        for record in records:
            cat_name = CoreAlgorithm._norm_name(record.get("category"))
            fam_name = CoreAlgorithm._norm_name(record.get("family"))
            type_name = CoreAlgorithm._norm_name(record.get("family_type"))

            key = (cat_name, fam_name, type_name)
            grouped.setdefault(key, []).append(record)

        # 构造多级映射
        root_map = {}
        for key, items in grouped.items():
            cat_name, fam_name, type_name = key

            # 同类型内按图元 ID 稳定排序
            items.sort(key=lambda item: item.get("element_id", 0))

            if cat_name not in root_map:
                root_map[cat_name] = {}

            if fam_name not in root_map[cat_name]:
                root_map[cat_name][fam_name] = {}

            root_map[cat_name][fam_name][type_name] = items

        result = []

        for cat_name in sorted(root_map.keys()):
            category_map = root_map[cat_name]
            category_records = []
            family_children = []

            for fam_name in sorted(category_map.keys()):
                family_map = category_map[fam_name]
                family_records = []
                type_children = []

                for type_name in sorted(family_map.keys()):
                    type_records = family_map[type_name]

                    type_children.append({
                        "name": type_name,
                        "records": type_records,
                        "count": len(type_records),
                    })

                    family_records.extend(type_records)

                family_children.append({
                    "name": fam_name,
                    "records": family_records,
                    "count": len(family_records),
                    "children": type_children,
                })

                category_records.extend(family_records)

            result.append({
                "name": cat_name,
                "records": category_records,
                "count": len(category_records),
                "children": family_children,
            })

        return result


# =====================================================================
# 第 3 层：宿主 API 适配层
# 当前封装 Revit API，未来可替换为 Rhino / BIMBase 适配器
# =====================================================================
class RevitHostAdapter:
    """Revit 模型读取、过滤与选择联动。"""

    def __init__(self):
        from pyrevit import revit, DB

        self.doc = revit.doc
        self.uidoc = revit.uidoc
        self.DB = DB

    def collect_family_instances(self):
        """
        收集当前 Revit 文档中的模型类族实例。
        如需统计注释族、标题栏等，可删除 CategoryType.Model 过滤条件。
        """
        if self.doc is None:
            return []

        db = self.DB
        collector = db.FilteredElementCollector(self.doc) \
            .OfClass(db.FamilyInstance) \
            .WhereElementIsNotElementType()

        records = []

        for element in collector:
            try:
                if element.Category is None:
                    continue

                # 这里只统计模型类族实例
                if element.Category.CategoryType != db.CategoryType.Model:
                    continue

                family_symbol = element.Symbol
                if family_symbol is None:
                    continue

                family = family_symbol.Family
                family_name = family.Name if family else family_symbol.Name

                level_name = u""
                try:
                    if element.Level is not None:
                        level_name = element.Level.Name
                except Exception:
                    level_name = u""

                records.append({
                    "category": element.Category.Name or u"",
                    "family": family_name or u"",
                    "family_type": family_symbol.Name or u"",
                    "level": level_name,
                    "element_id": element.Id.IntegerValue,
                })
            except Exception:
                # 单个族实例读取失败时跳过，不影响整体统计
                traceback.print_exc()
                continue

        return records

    def select_element_ids(self, element_ids):
        """在 Revit 当前视图中选中指定图元，属于 UI 联动，不写模型。"""
        if not self.uidoc or not element_ids:
            return 0

        try:
            id_objs = [self.DB.ElementId(elem_id) for elem_id in element_ids]
            self.uidoc.Selection.SetElementIds(id_objs)
            return len(id_objs)
        except Exception:
            traceback.print_exc()
            return 0


# =====================================================================
# 第 1 层：GUI 交互层
# 内嵌 XAML + WPF 界面
# =====================================================================
import clr

try:
    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")
    clr.AddReference("System.Data")
except Exception:
    pass

from System.Data import DataTable
from System.Windows.Controls import TreeViewItem
from pyrevit.forms import WPFWindow


XAML_LAYOUT = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="族实例数量统计浏览器"
        Height="720"
        Width="1080"
        MinHeight="500"
        MinWidth="800"
        WindowStartupLocation="CenterScreen"
        FontFamily="Microsoft YaHei">

    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- 头部筛选区 -->
        <StackPanel Grid.Row="0"
                    Orientation="Horizontal"
                    Margin="0,0,0,8">

            <TextBlock Text="族实例数量统计浏览器"
                       FontSize="16"
                       FontWeight="Bold"
                       VerticalAlignment="Center"
                       Margin="0,0,24,0"/>

            <TextBlock Text="类别:"
                       VerticalAlignment="Center"
                       Margin="0,0,6,0"/>

            <ComboBox x:Name="cb_category"
                      Width="160"
                      Margin="0,0,12,0"
                      SelectedIndex="0"/>

            <TextBlock Text="关键字:"
                       VerticalAlignment="Center"
                       Margin="0,0,6,0"/>

            <TextBox x:Name="tb_keyword"
                     Width="180"
                     VerticalContentAlignment="Center"
                     Margin="0,0,8,0"/>

            <Button Content="应用筛选"
                    Padding="10,4"
                    Margin="0,0,8,0"
                    Click="OnApplyFilter"/>

            <Button Content="重新统计"
                    Padding="10,4"
                    Margin="0,0,8,0"
                    Click="OnReload"/>

            <Button Content="选中当前节点实例"
                    Padding="10,4"
                    Margin="0,0,8,0"
                    Click="OnSelectInRevit"/>

            <Button Content="关闭"
                    Padding="10,4"
                    IsCancel="True"/>
        </StackPanel>

        <!-- 主体：左侧分组树 + 右侧实例明细表 -->
        <Grid Grid.Row="1">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="380"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>

            <GroupBox Header="族实例分组统计"
                      Grid.Column="0"
                      Margin="0,0,8,0"
                      Padding="4">

                <TreeView x:Name="tree_group"
                          SelectedItemChanged="OnTreeSelectionChanged"/>
            </GroupBox>

            <GroupBox Header="实例明细"
                      Grid.Column="1"
                      Margin="8,0,0,0"
                      Padding="4">

                <DataGrid x:Name="dg_instances"
                          AutoGenerateColumns="True"
                          IsReadOnly="True"
                          CanUserAddRows="False"
                          CanUserDeleteRows="False"
                          SelectionMode="Extended"
                          RowBackground="#F9F9F9"
                          AlternatingRowBackground="#FFFFFF"
                          GridLinesVisibility="Horizontal"
                          HorizontalGridLinesBrush="#DDDDDD"
                          HeadersVisibility="Column"/>
            </GroupBox>
        </Grid>

        <!-- 底部状态栏 -->
        <Border Grid.Row="2"
                BorderBrush="#CCCCCC"
                BorderThickness="0,1,0,0"
                Padding="4"
                Margin="0,8,0,0">

            <TextBlock x:Name="tb_status"
                       Text="就绪"/>
        </Border>
    </Grid>
</Window>
"""


class FamilyInstanceStatsWindow(WPFWindow):
    """族实例数量统计浏览器主窗口。"""

    def __init__(self):
        WPFWindow.__init__(self, XAML_LAYOUT, literal_string=True)

        self.adapter = RevitHostAdapter()
        self.records = []
        self.filtered_records = []
        self.current_records = []

        self.LoadData()

    def LoadData(self):
        """从 Revit 重新读取模型族实例。"""
        try:
            records = self.adapter.collect_family_instances()
        except Exception as ex:
            traceback.print_exc()
            from pyrevit import forms
            forms.alert(u"读取族实例失败:\n{}".format(ex), title="错误")
            return

        self.records = records

        # 刷新类别筛选下拉框
        category_names = sorted(
            set(CoreAlgorithm._norm_name(item.get("category")) for item in records)
        )

        self.cb_category.Items.Clear()
        self.cb_category.Items.Add(u"全部分类")
        for cat_name in category_names:
            self.cb_category.Items.Add(cat_name)

        self.cb_category.SelectedIndex = 0
        self.tb_keyword.Text = u""

        self.ApplyFilter()

    def ApplyFilter(self):
        """根据类别、关键字过滤并重建树。"""
        if not self.records:
            self.filtered_records = []
            self.RebuildTree([])
            self.FillGrid([])
            self.UpdateSummary()
            return

        category_name = None
        selected_item = self.cb_category.SelectedItem

        if selected_item is not None:
            selected_text = u"{}".format(selected_item)
            if selected_text != u"全部分类":
                category_name = selected_text

        keyword = self.tb_keyword.Text

        filtered = CoreAlgorithm.filter_records(
            self.records,
            category_name=category_name,
            keyword=keyword
        )

        self.filtered_records = filtered
        self.RebuildTree(filtered)
        self.FillGrid(filtered)
        self.UpdateSummary()

    def RebuildTree(self, filtered_records):
        """构建 类别 -> 族 -> 族类型 的分层树。"""
        self.tree_group.Items.Clear()

        root_node = TreeViewItem()
        root_node.Header = u"当前筛选结果（{} 个实例）".format(len(filtered_records))
        root_node.Tag = filtered_records
        self.tree_group.Items.Add(root_node)

        grouped = CoreAlgorithm.build_grouped_data(filtered_records)

        for category_item in grouped:
            category_node = TreeViewItem()
            category_node.Header = u"{}（{}）".format(
                category_item["name"],
                category_item["count"]
            )
            category_node.Tag = category_item["records"]
            root_node.Items.Add(category_node)

            for family_item in category_item["children"]:
                family_node = TreeViewItem()
                family_node.Header = u"{}（{}）".format(
                    family_item["name"],
                    family_item["count"]
                )
                family_node.Tag = family_item["records"]
                category_node.Items.Add(family_node)

                for type_item in family_item["children"]:
                    type_node = TreeViewItem()
                    type_node.Header = u"{}（{}）".format(
                        type_item["name"],
                        type_item["count"]
                    )
                    type_node.Tag = type_item["records"]
                    family_node.Items.Add(type_node)

        root_node.IsExpanded = True

    def FillGrid(self, records):
        """将当前节点实例写入 DataGrid。"""
        self.dg_instances.ItemsSource = None
        self.current_records = list(records) if records else []

        table = DataTable()
        table.Columns.Add(u"序号")
        table.Columns.Add(u"图元ID")
        table.Columns.Add(u"类别")
        table.Columns.Add(u"族名称")
        table.Columns.Add(u"族类型")
        table.Columns.Add(u"标高")

        for index, record in enumerate(self.current_records, start=1):
            row = table.NewRow()
            row[u"序号"] = u"{}".format(index)
            row[u"图元ID"] = u"{}".format(record.get("element_id") or u"")
            row[u"类别"] = u"{}".format(record.get("category") or u"")
            row[u"族名称"] = u"{}".format(record.get("family") or u"")
            row[u"族类型"] = u"{}".format(record.get("family_type") or u"")
            row[u"标高"] = u"{}".format(record.get("level") or u"")
            table.Rows.Add(row)

        self.dg_instances.ItemsSource = table.DefaultView
        self.UpdateSummary()

    def UpdateSummary(self):
        """更新状态栏统计信息。"""
        total_count = len(self.records)
        filtered_count = len(self.filtered_records)
        current_count = len(self.current_records)

        self.tb_status.Text = u"已统计族实例: {} | 过滤后: {} | 当前节点/筛选结果: {}".format(
            total_count,
            filtered_count,
            current_count
        )

    def OnApplyFilter(self, sender, e):
        """点击“应用筛选”。"""
        self.ApplyFilter()

    def OnReload(self, sender, e):
        """点击“重新统计”。"""
        self.LoadData()

    def OnTreeSelectionChanged(self, sender, args):
        """点击左侧树节点时，刷新右侧实例明细。"""
        selected_node = self.tree_group.SelectedItem

        if selected_node is None:
            return

        if getattr(selected_node, "Tag", None) is not None:
            self.FillGrid(selected_node.Tag)

    def OnSelectInRevit(self, sender, e):
        """选中当前树节点的族实例。"""
        if not self.current_records:
            from pyrevit import forms
            forms.alert(u"当前没有可选择的族实例。", title="提示")
            return

        element_ids = [item.get("element_id") for item in self.current_records]
        element_ids = [elem_id for elem_id in element_ids if elem_id]

        if not element_ids:
            from pyrevit import forms
            forms.alert(u"当前没有有效的图元 ID。", title="提示")
            return

        selected_count = self.adapter.select_element_ids(element_ids)

        from pyrevit import forms
        forms.alert(
            u"已在 Revit 中选中 {} 个族实例。".format(selected_count),
            title="选择完成"
        )


def main():
    try:
        window = FamilyInstanceStatsWindow()
        window.ShowDialog()
    except Exception as ex:
        traceback.print_exc()
        from pyrevit import forms
        forms.alert(
            u"族实例数量统计浏览器启动失败:\n{}".format(ex),
            title="错误"
        )


if __name__ == "__main__":
    main()