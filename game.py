"""Golf mechanics: dice, terrain rules, post-landing effects, and interactive play."""
from __future__ import annotations

import os
import random
from dataclasses import dataclass, field

from .generator import WIDTH, HEIGHT
from .models    import Terrain, TERRAIN_PROPS, HoleData, CourseData
from .renderer  import render_hole_with_legend

MULLIGANS_PER_COURSE = 6

# ── Direction maps ─────────────────────────────────────────────────────────────

# Numpad key → (Δcol, Δrow).  Rows increase downward so N = row-1.
DIRS: dict[str, tuple[int, int]] = {
    '7': (-1, -1), '8': ( 0, -1), '9': ( 1, -1),
    '4': (-1,  0),                 '6': ( 1,  0),
    '1': (-1,  1), '2': ( 0,  1), '3': ( 1,  1),
}

# Arrow glyph → (Δcol, Δrow)  — used for slopes and wind
ARROW_DIR: dict[str, tuple[int, int]] = {
    '↑': ( 0, -1), '↗': ( 1, -1), '→': ( 1,  0), '↘': ( 1,  1),
    '↓': ( 0,  1), '↙': (-1,  1), '←': (-1,  0), '↖': (-1, -1),
}

_COMPASS = (
    "  ┌─────────────────────────┐\n"
    "  │  7(NW)  8( N↑)  9(NE)  │\n"
    "  │  4(W←)    ·     6(E→)  │\n"
    "  │  1(SW)  2( S↓)  3(SE)  │\n"
    "  └─────────────────────────┘"
)

# ── State ──────────────────────────────────────────────────────────────────────

@dataclass
class HoleState:
    hole:     HoleData
    ball:     tuple[int, int]              # current (col, row)
    prev:     tuple[int, int]              # position before last shot (water penalty)
    strokes:  int                = 0
    complete: bool               = False
    history:  list[tuple[int, int]] = field(default_factory=list)  # all previous landing spots

    @classmethod
    def start(cls, hole: HoleData) -> HoleState:
        return cls(hole=hole, ball=hole.tee, prev=hole.tee)


@dataclass
class ShotResult:
    valid:            bool
    final_pos:        tuple[int, int]
    distance:         int
    penalty_strokes:  int       = 0
    messages:         list[str] = field(default_factory=list)
    error:            str       = ""

# ── Path helpers ───────────────────────────────────────────────────────────────

def _walk(bc: int, br: int, dc: int, dr: int, dist: int) -> list[tuple[int, int]]:
    """Return cells visited moving (dc,dr) for dist steps, clamped to grid."""
    return [
        (max(0, min(WIDTH  - 1, bc + dc * i)),
         max(0, min(HEIGHT - 1, br + dr * i)))
        for i in range(1, dist + 1)
    ]


def _base_dist(terrain: Terrain, roll: int) -> tuple[int, str]:
    """Terrain-modified distance and a short description."""
    match terrain:
        case Terrain.FAIRWAY:
            return roll + 1, f"Fairway +1  ({roll}+1 = {roll+1} sq)"
        case Terrain.ROUGH:
            return roll,           f"Rough, no modifier  ({roll} sq)"
        case Terrain.BUNKER:
            d = max(1, roll - 1)
            return d, f"Bunker -1  ({roll}-1 = {d} sq)"
        case _:
            # Slope, etc. — no modifier
            return roll, f"{terrain.value}  ({roll} sq)"

# ── Post-landing effects ───────────────────────────────────────────────────────

def follow_slopes(pos: tuple[int, int],
                  hole: HoleData) -> tuple[tuple[int, int], list[str]]:
    """
    Follow the slope chain from pos until landing on a non-slope cell.
    Trees and grid edges stop the chain.
    """
    msgs: list[str] = []
    visited: set[tuple[int, int]] = set()
    c, r = pos
    while True:
        if not (0 <= c < WIDTH and 0 <= r < HEIGHT):
            break
        if hole.grid[r][c] != Terrain.SLOPE:
            break
        if (c, r) in visited:
            break                   # cycle guard
        visited.add((c, r))
        arrow = hole.slope_dirs.get((c, r), "")
        if not arrow or arrow not in ARROW_DIR:
            break
        dc, dr = ARROW_DIR[arrow]
        nc, nr = c + dc, r + dr
        if not (0 <= nc < WIDTH and 0 <= nr < HEIGHT):
            break
        if hole.grid[nr][nc] == Terrain.TREES:
            break                   # trees block sliding
        c, r = nc, nr
        msgs.append(f"Slope {arrow} → col {c+1}, row {r+1}")
    return (c, r), msgs


