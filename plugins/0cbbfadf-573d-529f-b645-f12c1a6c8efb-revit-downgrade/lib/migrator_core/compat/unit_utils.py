# -*- coding: utf-8 -*-
"""
migrator_core.compat.unit_utils
===============================
Unit conversion helpers between Revit Internal Units (Feet, Radians)
and standard Metric/Imperial units.
"""

import math

FEET_TO_MM = 304.8
MM_TO_FEET = 1.0 / FEET_TO_MM
SQFT_TO_SQM = 0.09290304
SQM_TO_SQFT = 1.0 / SQFT_TO_SQM
CUFT_TO_CUM = 0.028316846592
CUM_TO_CUFT = 1.0 / CUFT_TO_CUM

def feet_to_mm(feet_val):
    if feet_val is None:
        return 0.0
    return float(feet_val) * FEET_TO_MM

def mm_to_feet(mm_val):
    if mm_val is None:
        return 0.0
    return float(mm_val) * MM_TO_FEET

def radians_to_degrees(rad_val):
    if rad_val is None:
        return 0.0
    return float(rad_val) * (180.0 / math.pi)

def degrees_to_radians(deg_val):
    if deg_val is None:
        return 0.0
    return float(deg_val) * (math.pi / 180.0)

def sqft_to_sqm(sqft_val):
    if sqft_val is None:
        return 0.0
    return float(sqft_val) * SQFT_TO_SQM

def cuft_to_cum(cuft_val):
    if cuft_val is None:
        return 0.0
    return float(cuft_val) * CUFT_TO_CUM

def format_length_display(feet_val, unit="mm"):
    if feet_val is None:
        return "-"
    if unit.lower() == "mm":
        return "{:.1f} mm".format(feet_to_mm(feet_val))
    elif unit.lower() == "m":
        return "{:.3f} m".format(feet_to_mm(feet_val) / 1000.0)
    elif unit.lower() == "ft":
        return "{:.2f} ft".format(feet_val)
    return str(feet_val)
