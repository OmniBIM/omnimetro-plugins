# -*- coding: utf-8 -*-
"""
migrator_core.models.material_record
====================================
Material representation for colors, transparency, and textures.
"""

class MaterialRecord(object):
    """Encapsulates material definition and visual properties."""

    def __init__(
        self,
        source_id=None,
        name="",
        color_r=128,
        color_g=128,
        color_b=128,
        transparency=0,
        shininess=50,
        smoothness=50,
        appearance_name="",
        texture_filename="",
        texture_asset_id=None
    ):
        self.source_id = source_id
        self.name = name
        self.color_r = color_r
        self.color_g = color_g
        self.color_b = color_b
        self.transparency = transparency
        self.shininess = shininess
        self.smoothness = smoothness
        self.appearance_name = appearance_name
        self.texture_filename = texture_filename
        self.texture_asset_id = texture_asset_id

    def to_dict(self):
        return {
            "source_id": self.source_id,
            "name": self.name,
            "color_r": self.color_r,
            "color_g": self.color_g,
            "color_b": self.color_b,
            "transparency": self.transparency,
            "shininess": self.shininess,
            "smoothness": self.smoothness,
            "appearance_name": self.appearance_name,
            "texture_filename": self.texture_filename,
            "texture_asset_id": self.texture_asset_id
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            source_id=data.get("source_id"),
            name=data.get("name", ""),
            color_r=data.get("color_r", 128),
            color_g=data.get("color_g", 128),
            color_b=data.get("color_b", 128),
            transparency=data.get("transparency", 0),
            shininess=data.get("shininess", 50),
            smoothness=data.get("smoothness", 50),
            appearance_name=data.get("appearance_name", ""),
            texture_filename=data.get("texture_filename", ""),
            texture_asset_id=data.get("texture_asset_id")
        )
