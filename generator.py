from __future__ import annotations
import math
import random
from .models import Terrain, HoleData, CourseData

WIDTH  = 16
HEIGHT = 26

# All holes par 6 → total 108.
_PAR_LAYOUT = [6] * 18


# ── Geometry ──────────────────────────────────────────────────────────────────

def _dist_point_segment(px: float, py: float,
                        ax: float, ay: float,
                        bx: float, by: float) -> float:
    dx, dy   = bx - ax, by - ay
    len_sq   = dx * dx + dy * dy
    if len_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _dist_to_polyline(px: float, py: float,
                      pts: list[tuple[float, float]]) -> float:
    return min(
        _dist_point_segment(px, py, pts[i][0], pts[i][1],
                            pts[i+1][0], pts[i+1][1])
        for i in range(len(pts) - 1)
    )


def _hash_noise(col: int, row: int, seed: int) -> float:
    """Deterministic spatial noise in [0, 1) — no PYTHONHASHSEED dependency."""
    n = (col * 1619 + row * 31337 + seed * 6971) & 0xFFFF_FFFF
    n = (((n >> 16) ^ n) * 0x45D9F3B) & 0xFFFF_FFFF
    n = (((n >> 16) ^ n) * 0x45D9F3B) & 0xFFFF_FFFF
    n = (n >> 16) ^ n
    return (n & 0x7FFF_FFFF) / 0x7FFF_FFFF


# ── Path generation ───────────────────────────────────────────────────────────

def _make_waypoints(tee: tuple[int, int], pin: tuple[int, int],
                    rng: random.Random) -> list[tuple[float, float]]:
    """Build a curved spine from tee to pin via random intermediate points."""
    tc, tr = tee
    pc, pr = pin
    n_mid  = rng.randint(2, 4)
    pts: list[tuple[float, float]] = [(float(tc), float(tr))]

    for i in range(n_mid):
        t      = (i + 1) / (n_mid + 1)
        base_c = tc + (pc - tc) * t
        base_r = tr + (pr - tr) * t
        c      = max(1.0, min(13.5, base_c + rng.uniform(-5, 5)))
        pts.append((c, base_r))

    pts.append((float(pc), float(pr)))
    return pts


# ── Grid population ───────────────────────────────────────────────────────────

def _build_base_grid(waypoints: list[tuple[float, float]],
                     seed: int) -> list[list[Terrain]]:
    grid = [[Terrain.FAIRWAY] * WIDTH for _ in range(HEIGHT)]
    for r in range(HEIGHT):
        for c in range(WIDTH):
            dist  = _dist_to_polyline(c, r, waypoints)
            noise = _hash_noise(c, r, seed)
            eff   = dist - noise * 0.8          # noise softens the edge

            if eff < 1.1:
                t = Terrain.FAIRWAY
            elif eff < 3.8:
                t = Terrain.ROUGH
            else:
                t = Terrain.ROUGH if noise > 0.40 else Terrain.TREES
            grid[r][c] = t
    return grid


def _stamp_fairway(grid: list[list[Terrain]],
                   cx: int, cy: int, radius: int) -> None:
    for dc in range(-radius, radius + 1):
        for dr in range(-radius, radius + 1):
            c, r = cx + dc, cy + dr
            if 0 <= c < WIDTH and 0 <= r < HEIGHT:
                grid[r][c] = Terrain.FAIRWAY


def _place_bunkers(grid: list[list[Terrain]],
                   waypoints: list[tuple[float, float]],
                   pin: tuple[int, int],
                   rng: random.Random) -> None:
    pc, pr = pin
    for _ in range(rng.randint(2, 5)):
        if rng.random() < 0.55:
            bc = int(pc + rng.uniform(-4, 4))
            br = int(pr + rng.uniform(-4, 4))
        else:
            idx = int(rng.uniform(0.2, 0.85) * (len(waypoints) - 1))
            wc, wr = waypoints[idx]
            bc = int(wc + rng.uniform(-3, 3))
            br = int(wr + rng.uniform(-2, 2))

        bc = max(0, min(WIDTH  - 1, bc))
        br = max(0, min(HEIGHT - 1, br))
        rad = rng.randint(1, 2)

        for dc in range(-rad, rad + 1):
            for dr in range(-rad, rad + 1):
                if dc * dc + dr * dr <= rad * rad + 0.5:
                    nc, nr = bc + dc, br + dr
                    if 0 <= nc < WIDTH and 0 <= nr < HEIGHT:
                        if grid[nr][nc] in (Terrain.FAIRWAY, Terrain.ROUGH):
                            grid[nr][nc] = Terrain.BUNKER


def _place_water(grid: list[list[Terrain]],
                 waypoints: list[tuple[float, float]],
                 rng: random.Random) -> None:
    if rng.random() > 0.55:   # ~55 % of holes have a water hazard
        return
    idx = int(rng.uniform(0.25, 0.75) * (len(waypoints) - 1))
    wc, wr  = waypoints[idx]
    side    = rng.choice((-1, 1))
    center_c = wc + side * rng.uniform(2, 5)
    center_r = wr + rng.uniform(-2, 2)
    hw = rng.uniform(1.5, 3.5)   # half-width
    hh = rng.uniform(2.5, 5.5)   # half-height (elongated)

    for dc in range(-int(hw) - 1, int(hw) + 2):
        for dr in range(-int(hh) - 1, int(hh) + 2):
            if (dc / hw) ** 2 + (dr / hh) ** 2 <= 1.0:
                nc = int(center_c) + dc
                nr = int(center_r) + dr
                if 0 <= nc < WIDTH and 0 <= nr < HEIGHT:
                    grid[nr][nc] = Terrain.WATER


