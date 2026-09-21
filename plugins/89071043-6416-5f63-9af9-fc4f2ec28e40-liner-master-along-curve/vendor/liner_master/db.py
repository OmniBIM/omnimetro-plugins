# -*- coding: utf-8 -*-
import sqlite3
import os
import json
import time
from pyrevit import script

logger = script.get_logger()

class OmniDB(object):
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # ProjectInfo
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ProjectInfo (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # AlignmentData
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS AlignmentData (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                point_index INTEGER,
                chainage_str TEXT,
                x REAL,
                y REAL,
                z REAL,
                is_equation BOOLEAN DEFAULT 0,
                equation_type TEXT
            )
        ''')
        
        # DisciplineConfig
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS DisciplineConfig (
                discipline TEXT,
                config_key TEXT,
                config_value TEXT,
                PRIMARY KEY (discipline, config_key)
            )
        ''')
        
        # OperationLogs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS OperationLogs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                user TEXT,
                discipline TEXT,
                element_ids TEXT,
                status TEXT
            )
        ''')
        
        conn.commit()
        conn.close()

    def set_config(self, discipline, key, value):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO DisciplineConfig (discipline, config_key, config_value)
            VALUES (?, ?, ?)
        ''', (discipline, key, json.dumps(value)))
        conn.commit()
        conn.close()

    def get_config(self, discipline, key, default=None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT config_value FROM DisciplineConfig WHERE discipline=? AND config_key=?
        ''', (discipline, key))
        row = cursor.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
        return default

    def save_alignment_points(self, points_data):
        """
        points_data: list of dicts {'index': int, 'chainage': str, 'x': float, 'y': float, 'z': float, 'is_equation': bool, 'type': str}
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM AlignmentData')
        
        for p in points_data:
            cursor.execute('''
                INSERT INTO AlignmentData (point_index, chainage_str, x, y, z, is_equation, equation_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (p.get('index', 0), p.get('chainage', ''), p.get('x', 0.0), p.get('y', 0.0), p.get('z', 0.0), p.get('is_equation', False), p.get('type', '')))
        conn.commit()
        conn.close()

    def get_alignment_points(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT point_index, chainage_str, x, y, z, is_equation, equation_type FROM AlignmentData ORDER BY point_index ASC')
        rows = cursor.fetchall()
        conn.close()
        return rows

    def log_operation(self, user, discipline, element_ids_list, status="SUCCESS"):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO OperationLogs (timestamp, user, discipline, element_ids, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (time.time(), user, discipline, json.dumps(element_ids_list), status))
        conn.commit()
        conn.close()