def apply_wind(pos: tuple[int, int],
               hole: HoleData) -> tuple[tuple[int, int], list[str]]:
    """Move ball wind_speed cells in wind_dir after landing. Trees stop movement."""
    if hole.wind_speed == 0:
        return pos, []
    dc, dr  = ARROW_DIR[hole.wind_dir]
    c, r    = pos
    moved   = 0
    for _ in range(hole.wind_speed):
        nc, nr = c + dc, r + dr
        if not (0 <= nc < WIDTH and 0 <= nr < HEIGHT):
            break
        if hole.grid[nr][nc] == Terrain.TREES:
            break
        c, r  = nc, nr
        moved += 1
    msgs = ([f"Wind {hole.wind_dir} ×{hole.wind_speed} → col {c+1}, row {r+1}"]
            if moved else [])
    return (c, r), msgs

# ── Shot computation ───────────────────────────────────────────────────────────

def compute_shot(state: HoleState,
                 dir_key: str,
                 roll: int | None) -> ShotResult:
    """
    Simulate a full shot and return ShotResult.
    roll=None  →  putt (always 1 sq, terrain modifier ignored).
    roll=int   →  normal shot with terrain modifier.

    Terrain rules
    ─────────────
    Fairway  +1 to distance.
    Rough    no modifier.
    Bunker   -1 to distance (min 1).
    Trees    can never be the landing cell.
             · From fairway  — may fly through; endpoint must exit the trees.
             · From rough    — may fly through with -1 penalty; endpoint must exit.
             · From other    — path cannot enter trees at all.
    Water    endpoint in water → +1 penalty, ball returns to previous lie.
    Slopes   chain-follow after landing.
    Wind     moves ball after slope settling.
    """
    dc, dr  = DIRS[dir_key]
    bc, br  = state.ball
    origin  = state.hole.grid[br][bc]
    msgs: list[str] = []

    # ── 1. Base distance ───────────────────────────────────────────────────────
    if roll is None:
        dist = 1
        msgs.append("Putt  (1 sq)")
    else:
        dist, desc = _base_dist(origin, roll)
        msgs.append(desc)

    # ── 2. Tree obstacle rules (skip for putts — they're too short to clear) ──
    path = _walk(bc, br, dc, dr, dist)
    trees_in_path = [p for p in path
                     if state.hole.grid[p[1]][p[0]] == Terrain.TREES]

    if trees_in_path and roll is not None:
        endpoint_terrain = state.hole.grid[path[-1][1]][path[-1][0]]

        if origin == Terrain.FAIRWAY:
            # Must clear: ball can fly through but endpoint can't be trees
            if endpoint_terrain == Terrain.TREES:
                return ShotResult(
                    valid=False, final_pos=state.ball, distance=dist,
                    error="Not enough distance to clear the trees from fairway."
                )
            msgs.append("Clearing trees (fairway).")

        elif origin == Terrain.ROUGH:
            # -1 distance penalty; endpoint still can't be trees
            dist = max(1, dist - 1)
            path = _walk(bc, br, dc, dr, dist)
            endpoint_terrain = state.hole.grid[path[-1][1]][path[-1][0]]
            if endpoint_terrain == Terrain.TREES:
                return ShotResult(
                    valid=False, final_pos=state.ball, distance=dist,
                    error="Can't land in trees even with rough penalty (-1 sq)."
                )
            msgs.append(f"Trees rough-penalty -1 → {dist} sq.")

        else:
            # Bunker, slope, etc. — cannot enter trees
            return ShotResult(
                valid=False, final_pos=state.ball, distance=dist,
                error=f"Can't shoot through trees from {origin.value}."
            )

    # ── 3. Final endpoint checks ───────────────────────────────────────────────
    endpoint = path[-1]
    ec, er   = endpoint

    if state.hole.grid[er][ec] == Terrain.TREES:
        return ShotResult(
            valid=False, final_pos=state.ball, distance=dist,
            error="Can't land in trees."
        )

    land_terrain = state.hole.grid[er][ec]
    msgs.append(f"Lands on {land_terrain.value}  (col {ec+1}, row {er+1})")

    # Immediate hole-out before any post-landing effects
    if endpoint == state.hole.pin:
        msgs.append("⛳ In the hole!")
        return ShotResult(valid=True, final_pos=endpoint, distance=dist, messages=msgs)

    # ── 4. Direct water landing ────────────────────────────────────────────────
    if land_terrain == Terrain.WATER:
        msgs.append("Water hazard!  +1 penalty stroke, back to previous lie.")
        return ShotResult(valid=True, final_pos=state.prev, distance=dist,
                          penalty_strokes=1, messages=msgs)

    # ── 5. Slope chain ─────────────────────────────────────────────────────────
    post_slope, slope_msgs = follow_slopes(endpoint, state.hole)
    msgs.extend(slope_msgs)
    endpoint = post_slope
    ec, er   = endpoint

    # ── 6. Wind (putts are unaffected) ────────────────────────────────────────
    if roll is not None:
        post_wind, wind_msgs = apply_wind(endpoint, state.hole)
        msgs.extend(wind_msgs)
        endpoint = post_wind
        ec, er   = endpoint

    # ── 7. Water after post-landing movement ───────────────────────────────────
    if state.hole.grid[er][ec] == Terrain.WATER:
        msgs.append("Carried into water!  +1 penalty stroke, back to previous lie.")
        return ShotResult(valid=True, final_pos=state.prev, distance=dist,
                          penalty_strokes=1, messages=msgs)

    return ShotResult(valid=True, final_pos=endpoint, distance=dist, messages=msgs)


