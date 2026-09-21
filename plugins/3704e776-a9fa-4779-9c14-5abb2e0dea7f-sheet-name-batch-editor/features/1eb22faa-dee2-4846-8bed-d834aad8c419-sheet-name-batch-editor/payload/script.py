# -*- coding: utf-8 -*-
"""
工具名称: 图纸名称批量管理器
功能描述: 批量修改当前项目/所选图纸的名称，支持前缀后缀、查找替换，执行前预览冲突与只读拦截
架构规范: 三层解耦标准 (GUI层 -> 核心算法层 -> 宿主适配层)
"""

import clr
import traceback

from pyrevit import revit, DB, forms
from pyrevit.forms import WPFWindow


# ----------------------------------------------------------------------
# 【第 2 层：核心业务与算法层】(纯 Python，零 Revit API 依赖)
# ----------------------------------------------------------------------
class CoreAlgorithm:
    """纯业务逻辑引擎，未来可平移到 Rhino / Blender / 国产 BIM 平台"""

    @staticmethod
    def generate_new_sheet_name(original_name, prefix, suffix, find_text, replace_text):
        """根据前后缀和查找替换规则生成新的图纸名称"""
        if original_name is None:
            return ""
        name = original_name
        if find_text:
            name = name.replace(find_text, replace_text)
        return "{}{}{}".format(prefix, name, suffix)

    @staticmethod
    def build_preview(all_sheets, selected_ids, prefix, suffix, find_text, replace_text):
        """生成执行前对比预览数据（纯字典列表）"""
        # 1. 为所有选中图纸计算新名称
        renamed_map = {}
        for sheet in all_sheets:
            eid = sheet['element_id']
            if eid in selected_ids:
                renamed_map[eid] = CoreAlgorithm.generate_new_sheet_name(
                    sheet['original_name'], prefix, suffix, find_text, replace_text
                )

        # 2. 构建最终图纸名称 -> 所属图元ID 映射
        final_owner = {}
        for sheet in all_sheets:
            eid = sheet['element_id']
            if eid in renamed_map:
                final_name = renamed_map[eid]
            else:
                final_name = sheet['original_name']

            if final_name:
                final_owner.setdefault(final_name, []).append(eid)

        # 3. 逐项生成预览
        preview_items = []
        idx = 0
        for sheet in all_sheets:
            eid = sheet['element_id']
            if eid not in selected_ids:
                continue
            idx += 1
            original = sheet['original_name']
            new_name = renamed_map[eid]

            status = "待执行"
            message = "名称即将修改"

            if not new_name.strip():
                status = "异常"
                message = "生成后名称为空"
            elif new_name == original:
                status = "无变化"
                message = "新名称与原名称相同"
            elif sheet.get('is_readonly', False):
                status = "异常"
                message = "图纸名称参数只读，禁止写入"
            else:
                owners = final_owner.get(new_name, [])
                conflict_owners = [oid for oid in owners if oid != eid]
                if conflict_owners:
                    status = "冲突"
                    message = "目标名称与图元ID {} 重复".format(conflict_owners[0])

            preview_items.append({
                "index": idx,
                "element_id": eid,
                "sheet_number": sheet.get('sheet_number', ''),
                "category": "图纸",
                "original_name": original,
                "target_name": new_name,
                "status": status,
                "message": message,
            })

        return preview_items


# ----------------------------------------------------------------------
# 【第 3 层：宿主 API 适配层】(封装 Revit API 读写与事务)
# ----------------------------------------------------------------------
class RevitHostAdapter:
    """宿主适配器，未来平移时重写此类即可适配 Rhino / BIMBase"""

    def __init__(self):
        self.doc = revit.doc
        self.uidoc = revit.uidoc

    def collect_all_sheets(self):
        """收集当前项目中所有图纸（ViewSheet）"""
        sheets = []
        collector = DB.FilteredElementCollector(self.doc).OfClass(DB.ViewSheet)
        for sheet in collector:
            param = sheet.get_Parameter(DB.BuiltInParameter.SHEET_NAME)
            is_readonly = (param is None) or param.IsReadOnly
            sheets.append({
                "element_id": sheet.Id.IntegerValue,
                "original_name": sheet.Name,
                "sheet_number": sheet.SheetNumber,
                "is_readonly": is_readonly,
            })
        return sheets

    def collect_selected_sheet_ids(self):
        """收集当前选中图纸的 ElementId 集合"""
        selected = set()
        ids = self.uidoc.Selection.GetElementIds()
        for eid in ids:
            el = self.doc.GetElement(eid)
            if el and isinstance(el, DB.ViewSheet):
                selected.add(el.Id.IntegerValue)
        return selected

    def apply_sheet_name_changes(self, changed_items):
        """统一事务中批量写入图纸名称，失败自动回滚"""
        if not changed_items:
            return 0

        tx = DB.Transaction(self.doc, "批量修改图纸名称")
        tx.Start()
        success_count = 0
        try:
            for item in changed_items:
                el = self.doc.GetElement(DB.ElementId(item['element_id']))
                if not el:
                    continue
                param = el.get_Parameter(DB.BuiltInParameter.SHEET_NAME)
                if param and not param.IsReadOnly:
                    param.Set(str(item['target_name']))
                    success_count += 1
            tx.Commit()
        except Exception:
            tx.RollBack()
            raise
        return success_count


