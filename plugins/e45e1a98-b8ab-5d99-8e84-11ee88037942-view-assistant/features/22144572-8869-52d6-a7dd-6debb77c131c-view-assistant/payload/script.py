# -*- coding: utf-8 -*-
import os
import math
from pyrevit import revit, DB, UI, forms
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Windows import DragDrop, DragDropEffects, Point, DataObject, Visibility

doc = revit.doc
uidoc = revit.uidoc
active_view = doc.ActiveView
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
TREE_XAML = os.path.join(SCRIPT_DIR, "ui.xaml")
LAUNCHER_XAML = os.path.join(SCRIPT_DIR, "launcher.xaml")

# ----------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------
def get_subdisc_param(v):
    try:
        p = v.get_Parameter(DB.BuiltInParameter.VIEW_SUBDISCIPLINE)
        if p: return p
    except: pass
    for name in ["子规程", "Sub-Discipline", "视图分类"]:
        p = v.LookupParameter(name)
        if p: return p
    return None

def get_view_params(v):
    try:
        disc = str(v.Discipline)
    except:
        disc = "Coordination"
    p = get_subdisc_param(v)
    sd = p.AsString() if p and p.HasValue else "未分类"
    return disc, sd

def is_view_name_exists(name):
    return any(v.Name.lower() == name.lower() for v in DB.FilteredElementCollector(doc).OfClass(DB.View))

# ----------------------------------------------------------------
# 功能 1：视图裁切 (创建 + 归类)
# ----------------------------------------------------------------
def crop_view_tool():
    if isinstance(active_view, DB.View3D):
        forms.alert("不支持三维视图。")
        return
    try:
        # 1. 框选
        try:
            picked_box = uidoc.Selection.PickBox(UI.Selection.PickBoxStyle.Crossing, "请在视图中拖拽框选裁切范围")
        except OperationCanceledException: return 
        
        # 2. 命名
        new_name = forms.ask_for_string(prompt="输入新视图名称：", title="1. 视图命名", default=active_view.Name + " - 裁剪")
        if not new_name or is_view_name_exists(new_name): return
        
        # 3. 分类 (即时指定位置)
        valid_types = [DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan, DB.ViewType.Section, DB.ViewType.Elevation, DB.ViewType.ThreeD]
        sds = sorted(list(set(get_view_params(v)[1] for v in DB.FilteredElementCollector(doc).OfClass(DB.View) 
                              if not v.IsTemplate and v.ViewType in valid_types)))
        sel_cat = forms.SelectFromList.show(["<新建分类...>"] + sds, title="2. 选择分类位置")
        if sel_cat is None: return
        target_cat = forms.ask_for_string(prompt="输入新分类名：") if sel_cat == "<新建分类...>" else sel_cat
        if not target_cat: return

        # 4. 执行
        cb = active_view.CropBox
        vt, it = cb.Transform, cb.Transform.Inverse
        p1, p2 = it.OfPoint(picked_box.Min), it.OfPoint(picked_box.Max)
        
        with revit.Transaction("TK:视图裁切"):
            nv_id = active_view.Duplicate(DB.ViewDuplicateOption.Duplicate)
            nv = doc.GetElement(nv_id)
            nv.Name = new_name
            p = get_subdisc_param(nv)
            if p and not p.IsReadOnly: p.Set(target_cat)
            nv.CropBoxActive = nv.CropBoxVisible = True
            nb = DB.BoundingBoxXYZ()
            nb.Transform = vt
            nb.Min = DB.XYZ(min(p1.X, p2.X), min(p1.Y, p2.Y), cb.Min.Z)
            nb.Max = DB.XYZ(max(p1.X, p2.X), max(p1.Y, p2.Y), cb.Max.Z)
            nv.CropBox = nb
        forms.toast("创建成功并归类为 [{}]".format(target_cat))
    except Exception as ex: forms.alert("错误: {}".format(ex))

