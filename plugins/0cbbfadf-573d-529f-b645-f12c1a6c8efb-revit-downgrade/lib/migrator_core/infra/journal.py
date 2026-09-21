# -*- coding: utf-8 -*-
"""
migrator_core.infra.journal
===========================
Migration journal tracking phase completions and processed element IDs
to allow safe resume after interruptions.
"""

import os
import io
import json
import time

class MigrationJournal(object):
    """
    Persists real-time migration progress to disk.
    Allows resumed runs to skip already migrated elements.
    """

    def __init__(self, journal_path=None):
        self.journal_path = journal_path
        self.data = {
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "completed_phases": [],
            "current_phase": None,
            "processed_element_uids": [],
            "statistics": {
                "success_count": 0,
                "error_count": 0
            }
        }
        if journal_path and os.path.exists(journal_path):
            self.load()

    def start_phase(self, phase_name):
        self.data["current_phase"] = phase_name
        self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.save()

    def complete_phase(self, phase_name):
        if phase_name not in self.data["completed_phases"]:
            self.data["completed_phases"].append(phase_name)
        self.data["current_phase"] = None
        self.data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.save()

    def is_phase_completed(self, phase_name):
        return phase_name in self.data["completed_phases"]

    def record_processed(self, source_unique_id, is_success=True):
        if source_unique_id not in self.data["processed_element_uids"]:
            self.data["processed_element_uids"].append(source_unique_id)
        if is_success:
            self.data["statistics"]["success_count"] += 1
        else:
            self.data["statistics"]["error_count"] += 1

    def is_processed(self, source_unique_id):
        return source_unique_id in self.data["processed_element_uids"]

    def save(self):
        if not self.journal_path:
            return
        try:
            folder = os.path.dirname(self.journal_path)
            if folder and not os.path.exists(folder):
                os.makedirs(folder)
            with io.open(self.journal_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    def load(self):
        if not self.journal_path or not os.path.exists(self.journal_path):
            return
        try:
            with io.open(self.journal_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            pass
