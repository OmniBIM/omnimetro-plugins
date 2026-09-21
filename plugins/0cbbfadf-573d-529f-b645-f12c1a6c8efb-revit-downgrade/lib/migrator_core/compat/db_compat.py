# -*- coding: utf-8 -*-
"""
migrator_core.compat.db_compat
==============================
Cross-engine SQLite import adapter.
Seamlessly handles CPython standard library sqlite3, pyRevit IronPython
framework.sqlite3, and CLR IronPython.SQLite assembly loading.
"""

import sys
import os

sqlite3 = None

# Method 1: pyRevit framework (official pyRevit IronPython & CPython provider)
try:
    from pyrevit.framework import sqlite3 as _pyrevit_sqlite3
    if _pyrevit_sqlite3 is not None:
        sqlite3 = _pyrevit_sqlite3
except Exception:
    pass

# Method 2: Standard Python sqlite3 (CPython 3.x)
if sqlite3 is None:
    try:
        import sqlite3 as _std_sqlite3
        sqlite3 = _std_sqlite3
    except Exception:
        pass

# Method 3: In standalone IronPython, explicitly search and bind the SQLite assembly
if sqlite3 is None:
    try:
        import clr
        loaded = False
        for p in sys.path:
            for dll_name in ["pyRevitLabs.IronPython.SQLite.dll", "IronPython.SQLite.dll"]:
                candidate = os.path.join(p, dll_name)
                if os.path.exists(candidate):
                    try:
                        clr.AddReferenceToFileAndPath(candidate)
                        loaded = True
                        break
                    except Exception:
                        pass
            if loaded:
                break
        if not loaded:
            try:
                clr.AddReference("pyRevitLabs.IronPython.SQLite")
            except Exception:
                try:
                    clr.AddReference("IronPython.SQLite")
                except Exception:
                    pass
        import sqlite3 as _clr_sqlite3
        sqlite3 = _clr_sqlite3
    except Exception:
        pass

def is_sqlite_available():
    return sqlite3 is not None

def get_sqlite():
    if sqlite3 is None:
        raise ImportError(
            "SQLite is not available in the current Python runtime. "
            "If running under IronPython, please ensure pyRevit framework is loaded "
            "or run with CPython engine."
        )
    return sqlite3