_SLOPE_ARROWS  = ['↑', '↗', '→', '↘', '↓', '↙', '←', '↖']


def _place_slopes(grid: list[list[Terrain]],
                  rng: random.Random,
                  slope_dirs: dict[tuple[int, int], str]) -> None:
    for _ in range(rng.randint(2, 5)):
        sc    = rng.randint(0, WIDTH  - 1)
        sr    = rng.randint(0, HEIGHT - 1)
        rad   = rng.randint(1, 3)
        arrow = rng.choice(_SLOPE_ARROWS)   # whole patch faces one direction
        for dc in range(-rad, rad + 1):
            for dr in range(-rad, rad + 1):
                if dc * dc + dr * dr <= rad * rad:
                    nc, nr = sc + dc, sr + dr
                    if 0 <= nc < WIDTH and 0 <= nr < HEIGHT:
                        if grid[nr][nc] in (Terrain.ROUGH, Terrain.TREES):
                            grid[nr][nc] = Terrain.SLOPE
                            slope_dirs[(nc, nr)] = arrow


# ── Tree obstacles (block the fairway corridor) ───────────────────────────────

def _place_tree_obstacles(grid: list[list[Terrain]],
                          waypoints: list[tuple[float, float]],
                          rng: random.Random) -> None:
    """Place 1–2 tree patches centered on the fairway spine to force navigation."""
    for _ in range(rng.randint(1, 2)):
        t   = rng.uniform(0.25, 0.75)
        idx = int(t * (len(waypoints) - 1))
        wc, wr = waypoints[idx]

        cc = int(wc) + rng.randint(-1, 1)
        cr = int(wr)

        for dc in range(-1, 2):
            for dr in range(-1, 2):
                nc, nr = cc + dc, cr + dr
                if 0 <= nc < WIDTH and 0 <= nr < HEIGHT:
                    if grid[nr][nc] not in (Terrain.WATER, Terrain.BUNKER):
                        grid[nr][nc] = Terrain.TREES


# ── Rough band (disconnects fairway corridor) ─────────────────────────────────

def _place_rough_band(grid: list[list[Terrain]],
                      rng: random.Random,
                      seed: int) -> None:
    """Stamp a wavy rough swathe across the hole to break the fairway corridor."""
    band_r    = rng.randint(9, 15)      # center row — middle third of the hole
    thickness = rng.randint(5, 6)       # total row-height of the band

    for c in range(WIDTH):
        # Per-column wave offset: ±1–2 rows so the band isn't perfectly straight.
        wave = round((_hash_noise(c, 99, seed) - 0.5) * 3)
        for dr in range(thickness):
            r = band_r + wave + dr
            if 0 <= r < HEIGHT and grid[r][c] == Terrain.FAIRWAY:
                grid[r][c] = Terrain.ROUGH


# ── Public API ────────────────────────────────────────────────────────────────

def generate_hole(number: int, seed: int) -> HoleData:
    rng = random.Random(seed)

    # Tee near bottom, pin near top; enforce horizontal offset ≥ 4 cols.
    tee_c = rng.randint(2, 12)
    tee_r = rng.randint(21, 23)
    pin_c = rng.randint(2, 13)
    while abs(pin_c - tee_c) < 4:
        pin_c = rng.randint(2, 13)
    pin_r = rng.randint(2, 4)

    tee = (tee_c, tee_r)
    pin = (pin_c, pin_r)

    waypoints  = _make_waypoints(tee, pin, rng)
    grid       = _build_base_grid(waypoints, seed)
    slope_dirs: dict[tuple[int, int], str] = {}

    _place_bunkers(grid, waypoints, pin, rng)
    _place_water(grid, waypoints, rng)
    _place_slopes(grid, rng, slope_dirs)
    _place_rough_band(grid, rng, seed)
    _place_tree_obstacles(grid, waypoints, rng)

    # Green and tee box stamped last so nothing overwrites them.
    _stamp_fairway(grid, pin_c, pin_r, 2)   # 5×5 green
    _stamp_fairway(grid, tee_c, tee_r, 1)   # 3×3 tee box

    # Wind: weighted toward calmer speeds (0→30 %, 1→40 %, 2→20 %, 3→10 %).
    wind_speed = rng.choices([0, 1, 2, 3], weights=[3, 4, 2, 1])[0]
    wind_dir   = rng.choice(_SLOPE_ARROWS) if wind_speed > 0 else ""

    par = _PAR_LAYOUT[(number - 1) % 18]
    return HoleData(number=number, par=par, grid=grid,
                    tee=tee, pin=pin, waypoints=waypoints,
                    slope_dirs=slope_dirs,
                    wind_speed=wind_speed, wind_dir=wind_dir)


def generate_course(name: str = "Procedural Pines", seed: int = 42) -> CourseData:
    holes = [generate_hole(n, seed=seed + n * 97) for n in range(1, 19)]
    return CourseData(name=name, holes=holes)
