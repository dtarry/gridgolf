from .models    import Terrain, TerrainProps, TERRAIN_PROPS, HoleData, CourseData
from .generator import generate_hole, generate_course
from .renderer  import render_hole, render_hole_with_legend, render_course_summary
from .game      import HoleState, ShotResult, compute_shot, apply_shot, play_hole, play_course

__all__ = [
    "Terrain", "TerrainProps", "TERRAIN_PROPS",
    "HoleData", "CourseData",
    "generate_hole", "generate_course",
    "render_hole", "render_hole_with_legend", "render_course_summary",
    "HoleState", "ShotResult", "compute_shot", "apply_shot",
    "play_hole", "play_course",
]
