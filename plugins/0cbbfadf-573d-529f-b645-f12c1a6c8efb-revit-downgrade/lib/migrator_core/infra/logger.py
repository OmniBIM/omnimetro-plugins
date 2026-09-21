# -*- coding: utf-8 -*-
"""
migrator_core.infra.logger
==========================
Structured logging system with file outputs, UI live subscriptions,
and specialized levels (SKIPPED, FALLBACK, SUCCESS, CRITICAL).
"""

import os
import sys
import io
import time
import datetime

class LogLevel(object):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    SKIPPED = "SKIPPED"
    FALLBACK = "FALLBACK"
    SUCCESS = "SUCCESS"

class LogEntry(object):
    def __init__(self, level, message, phase="CORE", source_id=None, target_id=None, category=None):
        self.timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.level = level
        self.message = message
        self.phase = phase
        self.source_id = source_id
        self.target_id = target_id
        self.category = category

    def to_string(self):
        parts = ["[{}]".format(self.timestamp), "[{}]".format(self.level), "[{}]".format(self.phase)]
        if self.category:
            parts.append("[{}]".format(self.category))
        if self.source_id:
            parts.append("Src:{}".format(self.source_id))
        if self.target_id:
            parts.append("Tgt:{}".format(self.target_id))
        parts.append(self.message)
        return " ".join(parts)

class MigratorLogger(object):
    """
    Central logging service with multi-level outputs and UI subscriber support.
    """
    _instance = None

    @classmethod
    def get_logger(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.entries = []
        self.subscribers = []
        self.log_file_path = None
        self._init_log_file()

    def _init_log_file(self):
        appdata = os.getenv("APPDATA", os.path.expanduser("~"))
        log_dir = os.path.join(appdata, "RVT2020Migrator", "logs")
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
            except Exception:
                pass
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.log_file_path = os.path.join(log_dir, "migration_{}.log".format(ts))

    def subscribe(self, callback):
        """Registers a callback function fn(log_entry) for UI streaming."""
        if callback not in self.subscribers:
            self.subscribers.append(callback)

    def unsubscribe(self, callback):
        if callback in self.subscribers:
            self.subscribers.remove(callback)

    def log(self, level, message, phase="CORE", source_id=None, target_id=None, category=None):
        entry = LogEntry(level, message, phase, source_id, target_id, category)
        self.entries.append(entry)

        # Write to file
        if self.log_file_path:
            try:
                with io.open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(entry.to_string() + "\n")
            except Exception:
                pass

        # Notify subscribers
        for sub in list(self.subscribers):
            try:
                sub(entry)
            except Exception:
                pass

    def info(self, msg, phase="CORE", source_id=None, category=None):
        self.log(LogLevel.INFO, msg, phase, source_id, category=category)

    def warning(self, msg, phase="CORE", source_id=None, category=None):
        self.log(LogLevel.WARNING, msg, phase, source_id, category=category)

    def error(self, msg, phase="CORE", source_id=None, category=None):
        self.log(LogLevel.ERROR, msg, phase, source_id, category=category)

    def critical(self, msg, phase="CORE", source_id=None, category=None):
        self.log(LogLevel.CRITICAL, msg, phase, source_id, category=category)

    def fallback(self, msg, phase="CORE", source_id=None, category=None):
        self.log(LogLevel.FALLBACK, msg, phase, source_id, category=category)

    def skipped(self, msg, phase="CORE", source_id=None, category=None):
        self.log(LogLevel.SKIPPED, msg, phase, source_id, category=category)

    def success(self, msg, phase="CORE", source_id=None, target_id=None, category=None):
        self.log(LogLevel.SUCCESS, msg, phase, source_id, target_id=target_id, category=category)

    def get_entries(self, level_filter=None):
        if not level_filter:
            return list(self.entries)
        return [e for e in self.entries if e.level == level_filter]

    def clear(self):
        self.entries = []

# Convenient singleton access
logger = MigratorLogger.get_logger()
