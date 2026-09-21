# -*- coding: utf-8 -*-
import codecs
import csv
import re
from Autodesk.Revit.DB import XYZ, HermiteSpline, ElementId, DirectShape, BuiltInCategory, GeometryObject
from System.Collections.Generic import List
from liner_master import core

def parse_chainage(chainage_str):
    """
    Parses chainage strings like DK135+256.255 into a float 135256.255
    """
    if not chainage_str:
        return 0.0
    # Match pattern like K1+234.56 or DK135+256.255
    match = re.search(r'K(\d+)\+(\d+(?:\.\d+)?)', chainage_str.upper())
    if match:
        km = float(match.group(1))
        m = float(match.group(2))
        return km * 1000.0 + m
    
    # Try basic float extraction if no K+ pattern
    nums = re.findall(r'[-+]?\d*\.\d+|\d+', chainage_str)
    if nums:
        return float(nums[0])
    return 0.0

def read_alignment_points_from_csv(file_path):
    """
    Reads CSV with expected columns: Chainage, X, Y, Z, IsEquation, EquationType
    Returns a list of point dictionaries.
    """
    points = []
    with codecs.open(file_path, 'r', 'utf-8-sig') as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            # Fallback column names mapping
            chainage_val = row.get('Chainage', row.get('里程', ''))
            x_val = float(row.get('X', row.get('x', 0)))
            y_val = float(row.get('Y', row.get('y', 0)))
            z_val = float(row.get('Z', row.get('z', 0)))
            
            is_eq_val = row.get('IsEquation', row.get('断链', 'False')).lower() in ['true', '1', 'yes', '是']
            eq_type_val = row.get('EquationType', row.get('断链类型', ''))
            
            points.append({
                'index': idx,
                'chainage': chainage_val,
                'chainage_val': parse_chainage(chainage_val),
                'x': x_val,
                'y': y_val,
                'z': z_val,
                'is_equation': is_eq_val,
                'type': eq_type_val
            })
    return points

def create_alignment_spline(doc, points_data):
    """
    Given a list of points_data from DB or CSV, creates a HermiteSpline.
    Converts coordinates from meters to internal feet if assumed meters.
    """
    if len(points_data) < 2:
        raise ValueError("Need at least 2 points to create an alignment spline.")
    
    xyz_pts = List[XYZ]()
    for p in points_data:
        # Assuming input is in meters, converting to feet
        # Revit API uses feet internally
        x_ft = core.mm_to_ft(p['x'] * 1000.0)
        y_ft = core.mm_to_ft(p['y'] * 1000.0)
        z_ft = core.mm_to_ft(p['z'] * 1000.0)
        xyz_pts.Add(XYZ(x_ft, y_ft, z_ft))
        
    spline = HermiteSpline.Create(xyz_pts, False)
    return spline

def create_alignment_directshape(doc, spline, name="Alignment Axis"):
    """
    Creates a DirectShape representation of the spline in the model.
    """
    ds = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel))
    ds.ApplicationId = core.TRACKING_APP_ID
    ds.ApplicationDataId = "AlignmentSpline"
    geometry_objects = List[GeometryObject]()
    geometry_objects.Add(spline)
    ds.SetShape(geometry_objects)
    ds.Name = name
    return ds
