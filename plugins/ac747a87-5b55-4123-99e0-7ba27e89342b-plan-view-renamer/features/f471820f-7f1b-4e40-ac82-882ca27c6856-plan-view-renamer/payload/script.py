# -*- coding: utf-8 -*-
"""
工具名称：平面视图名称批量编辑器（修复增强版）
架构规范：三层解耦标准
  Layer-2: PlanViewNameCore        -> 纯 Python，零 Revit API 依赖
  Layer-3: RevitHostAdapter         -> 宿主 API 适配层，事务保护
  Layer-1: PlanViewRenameWindow     -> WPF GUI 交互层

修复点：
1. ElementId 兼容取值，不再依赖 .IntegerValue
2. 视图名称读取多级 fallback，避免原始名称为空
3. DataGrid 绑定字段固定为 element_id / original_name / target_name / status / message / apply
"""

from collections import Counter

from pyrevit import revit, DB, forms
from pyrevit.forms import WPFWindow


# ----------------------------------------------------------------------
# 【第 2 层：核心业务与算法层】纯 Python，可跨平台移植
# ----------------------------------------------------------------------
class PlanViewNameCore:
    """平面视图名称重命名核心业务逻辑。"""

    @staticmethod
    def make_preview(views, mode, prefix, suffix, search, repl, existing_names):
        """
        生成预览数据、状态校验、冲突检测。
        views: [{element_id, original_name, native_obj}, ...]
        existing_names: set[str]，当前文档所有视图名（用于重名冲突检测）
        """
        if not views:
            return views

        mode_is_replace = "替换" in (mode or "")

        for view in views:
            original = (view.get("original_name") or "").strip()
            view['original_name'] = original
            view.setdefault('message', '')
            view.setdefault('status', None)
            view.setdefault('apply', False)

            # 计算目标名称
            if mode_is_replace:
                if not search:
                    view['target_name'] = original
                    view['status'] = '异常'
                    view['message'] = '查找文本不能为空'
                    continue
                target = original.replace(search, repl or '')
            else:
                prefix = prefix or ''
                suffix = suffix or ''
                target = prefix + original + suffix

            view['target_name'] = target

        # 统计批量目标名称重复
        target_counter = Counter(
            v.get('target_name') for v in views
            if v.get('target_name')
        )

        # 逐项校验收敛
        for item in views:
            if item.get('status'):
                continue

            original = item.get('original_name') or ''
            target = item.get('target_name') or ''

            if not original.strip():
                item['status'] = '异常'
                item['message'] = '原始名称空白，已跳过'
            elif not target.strip():
                item['status'] = '异常'
                item['message'] = '目标名称为空'
            elif target == original:
                item['status'] = '无变化'
                item['message'] = '名称未发生变化'
            elif target in existing_names:
                item['status'] = '冲突'
                item['message'] = '与其他视图名称重复'
            elif target_counter.get(target, 0) > 1:
                item['status'] = '冲突'
                item['message'] = '批量目标名称重复'
            else:
                item['status'] = '待执行'
                item['message'] = '可安全写入'

        return views