# ----------------------------------------------------------------
# 功能 2：图纸排版 (独立布图功能)
# ----------------------------------------------------------------
def view_management_tool():
    if not isinstance(active_view, DB.ViewSheet):
        forms.alert("请在图纸视图中运行。")
        return
    views = [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View) if not v.IsTemplate and isinstance(v, (DB.ViewPlan, DB.ViewSection))]
    sel = forms.SelectFromList.show(views, name_attr='Name', title="批量选择视图上图", multiselect=True)
    if sel:
        with revit.Transaction("TK:图纸批量排版"):
            cols = int(math.ceil(math.sqrt(len(sel))))
            for i, v in enumerate(sel):
                if DB.Viewport.CanAddViewToSheet(doc, active_view.Id, v.Id):
                    pos = DB.XYZ(0.5 + (i%cols)*1.4, 0.5 + (i//cols)*1.2, 0)
                    DB.Viewport.Create(doc, active_view.Id, v.Id, pos)
        forms.toast("排版完成")

# ----------------------------------------------------------------
# 功能 3：高级树管理器
# ----------------------------------------------------------------
class ViewNode(object):
    def __init__(self, name, vid=None, level=0):
        self.Name, self.ViewId, self.Level, self.Children, self.Parent = name, vid, level, [], None
        self.IsChecked = False
    @property
    def Icon(self): return {0:"🏢", 1:"📂", 2:"📄"}.get(self.Level, "")
    @property
    def Color(self): return {0:"#1976D2", 1:"#F57C00", 2:"#333333"}.get(self.Level, "#000")
    @property
    def BoxVis(self): return Visibility.Visible if self.Level == 2 else Visibility.Collapsed

class AdvancedTreeWindow(forms.WPFWindow):
    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file)
        self.pending_changes = {}
        self._load_tree()

    def _load_tree(self):
        root_data = {}
        for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
            if v.IsTemplate: continue
            if v.ViewType in [DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan, DB.ViewType.Section, DB.ViewType.Elevation]:
                d, sd = get_view_params(v)
                if d not in root_data: root_data[d] = {}
                if sd not in root_data[d]: root_data[d][sd] = []
                root_data[d][sd].append(v)
        
        self.display_data = []
        for d_n in sorted(root_data.keys()):
            dn = ViewNode(d_n, level=0)
            for s_n in sorted(root_data[d_n].keys()):
                sn = ViewNode(s_n, level=1); sn.Parent = dn
                for v in sorted(root_data[d_n][s_n], key=lambda x: x.Name):
                    vn = ViewNode(v.Name, v.Id, level=2); vn.Parent = sn; sn.Children.append(vn)
                dn.Children.append(sn)
            self.display_data.append(dn)
        self.view_tree.ItemsSource = None; self.view_tree.ItemsSource = self.display_data

    def tree_PreviewMouseLeftButtonDown(self, sender, e): self.startPoint = e.GetPosition(None)

    def tree_MouseMove(self, sender, e):
        try:
            if e.LeftButton == forms.WPFWindow.MouseButtonState.Pressed:
                pos = e.GetPosition(None)
                if abs(pos.X - self.startPoint.X) > 10 or abs(pos.Y - self.startPoint.Y) > 10:
                    item = sender.SelectedItem
                    if item and item.Level == 2:
                        DragDrop.DoDragDrop(sender, DataObject("ViewNode", item), DragDropEffects.Move)
        except: pass

    def tree_Drop(self, sender, e):
        try:
            if e.Data.GetDataPresent("ViewNode"):
                dn = e.Data.GetData("ViewNode")
                target = e.OriginalSource.DataContext
                if not target or not hasattr(target, "Level"): return
                if target.Level == 2: target = target.Parent
                new_d, new_sd = "", ""
                if target.Level == 1: new_d, new_sd = target.Parent.Name, target.Name
                elif target.Level == 0:
                    new_d, new_sd = target.Name, "未分类"
                    found_sd = next((c for c in target.Children if c.Name == "未分类"), None)
                    if not found_sd:
                        found_sd = ViewNode("未分类", level=1); found_sd.Parent = target; target.Children.append(found_sd)
                    target = found_sd
                if dn.Parent != target:
                    dn.Parent.Children.remove(dn); dn.Parent = target; target.Children.append(dn)
                    self.pending_changes[dn.ViewId] = (new_d, new_sd)
                    self.status_text.Text = "预览暂存: [{}] -> [{}/{}]".format(dn.Name, new_d, new_sd)
                    self.view_tree.ItemsSource = None; self.view_tree.ItemsSource = self.display_data
        except: pass

    def reset_tree(self, sender, args): self.pending_changes = {}; self._load_tree(); self.status_text.Text = "已重置。"

    def apply_changes(self, sender, args):
        if not self.pending_changes: return
        try:
            with revit.Transaction("TK:高级视图组织调整"):
                for vid, (d, sd) in self.pending_changes.items():
                    v = doc.GetElement(vid)
                    try: v.Discipline = getattr(DB.ViewDiscipline, d)
                    except: pass
                    p = get_subdisc_param(v)
                    if p and not p.IsReadOnly: p.Set(sd)
            forms.alert("成功应用 {} 项调整！".format(len(self.pending_changes)))
            self.pending_changes = {}; self._load_tree()
        except Exception as ex: forms.alert("失败: {}".format(ex))


class ViewAssistantLauncher(forms.WPFWindow):
    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file)

    def RunCrop_Click(self, sender, e):
        self.Close()
        crop_view_tool()

    def RunLayout_Click(self, sender, e):
        self.Close()
        view_management_tool()

    def RunTree_Click(self, sender, e):
        self.Close()
        AdvancedTreeWindow(TREE_XAML).show_dialog()

    def CloseWindow_Click(self, sender, e):
        self.Close()

def main():
    ViewAssistantLauncher(LAUNCHER_XAML).show_dialog()

if __name__ == "__main__": main()
