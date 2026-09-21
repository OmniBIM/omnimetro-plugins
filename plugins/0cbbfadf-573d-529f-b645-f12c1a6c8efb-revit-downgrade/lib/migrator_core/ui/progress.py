# -*- coding: utf-8 -*-
"""
migrator_core.ui.progress
=========================
Progress bar and dispatcher synchronization helpers.
"""

class ProgressTracker(object):
    """Encapsulates current phase, processed counts, and UI notification."""

    def __init__(self, total=0, on_update_fn=None):
        self.total = total
        self.current = 0
        self.phase_name = "Initializing"
        self.on_update = on_update_fn

    def set_phase(self, phase_name):
        self.phase_name = phase_name
        self.notify()

    def advance(self, step=1):
        self.current += step
        self.notify()

    def set_progress(self, current, total=None):
        self.current = current
        if total is not None:
            self.total = total
        self.notify()

    @property
    def percent(self):
        if self.total <= 0:
            return 0
        return min(100, int((float(self.current) / float(self.total)) * 100.0))

    def notify(self):
        if self.on_update:
            try:
                self.on_update(self.phase_name, self.current, self.total, self.percent)
            except Exception:
                pass