# ----------------------------------------------------------------------
# 【第 3 层：宿主 API 适配层】Revit API 读取、写入与事务
# ----------------------------------------------------------------------
class RevitHostAdapter:
    """Revit API 宿主适配器，未来平移到其他平台时仅替换本层。"""

    def __init__(self):
        self.doc = None
        self.uidoc = None
        if revit.doc:
            self.doc = revit.doc
            self.uidoc = revit.uidoc

    # ---------- 基础工具 ----------
    @staticmethod
    def _element_id_to_str(element_id):
        """跨版本安全转为字符串，避免 ElementId.IntegerValue 不兼容。"""
        try:
            if hasattr(element_id, 'IntegerValue'):
                return str(element_id.IntegerValue)
        except Exception:
            pass

        try:
            if hasattr(element_id, 'Value'):
                return str(element_id.Value)
        except Exception:
            pass

        try:
            return element_id.ToString()
        except Exception:
            return str(element_id)

    @staticmethod
    def _get_view_name(view):
        """视图名称读取：View.Name 优先，内置参数兜底。"""
        if view is None:
            return ''

        try:
            if view.Name:
                return view.Name.strip()
        except Exception:
            pass

        try:
            p = view.get_Parameter(DB.BuiltInParameter.VIEW_NAME)
            if p and p.HasValue:
                return (p.AsString() or '').strip()
        except Exception:
            pass

        return ''

    # ---------- 数据收集 ----------
    def collect_plan_views(self, scope='all'):
        """收集待处理平面视图，返回纯字典列表。"""
        if not self.doc:
            return []

        candidate_views = []

        if scope == 'current':
            av = getattr(self.uidoc, 'ActiveView', None)
            if isinstance(av, DB.ViewPlan):
                candidate_views.append(av)
        else:
            try:
                collector = DB.FilteredElementCollector(self.doc) \
                    .OfClass(DB.ViewPlan) \
                    .WhereElementIsNotElementType()
                candidate_views = [v for v in collector]
            except Exception:
                return []

        result = []
        for v in candidate_views:
            try:
                if getattr(v, 'IsTemplate', False):
                    continue
            except Exception:
                pass

            result.append({
                'element_id': self._element_id_to_str(v.Id),
                'original_name': self._get_view_name(v),
                'native_obj': v,
            })

        return result

    def collect_all_view_names(self):
        """收集当前模型所有视图名称集合，用于重名冲突检测。"""
        if not self.doc:
            return set()

        all_names = set()
        try:
            collector = DB.FilteredElementCollector(self.doc) \
                .OfClass(DB.View) \
                .WhereElementIsNotElementType()

            for v in collector:
                try:
                    if getattr(v, 'IsTemplate', False):
                        continue
                    if isinstance(v, DB.ViewSheet):
                        continue
                except Exception:
                    pass

                nm = self._get_view_name(v)
                if nm:
                    all_names.add(nm)
        except Exception:
            pass

        return all_names

    # ---------- 模型修改 ----------
    def apply_modifications(self, items):
        """在事务中批量重命名视图；失败整体回滚。"""
        if not items:
            return 0

        t = DB.Transaction(self.doc, '平面视图名称批量编辑')
        count = 0

        try:
            t.Start()

            for item in items:
                view = item.get('native_obj')
                if not view:
                    continue

                new_name = (item.get('target_name') or '').strip()
                old_name = self._get_view_name(view)

                if not new_name or new_name == old_name:
                    continue

                view.Name = new_name
                count += 1

            t.Commit()

        except Exception:
            try:
                if t.HasStarted():
                    t.RollBack()
            except Exception:
                pass
            raise

        return count