def apply_shot(state: HoleState,
               dir_key: str,
               roll: int | None) -> tuple[HoleState, ShotResult]:
    """Execute one shot. Returns (new_state, result). State is unchanged on invalid shot."""
    result = compute_shot(state, dir_key, roll)
    if not result.valid:
        return state, result

    strokes  = state.strokes + 1 + result.penalty_strokes
    complete = result.final_pos == state.hole.pin
    new_state = HoleState(
        hole=state.hole, ball=result.final_pos, prev=state.ball,
        strokes=strokes, complete=complete,
        history=state.history + [state.ball],
    )
    return new_state, result

# ── Scoring ────────────────────────────────────────────────────────────────────

_SCORE_NAMES: dict[int, str] = {
    -5: "Ostrich",   -4: "Condor",  -3: "Albatross",
    -2: "Eagle",     -1: "Birdie",
     0: "Par",
     1: "Bogey",      2: "Double Bogey",  3: "Triple Bogey",
}

def score_label(strokes: int, par: int) -> str:
    diff = strokes - par
    return _SCORE_NAMES.get(diff, f"+{diff}" if diff > 0 else str(diff))

# ── UI helpers ─────────────────────────────────────────────────────────────────

def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _prompt(prompt: str, valid: set[str]) -> str:
    while True:
        try:
            raw = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit
        if raw in valid:
            return raw
        print(f"  Options: {' '.join(sorted(valid))}")


def _lie_label(state: HoleState) -> str:
    bc, br  = state.ball
    terrain = state.hole.grid[br][bc]
    pc, pr  = state.hole.pin
    if terrain == Terrain.FAIRWAY and abs(bc - pc) <= 2 and abs(br - pr) <= 2:
        return "green"
    return terrain.value

# ── Interactive play ───────────────────────────────────────────────────────────

def _roll_dice() -> tuple[int, int]:
    return random.randint(1, 6), random.randint(1, 6)