# ----------------------------------------------------------------------
# 【第 1 层：GUI 交互层】(统一 WPF / XAML 界面)
# ----------------------------------------------------------------------
XAML_LAYOUT = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="图纸名称批量管理器" Height="650" Width="1000" WindowStartupLocation="CenterScreen">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- 头部信息区 -->
        <StackPanel Grid.Row="0" Margin="0,0,0,8">
            <TextBlock Text="图纸名称批量管理器" FontSize="18" FontWeight="Bold"/>
            <TextBlock Text="支持前缀 / 后缀 / 查找替换，执行前自动进行名称冲突与只读锁定预检" Foreground="#666666" FontSize="12"/>
        </StackPanel>

        <!-- 参数控制区 -->
        <Border Grid.Row="1" BorderBrush="#CCCCCC" BorderThickness="1" Padding="8" Margin="0,0,0,10">
            <StackPanel>
                <StackPanel Orientation="Horizontal">
                    <TextBlock Text="操作范围:" VerticalAlignment="Center" Margin="0,0,6,0"/>
                    <ComboBox x:Name="cmb_scope" Width="130" SelectionChanged="OnScopeChanged">
                        <ComboBoxItem Content="全部图纸" IsSelected="True"/>
                        <ComboBoxItem Content="当前选中图纸"/>
                    </ComboBox>
                    <TextBlock Text="前缀:" VerticalAlignment="Center" Margin="15,0,5,0"/>
                    <TextBox x:Name="txt_prefix" Width="100"/>
                    <TextBlock Text="后缀:" VerticalAlignment="Center" Margin="15,0,5,0"/>
                    <TextBox x:Name="txt_suffix" Width="100"/>
                </StackPanel>
                <StackPanel Orientation="Horizontal" Margin="0,8,0,0">
                    <TextBlock Text="查找:" VerticalAlignment="Center" Margin="0,0,6,0"/>
                    <TextBox x:Name="txt_find" Width="120"/>
                    <TextBlock Text="替换为:" VerticalAlignment="Center" Margin="15,0,6,0"/>
                    <TextBox x:Name="txt_replace" Width="120"/>
                    <Button x:Name="btn_refresh" Content=" 刷新预览 " Padding="12,4" Margin="20,0,0,0" Click="OnRefreshPreview"/>
                </StackPanel>
            </StackPanel>
        </Border>

        <!-- 数据对比预览区 -->
        <DataGrid Grid.Row="2" x:Name="dg_preview" AutoGenerateColumns="False" CanUserAddRows="False"
                  IsReadOnly="True" HeadersVisibility="Column" GridLinesVisibility="All" AlternatingRowBackground="#F7F7F7">
            <DataGrid.RowStyle>
                <Style TargetType="DataGridRow">
                    <Style.Triggers>
                        <DataTrigger Binding="{Binding [status]}" Value="异常">
                            <Setter Property="Background" Value="#FFFFCCCC"/>
                        </DataTrigger>
                        <DataTrigger Binding="{Binding [status]}" Value="冲突">
                            <Setter Property="Background" Value="#FFFFCCCC"/>
                        </DataTrigger>
                    </Style.Triggers>
                </Style>
            </DataGrid.RowStyle>
            <DataGrid.Columns>
                <DataGridTextColumn Header="序号" Binding="{Binding [index]}" Width="45"/>
                <DataGridTextColumn Header="图元ID" Binding="{Binding [element_id]}" Width="65"/>
                <DataGridTextColumn Header="图纸编号" Binding="{Binding [sheet_number]}" Width="85"/>
                <DataGridTextColumn Header="类别" Binding="{Binding [category]}" Width="50"/>
                <DataGridTextColumn Header="原始名称" Binding="{Binding [original_name]}" Width="*"/>
                <DataGridTextColumn Header="目标名称" Binding="{Binding [target_name]}" Width="*"/>
                <DataGridTextColumn Header="执行状态" Binding="{Binding [status]}" Width="75"/>
                <DataGridTextColumn Header="说明" Binding="{Binding [message]}" Width="*"/>
            </DataGrid.Columns>
        </DataGrid>

        <!-- 底部操作与反馈区 -->
        <Border Grid.Row="3" BorderBrush="#CCCCCC" BorderThickness="0,1,0,0" Padding="0,10,0,0" Margin="0,10,0,0">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel Grid.Column="0" VerticalAlignment="Center">
                    <CheckBox x:Name="chk_only_normal" Content="仅执行正常项" IsChecked="True" Foreground="#333333"/>
                    <TextBlock x:Name="txt_status" Text="已扫描 0 项 | 待修改 0 项 | 发现异常 0 项" Foreground="#888888" FontSize="12" Margin="0,6,0,0"/>
                </StackPanel>
                <StackPanel Grid.Column="1" Orientation="Horizontal" VerticalAlignment="Center">
                    <Button x:Name="btn_execute" Content=" 确认执行 " Padding="18,6" Margin="0,0,10,0" Background="#2D7D46" Foreground="White" BorderThickness="0" Click="OnExecute"/>
                    <Button Content=" 取消 " Padding="18,6" IsCancel="True"/>
                </StackPanel>
            </Grid>
        </Border>
    </Grid>