# ----------------------------------------------------------------------
# 【第 1 层：GUI 交互层】WPF / pyRevit.forms
# ----------------------------------------------------------------------
XAML_LAYOUT = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="平面视图名称批量编辑器"
        Height="680" Width="960"
        WindowStartupLocation="CenterScreen">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- 头部信息区 -->
        <StackPanel Grid.Row="0">
            <TextBlock Text="平面视图名称批量编辑器"
                       FontSize="18"
                       FontWeight="Bold"
                       Margin="0,0,0,4"/>
            <TextBlock x:Name="lbl_doc"
                       Text="活动文档："
                       Foreground="#666666"
                       FontSize="11"
                       Margin="2,0,0,10"/>
        </StackPanel>

        <!-- 参数控制区：范围 + 模式 -->
        <StackPanel Grid.Row="1"
                    Orientation="Horizontal"
                    Margin="0,0,0,8">
            <TextBlock Text="范围：" VerticalAlignment="Center" Margin="0,0,4,0"/>
            <ComboBox x:Name="cmb_scope"
                      Width="230"
                      Margin="0,0,15,0"
                      VerticalAlignment="Center"/>

            <TextBlock Text="模式：" VerticalAlignment="Center" Margin="0,0,4,0"/>
            <ComboBox x:Name="cmb_mode"
                      Width="130"
                      VerticalAlignment="Center"/>
        </StackPanel>

        <!-- 参数控制区：规则输入 -->
        <StackPanel Grid.Row="2"
                    Orientation="Horizontal"
                    Margin="0,0,0,10">
            <TextBlock Text="前缀：" VerticalAlignment="Center" Margin="0,0,4,0"/>
            <TextBox x:Name="txt_prefix" Width="90" Margin="0,0,12,0"/>

            <TextBlock Text="后缀：" VerticalAlignment="Center" Margin="0,0,4,0"/>
            <TextBox x:Name="txt_suffix" Width="90" Margin="0,0,12,0"/>

            <TextBlock Text="查找：" VerticalAlignment="Center" Margin="0,0,4,0"/>
            <TextBox x:Name="txt_search" Width="120" Margin="0,0,12,0"/>

            <TextBlock Text="替换为：" VerticalAlignment="Center" Margin="0,0,4,0"/>
            <TextBox x:Name="txt_repl" Width="120" Margin="0,0,15,0"/>

            <Button x:Name="btn_refresh"
                    Content="刷新预览"
                    Padding="12,4"
                    Click="OnRefreshPreview"/>
        </StackPanel>

        <!-- 数据对比预览区 -->
        <DataGrid Grid.Row="3"
                  x:Name="dg_preview"
                  AutoGenerateColumns="False"
                  CanUserAddRows="False"
                  SelectionMode="Extended"
                  BorderBrush="#DDDDDD"
                  GridLinesVisibility="All">

            <DataGrid.RowStyle>
                <Style TargetType="{x:Type DataGridRow}">
                    <Style.Triggers>
                        <DataTrigger Binding="{Binding status}" Value="待执行">
                            <Setter Property="Background" Value="#FFFFFFFF"/>
                        </DataTrigger>
                        <DataTrigger Binding="{Binding status}" Value="无变化">
                            <Setter Property="Foreground" Value="Gray"/>
                        </DataTrigger>
                        <DataTrigger Binding="{Binding status}" Value="冲突">
                            <Setter Property="Background" Value="#FFFFD1D1"/>
                        </DataTrigger>
                        <DataTrigger Binding="{Binding status}" Value="异常">
                            <Setter Property="Background" Value="#FFFFE0E0"/>
                        </DataTrigger>
                    </Style.Triggers>
                </Style>
            </DataGrid.RowStyle>

            <DataGrid.Columns>
                <DataGridCheckBoxColumn Header="应用"
                                        Binding="{Binding apply}"
                                        Width="45"
                                        IsReadOnly="False"/>

                <DataGridTextColumn Header="ElementId"
                                    Binding="{Binding element_id}"
                                    Width="100"
                                    IsReadOnly="True"/>

                <DataGridTextColumn Header="原始名称"
                                    Binding="{Binding original_name}"
                                    Width="180"
                                    IsReadOnly="True"/>

                <DataGridTextColumn Header="目标名称（预览）"
                                    Binding="{Binding target_name}"
                                    Width="200"
                                    IsReadOnly="True"/>

                <DataGridTextColumn Header="状态"
                                    Binding="{Binding status}"
                                    Width="75"
                                    IsReadOnly="True"/>

                <DataGridTextColumn Header="校验说明"
                                    Binding="{Binding message}"
                                    Width="*"
                                    IsReadOnly="True"/>
            </DataGrid.Columns>
        </DataGrid>

        <!-- 底部操作与反馈区 -->
        <DockPanel Grid.Row="4" Margin="0,10,0,0">
            <StackPanel DockPanel.Dock="Right"
                        Orientation="Horizontal"
                        HorizontalAlignment="Right">
                <Button x:Name="btn_execute"
                        Content="执行勾选项"
                        Padding="16,5"
                        Margin="0,0,8,0"
                        Click="OnExecute"/>

                <Button Content="关闭"
                        Padding="16,5"
                        IsCancel="True"/>
            </StackPanel>

            <CheckBox x:Name="chk_select_valid"
                      Content="自动选择正常项（异常/冲突自动跳过）"
                      IsChecked="True"
                      VerticalAlignment="Center"
                      Checked="OnAutoSelectChanged"
                      Unchecked="OnAutoSelectChanged"/>

            <TextBlock x:Name="lbl_status"
                       DockPanel.Dock="Bottom"
                       Text="已扫描 0 项 | 待执行 0 项 | 异常/冲突 0 项"
                       Foreground="#555555"
                       FontSize="12"
                       Margin="0,8,0,0"/>
        </DockPanel>
    </Grid>
