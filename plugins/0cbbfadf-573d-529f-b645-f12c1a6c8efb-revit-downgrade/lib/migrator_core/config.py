# -*- coding: utf-8 -*-
"""
migrator_core.config
====================
Configuration management for Migration tasks and tool settings.
"""

import os
import json
from .constants import DEFAULT_BATCH_SIZE

class MigrationProfile(object):
    SAFE = "Safe"
    BALANCED = "Balanced"
    MAXIMUM = "Maximum"

class MigrationConfig(object):
    """Encapsulates all migration settings."""

    def __init__(self, profile=MigrationProfile.BALANCED):
        self.profile = profile
        self.batch_size = DEFAULT_BATCH_SIZE

        # Feature flags
        self.rebuild_native = True
        self.rebuild_families = True
        self.geometry_fallback = True
        self.direct_shape_fallback = True
        self.rebuild_materials = True
        self.rebuild_parameters = True
        self.rebuild_shared_parameters = True
        self.rebuild_views = True
        self.rebuild_sheets = True
        self.rebuild_schedules = True
        self.rebuild_mep = True
        self.rebuild_annotations = False
        self.convert_links = False
        self.convert_worksharing = False

        # Paths
        self.output_directory = ""
        self.target_template_path = ""
        self.family_template_dir = ""

        # Policies
        self.error_policy_continue = True
        self.debug_mode = False
        self.pack_local_textures = True
        self.reuse_existing_elements = True

        # Apply profile presets
        self.apply_profile(profile)

    def apply_profile(self, profile_name):
        self.profile = profile_name
        if profile_name == MigrationProfile.SAFE:
            self.rebuild_native = True
            self.rebuild_families = True
            self.geometry_fallback = True
            self.direct_shape_fallback = True
            self.rebuild_materials = True
            self.rebuild_parameters = True
            self.rebuild_views = False
            self.rebuild_sheets = False
            self.rebuild_annotations = False
            self.convert_links = False
        elif profile_name == MigrationProfile.BALANCED:
            self.rebuild_native = True
            self.rebuild_families = True
            self.geometry_fallback = True
            self.direct_shape_fallback = True
            self.rebuild_materials = True
            self.rebuild_parameters = True
            self.rebuild_views = True
            self.rebuild_sheets = True
            self.rebuild_schedules = True
            self.rebuild_annotations = False
            self.convert_links = False
        elif profile_name == MigrationProfile.MAXIMUM:
            self.rebuild_native = True
            self.rebuild_families = True
            self.geometry_fallback = True
            self.direct_shape_fallback = True
            self.rebuild_materials = True
            self.rebuild_parameters = True
            self.rebuild_views = True
            self.rebuild_sheets = True
            self.rebuild_schedules = True
            self.rebuild_annotations = True
            self.convert_links = True

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    @classmethod
    def from_dict(cls, data):
        cfg = cls()
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg

    @classmethod
    def get_default_config_path(cls):
        appdata = os.getenv("APPDATA", os.path.expanduser("~"))
        config_dir = os.path.join(appdata, "RVT2020Migrator")
        if not os.path.exists(config_dir):
            try:
                os.makedirs(config_dir)
            except Exception:
                pass
        return os.path.join(config_dir, "config.json")

    def save_to_disk(self, file_path=None):
        if not file_path:
            file_path = self.get_default_config_path()
        try:
            with open(file_path, "w") as f:
                json.dump(self.to_dict(), f, indent=2)
        except Exception:
            pass

    @classmethod
    def load_from_disk(cls, file_path=None):
        if not file_path:
            file_path = cls.get_default_config_path()
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)
                    return cls.from_dict(data)
            except Exception:
                pass
        return cls()
