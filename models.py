from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class Terrain(Enum):
    FAIRWAY = "fairway"
    ROUGH   = "rough"
    TREES   = "trees"
    BUNKER  = "bunker"
    WATER   = "water"
    SLOPE   = "slope"


@dataclass(frozen=True)
class TerrainProps:
    symbol:      str    # single display character (char renderer fallback)
    ansi:        str    # ANSI foreground color (char renderer)
    bg:          str    # ANSI background color (block renderer)
    shot_factor: float  # ball distance multiplier from this terrain


TERRAIN_PROPS: dict[Terrain, TerrainProps] = {
    Terrain.FAIRWAY: TerrainProps(".", "\033[92m",   "\033[48;5;82m",  1.00),
    Terrain.ROUGH:   TerrainProps("r", "\033[32m",   "\033[48;5;64m",  0.80),
    Terrain.TREES:   TerrainProps("*", "\033[2;32m", "\033[48;5;22m",  0.50),
    Terrain.BUNKER:  TerrainProps("s", "\033[33m",   "\033[48;5;222m", 0.65),
    Terrain.WATER:   TerrainProps("~", "\033[94m",   "\033[48;5;33m",  0.00),
    Terrain.SLOPE:   TerrainProps("↗", "\033[37m",   "\033[48;5;94m",  0.90),
}


@dataclass
class HoleData:
    number:     int
    par:        int
    grid:       list[list[Terrain]]              # grid[row][col], 26 rows × 16 cols
    tee:        tuple[int, int]                  # (col, row)
    pin:        tuple[int, int]                  # (col, row)
    waypoints:  list[tuple[float, float]]        = field(default_factory=list)
    slope_dirs: dict[tuple[int, int], str]       = field(default_factory=dict)


@dataclass
class CourseData:
    name:  str
    holes: list[HoleData]

    @property
    def total_par(self) -> int:
        return sum(h.par for h in self.holes)
