# -*- coding: utf-8 -*-
"""
migrator_core.ui.main_window
============================
Code-behind controller for the WPF MainWindow.
"""

import os
import sys
import time
import threading
from ..infra.logger import logger
from ..infra.cancellation import CancellationToken
from ..exceptions import CancellationError
from ..scanner import ProjectScanner, ElementScanner, FamilyScanner, MaterialScanner, ViewScanner
from ..analyzers import CapabilityAnalyzer
from ..validation import ModelValidator, ReportGenerator
from ..compat import IS_REVIT
from .scan_progress_window import ScanProgressWindow, pump_dispatcher

MAIN_WINDOW_XAML = os.path.join(os.path.dirname(__file__), "main_window.xaml")


class TaskProgressReporter(object):
    """
    Manages live 0.5s throttled progress bar and status updates on Tab 3 (转换进度).
    Pumps WPF Dispatcher to keep Revit completely responsive and eliminate (Not Responding).
    """
    UPDATE_INTERVAL = 0.5

    def __init__(self, ui_window, cancellation_token=None):
        self.ui = ui_window
        self.cancellation_token = cancellation_token
        self.start_time = time.time()
        self.last_update_time = 0.0

    def update_progress(self, phase_name, current, total, item_desc="", overall_percent=None, force=False):
        now = time.time()
        if not force and (now - self.last_update_time < self.UPDATE_INTERVAL):
            return

        self.last_update_time = now
        elapsed = max(0.001, now - self.start_time)
        speed = int(float(current) / elapsed) if elapsed > 0.05 else 0

        if overall_percent is None:
            pct = min(100.0, max(0.0, (float(current) / float(max(1, total))) * 100.0))
        else:
            pct = min(100.0, max(0.0, float(overall_percent)))

        if self.ui:
            try:
                if hasattr(self.ui, "lblCurrentPhase"):
                    self.ui.lblCurrentPhase.Text = phase_name
                if hasattr(self.ui, "progOverall"):
                    self.ui.progOverall.Value = pct
                if hasattr(self.ui, "lblProgressDetail"):
                    if total > 0:
                        self.ui.lblProgressDetail.Text = (
                            u"已处理 {:,} / {:,} ({}%) | 速度: {:,} 个/秒 | 耗时: {:.1f}s"
                        ).format(current, total, int(pct), speed, elapsed)
                    else:
                        self.ui.lblProgressDetail.Text = u"处理中 ({}%) | 耗时: {:.1f}s".format(int(pct), elapsed)
                if hasattr(self.ui, "txtLiveStatus") and item_desc:
                    self.ui.txtLiveStatus.Text = item_desc
                if hasattr(self.ui, "txtStatusFooter"):
                    self.ui.txtStatusFooter.Text = u"{} ({}%) | {}".format(phase_name, int(pct), item_desc or u"运行中")

                pump_dispatcher(self.ui.Dispatcher if hasattr(self.ui, "Dispatcher") else None)
            except Exception:
                pass

        if self.cancellation_token and self.cancellation_token.is_cancellation_requested:
            raise CancellationError("用户取消了当前操作")

    def create_stage_reporter(self, stage_name, min_pct, max_pct):
        def reporter(current, total, item_desc="", force=False):
            ratio = float(current) / float(max(1, total)) if total > 0 else 0.0
            overall_pct = min_pct + ratio * (max_pct - min_pct)
            self.update_progress(
                phase_name=stage_name,
                current=current,
                total=total,
                item_desc=item_desc,
                overall_percent=overall_pct,
                force=force
            )
        return reporter