</Window>
"""


class PlanViewRenameWindow(WPFWindow):
    """平面视图名称批量编辑器主窗口。"""

    def __init__(self):
        self.adapter = RevitHostAdapter()
        self.preview_container = []

        WPFWindow.__init__(self, XAML_LAYOUT, literal_string=True)

        self._init_controls()
        self.refresh_preview()

    # ---------------- 初始化辅助 ----------------
    def _init_controls(self):
        self.cmb_scope.ItemsSource = [
            '全部平面视图',
            '当前活动视图',
        ]
        self.cmb_scope.SelectedIndex = 0

        self.cmb_mode.ItemsSource = [
            '添加前后缀',
            '查找并替换',
        ]
        self.cmb_mode.SelectedIndex = 0

        doc_name = getattr(self.adapter.doc, 'Title', '未知文档', )
        self.lbl_doc.Text = '活动文档：{} | 工具版本：2.0.0'.format(doc_name)

    # ---------------- UI 业务事件 ----------------
    def _scope_key(self):
        if self.cmb_scope.SelectedIndex == 1:
            return 'current'
        return 'all'

    def _apply_auto_select(self):
        """根据底部自动选择开关刷新 apply 状态。"""
        items = getattr(self, 'preview_container', None)
        if not items:
            return

        auto_select = bool(self.chk_select_valid.IsChecked)

        for item in items:
            item['apply'] = bool(
                auto_select and item.get('status') == '待执行'
            )

        # 刷新 DataGrid
        self.dg_preview.ItemsSource = None
        self.dg_preview.ItemsSource = items

    def _refresh_status_text(self):
        items = self.preview_container or []
        total = len(items)
        selected = sum(1 for x in items if x.get('apply'))
        normal = sum(1 for x in items if x.get('status') == '待执行')
        blocked = total - normal
        self.lbl_status.Text = (
            '已扫描 {0} 项 | 正常待执行 {1} 项 | 已勾选 {2} 项 | '
            '异常/冲突/无变化 {3} 项'.format(
                total,
                normal,
                selected,
                blocked,
            )
        )

    # ---------------- 界面刷新 ----------------
    def refresh_preview(self):
        if not self.adapter.doc:
            forms.alert('未检测到活动 Revit 文档。', title='无法扫描')
            return

        scope = self._scope_key()
        mode = str(self.cmb_mode.SelectedItem or '添加前后缀')
        prefix = self.txt_prefix.Text or ''
        suffix = self.txt_suffix.Text or ''
        search = self.txt_search.Text or ''
        repl = self.txt_repl.Text or ''

        raw_items = self.adapter.collect_plan_views(scope=scope)
        existing_names = self.adapter.collect_all_view_names()

        self.preview_container = PlanViewNameCore.make_preview(
            raw_items,
            mode,
            prefix,
            suffix,
            search,
            repl,
            existing_names,
        )

        if not self.preview_container:
            self.dg_preview.ItemsSource = []
            self.lbl_status.Text = '已扫描 0 项（请检查当前范围是否存在平面视图）'
            return

        self._apply_auto_select()
        self._refresh_status_text()

    # ---------------- 控件事件 ----------------
    def OnRefreshPreview(self, sender, e):
        self.refresh_preview()

    def OnAutoSelectChanged(self, sender, e):
        self._apply_auto_select()
        self._refresh_status_text()

    # ---------------- 事务执行 ----------------
    def OnExecute(self, sender, e):
        if not self.adapter.doc:
            forms.alert('未检测到活动 Revit 文档。', title='无法执行')
            return

        items = self.preview_container or []

        # 用户勾选的项，同时再次安全过滤：只允许执行“待执行”
        to_apply = [
            item for item in items
            if item.get('apply') and item.get('status') == '待执行'
        ]

        if not to_apply:
            forms.alert('请先勾选需要执行的待执行视图。', title='没有可执行项')
            return

        result = forms.alert(
            '即将批量执行 {} 个平面视图重命名，是否继续？'.format(len(to_apply)),
            title='请确认',
            yes=True,
            no=True,
        )

        if not result:
            return

        try:
            count = self.adapter.apply_modifications(to_apply)
            forms.alert(
                '成功修改 {} 个平面视图名称。'.format(count),
                title='执行完成',
            )
            self.refresh_preview()
        except Exception as ex:
            forms.alert(
                '执行失败，事务已回滚：\n{}'.format(ex),
                title='执行异常',
            )


if __name__ == '__main__':
    PlanViewRenameWindow().ShowDialog()