def play_hole(hole: HoleData, mulligans: int) -> tuple[int, int]:
    """
    Play one hole interactively.
    Returns (strokes, mulligans_remaining).
    The mulligan offer appears on the FIRST roll of each hole only.
    """
    state      = HoleState.start(hole)
    first_roll = True

    while not state.complete:
        _clear()
        print(render_hole_with_legend(hole, ball_pos=state.ball, mulligans=mulligans, ghost_pos=set(state.history)))

        print(f"\n  Stroke {state.strokes + 1}  ·  Lie: {_lie_label(state)}")

        # Roll
        d1, d2 = _roll_dice()
        print(f"\n  Rolled:  [{d1}]  [{d2}]")

        # Choose die, putt, or mulligan reroll
        terrain = hole.grid[state.ball[1]][state.ball[0]]
        while True:
            parts = ["[1]", "[2]", "[p] putt"]
            if first_roll:
                parts.append("[m] free reroll")
            elif mulligans > 0:
                parts.append(f"[m] mulligan ({mulligans} left)")
            print(f"  {'  '.join(parts)}")

            valid = {'1', '2', 'p'}
            if first_roll or mulligans > 0:
                valid.add('m')
            choice = _prompt("  > ", valid)

            if choice == 'm':
                if first_roll:
                    first_roll = False          # free — no pool cost
                else:
                    mulligans -= 1
                d1, d2 = _roll_dice()
                print(f"  Rerolled:  [{d1}]  [{d2}]")
            else:
                first_roll = False
                break

        if choice == 'p':
            roll = None
            print("  Putt — 1 square.")
        else:
            roll = d1 if choice == '1' else d2
            dist, desc = _base_dist(terrain, roll)
            print(f"  {desc}")

        # Direction — retry loop for invalid shots
        print(f"\n{_COMPASS}")
        while True:
            key = _prompt("  Direction > ", set(DIRS))
            state, result = apply_shot(state, key, roll)
            if not result.valid:
                print(f"\n  ✗ {result.error}  Choose a different direction.")
            else:
                print()
                for msg in result.messages:
                    print(f"  {msg}")
                break

        if state.complete:
            _clear()
            print(render_hole_with_legend(hole, ball_pos=state.ball, mulligans=mulligans, ghost_pos=set(state.history)))
            label = score_label(state.strokes, hole.par)
            print(f"\n  ⛳  Hole {hole.number} — {state.strokes} strokes"
                  f"  (par {hole.par})  {label}")
        else:
            _clear()
            print(render_hole_with_legend(hole, ball_pos=state.ball, mulligans=mulligans, ghost_pos=set(state.history)))
            input("\n  [Enter] to take next shot...")

    input("\n  [Enter] to continue...")
    return state.strokes, mulligans


def play_course(course: CourseData) -> None:
    """Play all 18 holes with a shared mulligan pool and print a final scorecard."""
    scores:    list[int] = []
    mulligans: int       = MULLIGANS_PER_COURSE

    for hole in course.holes:
        strokes, mulligans = play_hole(hole, mulligans)
        scores.append(strokes)
        played_par = sum(h.par for h in course.holes[:len(scores)])
        diff       = sum(scores) - played_par
        sign       = f"+{diff}" if diff > 0 else str(diff)
        print(f"  After hole {hole.number}:  {sum(scores)} total  "
              f"({sign} vs par)  ·  {mulligans} mulligans left")
        input("  [Enter] for next hole...")

    _print_scorecard(course, scores)


def _print_scorecard(course: CourseData, scores: list[int]) -> None:
    _clear()
    total = sum(scores)
    par   = course.total_par
    diff  = total - par
    sign  = f"+{diff}" if diff > 0 else str(diff)

    print(f"\n  {'═' * 44}")
    print(f"  {course.name}")
    print(f"  Final Scorecard")
    print(f"  {'─' * 44}")
    print(f"  {'#':>2}  {'Par':>3}  {'Score':>5}  {'±Par':>5}  Result")
    print(f"  {'─' * 44}")
    for s, h in zip(scores, course.holes):
        d     = s - h.par
        dsign = f"+{d}" if d > 0 else str(d)
        print(f"  {h.number:>2}   {h.par:>3}   {s:>5}  {dsign:>5}  {score_label(s, h.par)}")
    print(f"  {'─' * 44}")
    print(f"  {'Total':>13}  {total:>5}  {sign:>5}  {score_label(total, par)}")
    print(f"  {'═' * 44}\n")
