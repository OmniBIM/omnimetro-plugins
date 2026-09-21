# -*- coding: utf-8 -*-
"""
migrator_core.ui.scan_progress_window
=====================================
Live model scanning progress window for pyRevit/Revit 2027.
Renders real-time progress, speed (items/sec), elapsed time, current item,
and throttles UI updates to 0.5s intervals to keep Revit responsive.
"""

import os
import sys
import time
from ..exceptions import CancellationError
from ..infra.logger import logger

try:
    from pyrevit import forms
    HAS_PYREVIT = True
    BaseWindow = forms.WPFWindow
except Exception:
    HAS_PYREVIT = False
    BaseWindow = object

try:
    import clr
    import System
    clr.AddReference("WindowsBase")
    clr.AddReference("PresentationCore")
    clr.AddReference("PresentationFramework")
    from System.Windows.Threading import Dispatcher, DispatcherPriority

    def _donothing():
        pass

    _nop_action = System.Action(_donothing)

    def pump_dispatcher(dispatcher=None):
        """Pumps WPF dispatcher queue safely without nested Win32 message loop."""
        try:
            disp = dispatcher or Dispatcher.CurrentDispatcher
            if disp:
                disp.Invoke(_nop_action, DispatcherPriority.Background)
        except Exception:
            pass
except Exception:
    def pump_dispatcher(dispatcher=None):
        pass


class ScanProgressWindow(BaseWindow):
    """
    Popup progress window displaying live scan feedback with 0.5s throttling.
    """

    UPDATE_INTERVAL = 0.5  # Update UI every 0.5s

    def __init__(self, owner=None, cancellation_token=None):
        self.xaml_file = os.path.join(os.path.dirname(__file__), "scan_progress_window.xaml")
        if HAS_PYREVIT:
            BaseWindow.__init__(self, self.xaml_file)
            if owner:
                try:
                    self.Owner = owner
                except Exception:
                    pass
            try:
                if hasattr(self, "btnCancelScan"):
                    self.btnCancelScan.Click += self.on_cancel_click
            except Exception:
                pass
            try:
                self.Closing += self.on_window_closing
            except Exception:
                pass

        self.cancellation_token = cancellation_token
        self.start_time = time.time()
        self.last_update_time = 0.0
        self.is_closed = False
        self.total_processed = 0

    def show(self):
        """Displays the progress window non-modally."""
        if HAS_PYREVIT and not self.is_closed:
            try:
                self.Show()
                pump_dispatcher(self.Dispatcher if hasattr(self, "Dispatcher") else None)
            except Exception as ex:
                logger.warning("Failed to show progress window: {}".format(ex), phase="UI")

    def close(self):
        """Closes the progress window safely."""
        if self.is_closed:
            return
        self.is_closed = True
        if HAS_PYREVIT:
            try:
                self.Close()
                pump_dispatcher(self.Dispatcher if hasattr(self, "Dispatcher") else None)
            except Exception:
                pass

    def on_cancel_click(self, sender=None, args=None):
        """Handles user clicking the Cancel button."""
        if self.cancellation_token:
            self.cancellation_token.request_cancel("用户取消了扫描操作")
        if hasattr(self, "txtDetail"):
            self.txtDetail.Text = "正在取消扫描，请稍候..."
        if hasattr(self, "btnCancelScan"):
            self.btnCancelScan.IsEnabled = False
        pump_dispatcher(self.Dispatcher if hasattr(self, "Dispatcher") else None)

    def on_window_closing(self, sender=None, args=None):
        """Handles user closing the window from title bar."""
        if self.cancellation_token and not self.cancellation_token.is_cancellation_requested:
            self.cancellation_token.request_cancel("用户关闭了进度窗口")
        self.is_closed = True

    def update_progress(self, stage_name, current, total, item_desc="", overall_percent=None, force=False):
        """
        Updates UI text, progress bar, speed, and elapsed time.
        Throttled to run at most once every 0.5s unless force=True.
        """
        now = time.time()
        if not force and (now - self.last_update_time < self.UPDATE_INTERVAL):
            return

        self.last_update_time = now
        self.total_processed = current
        elapsed = max(0.001, now - self.start_time)
        speed = int(float(current) / elapsed) if elapsed > 0.05 else 0

        if overall_percent is None:
            pct = min(100.0, max(0.0, (float(current) / float(max(1, total))) * 100.0))
        else:
            pct = min(100.0, max(0.0, float(overall_percent)))

        if HAS_PYREVIT and not self.is_closed:
            try:
                if hasattr(self, "txtStage"):
                    self.txtStage.Text = stage_name
                if hasattr(self, "txtDetail"):
                    self.txtDetail.Text = "已处理 {:,} / {:,}".format(current, total) if total > 0 else "正在处理..."
                if hasattr(self, "progressBar"):
                    self.progressBar.Value = pct
                if hasattr(self, "txtPercent"):
                    self.txtPercent.Text = "{:.1f}%".format(pct)
                if hasattr(self, "txtSpeed"):
                    self.txtSpeed.Text = "扫描速度: {:,} 个/秒".format(speed)
                if hasattr(self, "txtElapsed"):
                    self.txtElapsed.Text = "已耗时: {:.1f}s".format(elapsed)
                if hasattr(self, "txtCurrentItem") and item_desc:
                    self.txtCurrentItem.Text = item_desc

                pump_dispatcher(self.Dispatcher if hasattr(self, "Dispatcher") else None)
            except Exception:
                pass

        if self.cancellation_token and self.cancellation_token.is_cancellation_requested:
            raise CancellationError("用户取消了扫描操作")

    def create_stage_reporter(self, stage_name, min_pct, max_pct):
        """
        Returns a progress callback closure calibrated for a specific stage.
        The callback maps current/total to [min_pct, max_pct] overall progress.
        """
        def reporter(current, total, item_desc="", force=False):
            ratio = float(current) / float(max(1, total)) if total > 0 else 0.0
            overall_pct = min_pct + ratio * (max_pct - min_pct)
            self.update_progress(
                stage_name=stage_name,
                current=current,
                total=total,
                item_desc=item_desc,
                overall_percent=overall_pct,
                force=force
            )
        return reporter
