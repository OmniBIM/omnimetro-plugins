# -*- coding: utf-8 -*-
"""
migrator_core.compat
====================
Revit API version adapters, SQLite cross-engine compatibility, and unit conversions.
"""

from .revit_compat import IS_REVIT, DB, UI, RevitVersionAdapter
from .db_compat import sqlite3, is_sqlite_available, get_sqlite
from .unit_utils import (
    feet_to_mm,
    mm_to_feet,
    radians_to_degrees,
    degrees_to_radians,
    sqft_to_sqm,
    cuft_to_cum,
    format_length_display
)