class MainWindowController(object):
    """
    Controls the interaction between the WPF MainWindow and the Migrator Engine.
    Works seamlessly in pyRevit WPF context or standalone test mock.
    """

    def __init__(self, doc=None, ui_window=None):
        self.doc = doc
        self.ui = ui_window
        self.cancellation_token = CancellationToken()
        self.scanned_elements = []
        self.scanned_families = []
        self.scanned_materials = []
        self.scanned_views = []
        self.scanned_sheets = []
        self.scanned_levels = []
        self.scanned_grids = []
        self.project_record = None

        # Subscribe logger to live feed
        logger.subscribe(self.on_log_message)

    def on_log_message(self, entry):
        if self.ui and hasattr(self.ui, "txtLogWindow"):
            try:
                # Append to log window
                self.ui.txtLogWindow.AppendText(entry.to_string() + "\n")
                self.ui.txtLogWindow.ScrollToEnd()
            except Exception:
                pass
        if self.ui and hasattr(self.ui, "txtLiveStatus"):
            try:
                self.ui.txtLiveStatus.Text = entry.message
            except Exception:
                pass

    def run_scan(self):
        """Executes non-destructive model scan with popup progress window."""
        self.cancellation_token.reset()

        # Instantiate live progress window with 0.5s updates
        progress_win = ScanProgressWindow(owner=self.ui, cancellation_token=self.cancellation_token)
        progress_win.show()

        if self.ui and hasattr(self.ui, "btnScanModel"):
            self.ui.btnScanModel.IsEnabled = False

        try:
            if not IS_REVIT or not self.doc:
                logger.warning("Not running inside active Revit document. Running simulated scan.")
                self._mock_scan(progress_win)
                return

            logger.info("Starting model scan...", phase="SCAN")
            self._update_status("正在启动模型扫描与分析...")

            # 1. Datums & Project info (0% -> 5%)
            cb_datums = progress_win.create_stage_reporter(u"阶段 1/6: 扫描标高与轴网基准...", 0.0, 5.0)
            cb_datums(0, 10, u"正在读取项目信息...", force=True)
            p_scanner = ProjectScanner(self.doc)
            self.project_record = p_scanner.scan()

            el_scanner = ElementScanner(self.doc)
            self.scanned_levels, self.scanned_grids = el_scanner.scan_datums(progress_callback=cb_datums)
            tot_datums = len(self.scanned_levels) + len(self.scanned_grids)
            cb_datums(max(1, tot_datums), max(1, tot_datums), u"标高与轴网扫描完成", force=True)

            # 2. Elements (5% -> 70%)
            cb_elem = progress_win.create_stage_reporter(u"阶段 2/6: 扫描物理构件与几何数据...", 5.0, 70.0)
            cb_elem(0, 100, u"准备遍历模型物理构件...", force=True)
            self.scanned_elements = el_scanner.scan_elements(progress_callback=cb_elem)
            cb_elem(len(self.scanned_elements), max(1, len(self.scanned_elements)), u"构件扫描完成", force=True)

            # 3. Families (70% -> 85%)
            cb_fam = progress_win.create_stage_reporter(u"阶段 3/6: 扫描族定义与类型参数...", 70.0, 85.0)
            cb_fam(0, 100, u"准备扫描族库...", force=True)
            fam_scanner = FamilyScanner(self.doc)
            self.scanned_families = fam_scanner.scan(progress_callback=cb_fam)
            cb_fam(len(self.scanned_families), max(1, len(self.scanned_families)), u"族定义扫描完成", force=True)

            # 4. Materials (85% -> 90%)
            cb_mat = progress_win.create_stage_reporter(u"阶段 4/6: 扫描材质与外观着色器...", 85.0, 90.0)
            cb_mat(0, 100, u"准备扫描材质...", force=True)
            mat_scanner = MaterialScanner(self.doc)
            self.scanned_materials = mat_scanner.scan(progress_callback=cb_mat)
            cb_mat(len(self.scanned_materials), max(1, len(self.scanned_materials)), u"材质扫描完成", force=True)

            # 5. Views & Sheets (90% -> 95%)
            cb_view = progress_win.create_stage_reporter(u"阶段 5/6: 扫描视图与工程图纸...", 90.0, 95.0)
            cb_view(0, 100, u"准备扫描视图与图纸...", force=True)
            view_scanner = ViewScanner(self.doc)
            self.scanned_views, self.scanned_sheets = view_scanner.scan(progress_callback=cb_view)
            tot_v = len(self.scanned_views) + len(self.scanned_sheets)
            cb_view(tot_v, max(1, tot_v), u"视图与图纸扫描完成", force=True)

            # 6. Analyze Capabilities (95% -> 100%)
            cb_cap = progress_win.create_stage_reporter(u"阶段 6/6: 评估迁移可行性与降级矩阵...", 95.0, 100.0)
            cb_cap(0, max(1, len(self.scanned_elements)), u"开始各类别可行性评估...", force=True)
            matrix_rows, stats, risks = CapabilityAnalyzer.analyze_model(
                self.scanned_elements, self.scanned_families, progress_callback=cb_cap
            )
            cb_cap(len(self.scanned_elements), max(1, len(self.scanned_elements)), u"评估完成！", force=True)

            # Finish
            progress_win.update_progress(
                u"扫描完成",
                len(self.scanned_elements),
                len(self.scanned_elements),
                item_desc=u"模型扫描完成，正在呈现统计分析...",
                overall_percent=100.0,
                force=True
            )
            time.sleep(0.3)

            # Update UI
            self._apply_scan_results_to_ui(stats, matrix_rows, risks)
            logger.success("Model scan completed successfully! Total elements: {}".format(len(self.scanned_elements)), phase="SCAN")
            self._update_status("扫描完成 | 预计高保真覆盖率：{}%".format(stats.get("coverage_percent", 100.0)))

        except CancellationError as ex:
            logger.warning("模型扫描已被用户取消", phase="SCAN")
            self._update_status("扫描已取消")
        except Exception as ex:
            logger.error("模型扫描过程中出错: {}".format(ex), phase="SCAN")
            self._update_status("扫描错误: {}".format(ex))
        finally:
            progress_win.close()
            if self.ui and hasattr(self.ui, "btnScanModel"):
                self.ui.btnScanModel.IsEnabled = True

    def _apply_scan_results_to_ui(self, stats, matrix_rows, risks):
        if not self.ui:
            return
        try:
            self.ui.txtTotalElements.Text = "{:,}".format(stats.get("total_elements", 0))
            self.ui.txtTotalFamilies.Text = "{:,}".format(len(self.scanned_families))
            self.ui.txtTotalMaterials.Text = "{:,}".format(len(self.scanned_materials))
            self.ui.txtTotalViews.Text = "{:,}".format(len(self.scanned_views) + len(self.scanned_sheets))

            self.ui.txtCoveragePercent.Text = "{}%".format(stats.get("coverage_percent", 100.0))

            tot = max(1, stats.get("total_elements", 1))
            self.ui.txtNativeRatio.Text = "{:.1f}%".format((stats.get("native_count", 0) / float(tot)) * 100.0)
            self.ui.txtFamilyRatio.Text = "{:.1f}%".format((stats.get("family_count", 0) / float(tot)) * 100.0)
            self.ui.txtGeometryRatio.Text = "{:.1f}%".format((stats.get("geometry_count", 0) / float(tot)) * 100.0)
            self.ui.txtUnsupportedRatio.Text = "{:.1f}%".format((stats.get("unsupported_count", 0) / float(tot)) * 100.0)

            # Bind DataGrid
            items_list = [r.to_dict() for r in matrix_rows]
            self.ui.gridScanResults.ItemsSource = items_list
        except Exception:
            pass

    def export_package(self, output_path):
        """Streams scanned model to .rvtmig intermediate package with 0.5s live progress updates."""
        from ..package import PackageWriter
        self.cancellation_token.reset()

        reporter = TaskProgressReporter(self.ui, cancellation_token=self.cancellation_token)
        reporter.update_progress(u"正在初始化导出环境...", 0, 100, item_desc=u"准备迁移容器...", overall_percent=0.0, force=True)

        logger.info("Starting package export to: {}".format(output_path), phase="EXPORT")
        out_dir = os.path.dirname(output_path)
        pkg_name = os.path.basename(output_path)

        try:
            # If model has not been scanned yet in Revit, auto-scan first (0% -> 30%)
            has_scanned = bool(self.scanned_elements or self.scanned_levels or self.project_record)
            if not has_scanned and IS_REVIT and self.doc:
                logger.info("Auto-scanning model before export...", phase="EXPORT")
                cb_datums = reporter.create_stage_reporter(u"扫描阶段 1/3: 标高与轴网基准...", 0.0, 10.0)
                p_scanner = ProjectScanner(self.doc)
                self.project_record = p_scanner.scan()
                el_scanner = ElementScanner(self.doc)
                self.scanned_levels, self.scanned_grids = el_scanner.scan_datums(progress_callback=cb_datums)

                cb_elem = reporter.create_stage_reporter(u"扫描阶段 2/3: 物理构件与几何资产...", 10.0, 25.0)
                self.scanned_elements = el_scanner.scan_elements(progress_callback=cb_elem)

                cb_fam = reporter.create_stage_reporter(u"扫描阶段 3/3: 族与材质定义...", 25.0, 30.0)
                fam_scanner = FamilyScanner(self.doc)
                self.scanned_families = fam_scanner.scan(progress_callback=cb_fam)
                mat_scanner = MaterialScanner(self.doc)
                self.scanned_materials = mat_scanner.scan(progress_callback=cb_fam)
                view_scanner = ViewScanner(self.doc)
                self.scanned_views, self.scanned_sheets = view_scanner.scan()
                base_pct = 30.0
            else:
                base_pct = 0.0

            export_weight = 100.0 - base_pct

            # 1. Project Info, Datums (0% -> 10% of export)
            cb_datums = reporter.create_stage_reporter(
                u"导出阶段 1/6: 写入项目信息、标高与轴网...",
                base_pct, base_pct + export_weight * 0.10
            )
            cb_datums(0, 10, u"创建迁移包容器与 SQLite 存储...", force=True)
            writer = PackageWriter(out_dir, package_filename=pkg_name)

            if self.project_record:
                writer.write_project_info(self.project_record)
            writer.write_levels(self.scanned_levels)
            writer.write_grids(self.scanned_grids)
            cb_datums(10, 10, u"标高与轴网写入完成", force=True)

            # 2. Materials (10% -> 20% of export)
            cb_mat = reporter.create_stage_reporter(
                u"导出阶段 2/6: 写入材质与着色器定义...",
                base_pct + export_weight * 0.10, base_pct + export_weight * 0.20
            )
            cb_mat(0, max(1, len(self.scanned_materials)), u"正在写入材质记录...", force=True)
            writer.write_materials(self.scanned_materials, progress_callback=cb_mat)
            cb_mat(max(1, len(self.scanned_materials)), max(1, len(self.scanned_materials)), u"材质写入完成", force=True)

            # 3. Elements (20% -> 75% of export)
            cb_elem = reporter.create_stage_reporter(
                u"导出阶段 3/6: 写入物理构件与几何资产...",
                base_pct + export_weight * 0.20, base_pct + export_weight * 0.75
            )
            cb_elem(0, max(1, len(self.scanned_elements)), u"正在批量写入图元与参数...", force=True)
            writer.write_elements_batch(
                self.scanned_elements,
                progress_callback=cb_elem,
                cancellation_token=self.cancellation_token
            )
            cb_elem(max(1, len(self.scanned_elements)), max(1, len(self.scanned_elements)), u"构件与参数写入完成", force=True)

            # 4. Families (75% -> 85% of export)
            cb_fam = reporter.create_stage_reporter(
                u"导出阶段 4/6: 写入族定义与类型参数...",
                base_pct + export_weight * 0.75, base_pct + export_weight * 0.85
            )
            cb_fam(0, max(1, len(self.scanned_families)), u"正在写入族定义...", force=True)
            writer.write_families(self.scanned_families, progress_callback=cb_fam)
            cb_fam(max(1, len(self.scanned_families)), max(1, len(self.scanned_families)), u"族定义写入完成", force=True)

            # 5. Views & Sheets (85% -> 90% of export)
            cb_views = reporter.create_stage_reporter(
                u"导出阶段 5/6: 写入工程视图与图纸布局...",
                base_pct + export_weight * 0.85, base_pct + export_weight * 0.90
            )
            cb_views(0, max(1, len(self.scanned_views) + len(self.scanned_sheets)), u"正在写入视图与图纸...", force=True)
            writer.write_views(self.scanned_views, progress_callback=cb_views)
            writer.write_sheets(self.scanned_sheets, progress_callback=cb_views)
            cb_views(10, 10, u"视图与图纸写入完成", force=True)

            # 6. Finalize & Zip (90% -> 100%)
            cb_zip = reporter.create_stage_reporter(
                u"导出阶段 6/6: 生成校验和与 ZIP 流式打包...",
                base_pct + export_weight * 0.90, 100.0
            )
            cb_zip(0, 10, u"正在生成迁移清单与校验和...", force=True)
            final_pkg = writer.finalize(progress_callback=cb_zip)

            reporter.update_progress(
                u"导出完成", 100, 100,
                item_desc=u"迁移包已成功保存至: {}".format(os.path.basename(final_pkg)),
                overall_percent=100.0,
                force=True
            )
            logger.success("Package export complete: {}".format(final_pkg), phase="EXPORT")
            self._update_status(u"导出完成 | 文件: {}".format(os.path.basename(final_pkg)))
            return final_pkg

        except CancellationError:
            logger.warning("Package export cancelled by user.", phase="EXPORT")
            reporter.update_progress(u"导出已取消", 0, 100, item_desc=u"导出操作已被用户中断。", overall_percent=0.0, force=True)
            self._update_status(u"导出已取消")
            return None
        except Exception as ex:
            logger.error("Package export failed: {}".format(str(ex)), phase="EXPORT")
            reporter.update_progress(u"导出失败", 0, 100, item_desc=u"错误: {}".format(str(ex)), overall_percent=0.0, force=True)
            self._update_status(u"导出错误: {}".format(str(ex)))
            raise

    def import_package(self, package_path):
        """Reconstructs native BIM elements from .rvtmig container with 0.5s live progress updates."""
        from ..package import PackageReader
        from ..importer_engine import ImporterEngine
        self.cancellation_token.reset()

        reporter = TaskProgressReporter(self.ui, cancellation_token=self.cancellation_token)
        reporter.update_progress(u"正在初始化导入环境...", 0, 100, item_desc=u"解析 .rvtmig 迁移数据包...", overall_percent=0.0, force=True)

        logger.info("Starting model reconstruction from: {}".format(package_path), phase="IMPORT")
        self._update_status("正在解包并读取迁移数据...")

        try:
            reader = PackageReader(package_path)
            engine = ImporterEngine(self.doc, reader)

            val_result = engine.run_import(stage_reporter_factory=reporter.create_stage_reporter)

            reporter.update_progress(
                u"导入与原生重建完成！", 100, 100,
                item_desc=u"模型原生重建完成，已生成质检报告。",
                overall_percent=100.0,
                force=True
            )
            logger.success("Model reconstruction complete!", phase="IMPORT")
            self._update_status("模型重建完成！已生成质检报告")
            return val_result

        except CancellationError:
            logger.warning("Import cancelled by user.", phase="IMPORT")
            reporter.update_progress(u"导入已取消", 0, 100, item_desc=u"重建操作已被用户中断。", overall_percent=0.0, force=True)
            self._update_status(u"导入已取消")
            return None
        except Exception as ex:
            logger.error("Import failed: {}".format(str(ex)), phase="IMPORT")
            reporter.update_progress(u"导入失败", 0, 100, item_desc=u"错误: {}".format(str(ex)), overall_percent=0.0, force=True)
            self._update_status(u"导入错误: {}".format(str(ex)))
            raise

    def cancel(self):
        self.cancellation_token.request_cancel()
        logger.warning("Cancellation requested by user.", phase="CORE")

    def _update_status(self, text):
        if self.ui and hasattr(self.ui, "txtStatusFooter"):
            try:
                self.ui.txtStatusFooter.Text = text
            except Exception:
                pass

    def _mock_scan(self, progress_win=None):
        """Provides simulated scan data when testing outside Revit."""
        if progress_win:
            cb = progress_win.create_stage_reporter(u"模拟扫描: 正在读取构件...", 0.0, 100.0)
            total = 1000
            for i in range(1, total + 1):
                cb(i, total, u"[Mock Element] 构件 ID: {}".format(i))
                time.sleep(0.001)
            progress_win.update_progress(
                u"模拟扫描完成", total, total, item_desc=u"模拟数据扫描完成！", overall_percent=100.0, force=True
            )
            time.sleep(0.2)

        stats = {
            "total_elements": 125632,
            "native_count": 117000,
            "family_count": 6200,
            "geometry_count": 1900,
            "unsupported_count": 532,
            "coverage_percent": 99.6
        }
        self._apply_scan_results_to_ui(stats, [], [])
        self._update_status("扫描完成 | 预计高保真覆盖率：99.6%")
