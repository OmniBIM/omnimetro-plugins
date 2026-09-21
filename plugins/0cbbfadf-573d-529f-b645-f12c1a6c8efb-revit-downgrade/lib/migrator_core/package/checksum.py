# -*- coding: utf-8 -*-
"""
migrator_core.package.checksum
==============================
SHA-256 calculation utilities and asset deduplication store.
"""

import os
import hashlib
import shutil

def calculate_sha256(file_path, block_size=65536):
    """Calculates SHA-256 hex digest for a file on disk."""
    if not os.path.exists(file_path):
        return None
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(block_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def calculate_bytes_sha256(data_bytes):
    """Calculates SHA-256 hex digest for in-memory bytes."""
    return hashlib.sha256(data_bytes).hexdigest()

class AssetStore(object):
    """
    Manages deduplicated asset storage (SAT files, textures, previews)
    keyed by SHA-256 hash.
    """
    def __init__(self, base_asset_dir):
        self.base_dir = base_asset_dir
        self.geom_dir = os.path.join(base_asset_dir, "geometry")
        self.texture_dir = os.path.join(base_asset_dir, "textures")
        self.preview_dir = os.path.join(base_asset_dir, "previews")
        self.family_dir = os.path.join(base_asset_dir, "families")
        self._ensure_dirs()

    def _ensure_dirs(self):
        for d in [self.geom_dir, self.texture_dir, self.preview_dir, self.family_dir]:
            if not os.path.exists(d):
                try:
                    os.makedirs(d)
                except Exception:
                    pass

    def add_geometry_file(self, src_file_path):
        """Copies geometry file to asset store with SHA-256 name. Returns asset_id."""
        if not os.path.exists(src_file_path):
            return None
        sha = calculate_sha256(src_file_path)
        ext = os.path.splitext(src_file_path)[1]
        dest_filename = "{}{}".format(sha, ext)
        dest_path = os.path.join(self.geom_dir, dest_filename)
        if not os.path.exists(dest_path):
            shutil.copy2(src_file_path, dest_path)
        return dest_filename

    def add_geometry_bytes(self, data_bytes, ext=".sat"):
        """Saves geometry bytes to asset store. Returns asset_id."""
        sha = calculate_bytes_sha256(data_bytes)
        dest_filename = "{}{}".format(sha, ext)
        dest_path = os.path.join(self.geom_dir, dest_filename)
        if not os.path.exists(dest_path):
            with open(dest_path, "wb") as f:
                f.write(data_bytes)
        return dest_filename

    def add_texture_file(self, src_file_path):
        """Copies texture image into textures asset store. Returns asset_id."""
        if not os.path.exists(src_file_path):
            return None
        sha = calculate_sha256(src_file_path)
        ext = os.path.splitext(src_file_path)[1]
        dest_filename = "{}{}".format(sha, ext)
        dest_path = os.path.join(self.texture_dir, dest_filename)
        if not os.path.exists(dest_path):
            shutil.copy2(src_file_path, dest_path)
        return dest_filename

    def get_asset_path(self, subfolder, asset_filename):
        """Resolves absolute path for an asset filename."""
        return os.path.join(self.base_dir, subfolder, asset_filename)