</Window>
"""


class MainToolWindow(WPFWindow):
    def __init__(self):
        WPFWindow.__init__(self, XAML_LAYOUT, literal_string=True)
        self.adapter = RevitHostAdapter()
        self.all_sheets = []
        self.preview_items = []
        self.cmb_scope.SelectedIndex = 0  # 设置默认范围，触发刷新
        self.load_data()

    def load_data(self):
        self.all_sheets = self.adapter.collect_all_sheets()
        self.update_preview()

    def update_preview(self):
        scope = self.cmb_scope.SelectedIndex
        if scope == 0:
            selected_ids = {s['element_id'] for s in self.all_sheets}
        else:
            selected_ids = self.adapter.collect_selected_sheet_ids()

        preview = CoreAlgorithm.build_preview(
            all_sheets=self.all_sheets,
            selected_ids=selected_ids,
            prefix=self.txt_prefix.Text,
            suffix=self.txt_suffix.Text,
            find_text=self.txt_find.Text,
            replace_text=self.txt_replace.Text,
        )
        self.preview_items = preview
        self.dg_preview.ItemsSource = preview
        self.update_status()

    def update_status(self):
        total = len(self.preview_items)
        pending = sum(1 for x in self.preview_items if x['status'] == "待执行")
        errors = sum(1 for x in self.preview_items if x['status'] in ("异常", "冲突"))
        self.txt_status.Text = "已扫描 {} 项 | 待修改 {} 项 | 发现异常 {} 项".format(total, pending, errors)

    def OnScopeChanged(self, sender, e):
        self.update_preview()

    def OnRefreshPreview(self, sender, e):
        self.all_sheets = self.adapter.collect_all_sheets()
        self.update_preview()

    def OnExecute(self, sender, e):
        # 执行前强制刷新，保证数据最新
        self.all_sheets = self.adapter.collect_all_sheets()
        self.update_preview()

        if not self.preview_items:
            forms.alert("当前没有可预览的数据，请确认操作范围或扫描条件。", title="提示")
            return

        only_normal = self.chk_only_normal.IsChecked != False
        if only_normal:
            valid_items = [x for x in self.preview_items if x['status'] == "待执行"]
        else:
            valid_items = [x for x in self.preview_items if x['status'] in ("待执行", "无变化")]

        if not valid_items:
            forms.alert("没有可执行修改的项，请调整参数或检查冲突/只读项。", title="提示")
            return

        changed_items = [{"element_id": x['element_id'], "target_name": x['target_name']} for x in valid_items]
        try:
            count = self.adapter.apply_sheet_name_changes(changed_items)
            forms.alert("成功修改 {} 项图纸名称！".format(count), title="执行成功")
            self.Close()
        except Exception:
            forms.alert("执行失败，所有修改已回滚。\n{}".format(traceback.format_exc()), title="错误")


if __name__ == "__main__":
    MainToolWindow().ShowDialog()