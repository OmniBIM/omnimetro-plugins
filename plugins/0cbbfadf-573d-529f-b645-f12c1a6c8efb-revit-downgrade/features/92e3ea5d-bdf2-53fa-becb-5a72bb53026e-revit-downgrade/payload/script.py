# -*- coding: utf-8 -*-
"""
Revit 跨版本模型降级与原生重建平台
OmniMetro 专属入口启动脚本
支持 Revit 2027/2024 模型静态能力评估、0.5s实时扫描与 Revit 2020/2018 原生高保真重建。
"""

import os
import sys
import webbrowser

# Ensure plugin lib is on sys.path
FEATURE_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(FEATURE_ROOT))
LIB_ROOT = os.path.join(PLUGIN_ROOT, "lib")
if LIB_ROOT not in sys.path:
    sys.path.insert(0, LIB_ROOT)

# Initialize pyRevit framework
try:
    from pyrevit import forms, revit, framework
    HAS_PYREVIT = True
except Exception:
    HAS_PYREVIT = False

from migrator_core.ui.main_window import MainWindowController, MAIN_WINDOW_XAML
from migrator_core.infra.logger import logger


if HAS_PYREVIT:
    class MigratorWindow(forms.WPFWindow):
        def __init__(self, xaml_file_name):
            forms.WPFWindow.__init__(self, xaml_file_name)
            self.controller = MainWindowController(doc=revit.doc, ui_window=self)

            # Bind event handlers
            if hasattr(self, "btnScanModel"):
                self.btnScanModel.Click += self.on_scan_clicked
            if hasattr(self, "btnExportPackage"):
                self.btnExportPackage.Click += self.on_export_clicked
            if hasattr(self, "btnImportPackage"):
                self.btnImportPackage.Click += self.on_import_clicked
            if hasattr(self, "btnCancel"):
                self.btnCancel.Click += self.on_cancel_clicked
            if hasattr(self, "btnExportLog"):
                self.btnExportLog.Click += self.on_export_log_clicked
            if hasattr(self, "btnExportHtmlReport"):
                self.btnExportHtmlReport.Click += self.on_export_html_clicked

            # Auto-populate project info on open
            if revit.doc and hasattr(self, "txtProjectName"):
                self.txtProjectName.Text = revit.doc.Title or "Unnamed.rvt"

            # Auto-detect version to provide helpful guidance
            try:
                revit_ver = int(revit.doc.Application.VersionNumber)
            except Exception:
                revit_ver = 2027

            if hasattr(self, "txtStatusFooter"):
                if revit_ver >= 2024:
                    self.txtStatusFooter.Text = "就绪 | 当前环境: Revit {} (源端: 支持模型扫描与导出 .rvtmig)".format(revit_ver)
                else:
                    self.txtStatusFooter.Text = "就绪 | 当前环境: Revit {} (目标端: 支持导入 .rvtmig 并原生重建)".format(revit_ver)

        def _set_busy(self, is_busy):
            for btn_name in ("btnExportPackage", "btnImportPackage", "btnScanModel"):
                if hasattr(self, btn_name):
                    try:
                        getattr(self, btn_name).IsEnabled = not is_busy
                    except Exception:
                        pass

        def on_scan_clicked(self, sender, args):
            """Executes model scan with 0.5s progress feedback window."""
            self.controller.run_scan()

        def on_export_clicked(self, sender, args):
            """Exports current model to .rvtmig container."""
            doc_title = revit.doc.Title if revit.doc else "Model"
            save_path = forms.save_file(
                file_ext="rvtmig",
                default_name="{}_R2027_to_R2020.rvtmig".format(doc_title)
            )
            if save_path:
                if hasattr(self, "MainTabControl"):
                    self.MainTabControl.SelectedIndex = 3  # Switch to Progress tab
                self._set_busy(True)
                try:
                    from migrator_core.ui.scan_progress_window import pump_dispatcher
                    pump_dispatcher(self.Dispatcher if hasattr(self, "Dispatcher") else None)
                    final_pkg = self.controller.export_package(save_path)
                    if final_pkg:
                        forms.alert("成功导出迁移包：\n{}".format(final_pkg), title="导出成功")
                except Exception as ex:
                    forms.alert("导出失败：{}".format(str(ex)), title="错误")
                finally:
                    self._set_busy(False)

        def on_import_clicked(self, sender, args):
            """Imports and reconstructs model from .rvtmig package."""
            pkg_path = forms.pick_file(
                file_ext="rvtmig",
                title="选择要导入重建的 .rvtmig 迁移包文件"
            )
            if pkg_path:
                if hasattr(self, "MainTabControl"):
                    self.MainTabControl.SelectedIndex = 3  # Switch to Progress tab
                self._set_busy(True)
                try:
                    from migrator_core.ui.scan_progress_window import pump_dispatcher
                    pump_dispatcher(self.Dispatcher if hasattr(self, "Dispatcher") else None)
                    stats = self.controller.import_package(pkg_path)
                    if stats:
                        created = stats.get("total_created", 0)
                        forms.alert("模型原生重建完成！\n成功生成图元数量：{:,}".format(created), title="导入完成")
                except Exception as ex:
                    forms.alert("导入重建失败：{}".format(str(ex)), title="导入错误")
                finally:
                    self._set_busy(False)

        def on_cancel_clicked(self, sender, args):
            self.controller.cancel()

        def on_export_log_clicked(self, sender, args):
            log_dir = os.path.join(os.getenv("APPDATA", ""), "RVT2020Migrator", "logs")
            forms.alert("日志文件已保存在：\n{}".format(log_dir), title="日志路径")

        def on_export_html_clicked(self, sender, args):
            report_dir = os.path.join(os.getenv("APPDATA", ""), "RVT2020Migrator", "reports")
            if os.path.exists(report_dir):
                files = [os.path.join(report_dir, f) for f in os.listdir(report_dir) if f.endswith(".html")]
                if files:
                    latest = max(files, key=os.path.getmtime)
                    webbrowser.open(latest)
                    return
            forms.alert("尚未生成任何校验报告。", title="提示")


    win = MigratorWindow(MAIN_WINDOW_XAML)
    win.ShowDialog()
else:
    print("Please run inside pyRevit / Revit environment.")
