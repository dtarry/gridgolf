from __future__ import annotations
from .models import Terrain, TERRAIN_PROPS, HoleData, CourseData

_RESET = "\033[0m"
_BOLD  = "\033[1m"

# Foreground color to use for symbols drawn inside each block.
_FG: dict[Terrain, str] = {
    Terrain.FAIRWAY: "\033[38;5;22m",   # dark green on bright fairway
    Terrain.ROUGH:   "\033[38;5;22m",   # dark green on medium rough
    Terrain.TREES:   "\033[38;5;64m",   # lighter on dark forest
    Terrain.BUNKER:  "\033[38;5;94m",   # dark brown on sand
    Terrain.WATER:   "\033[97m",        # white on blue
    Terrain.SLOPE:   "\033[97m",        # white on brown
}

_FAIRWAY_BG = TERRAIN_PROPS[Terrain.FAIRWAY].bg
_WHITE_BG   = "\033[107m"


def _block(bg: str, fg: str, ch: str) -> str:
    """One cell: character + trailing space on bg/fg, then reset.
    Result is always 2 terminal columns wide."""
    return f"{bg}{fg}{ch} {_RESET}"


def _plain(bg: str) -> str:
    """One empty cell: two spaces on bg, then reset."""
    return f"{bg}  {_RESET}"


def render_hole(hole: HoleData,
                ball_pos: tuple[int, int] | None = None) -> str:
    tc, tr    = hole.tee
    pc, pr    = hole.pin
    direction = "left" if pc < tc else "right"
    offset    = abs(pc - tc)

    rows = len(hole.grid)
    cols = len(hole.grid[0]) if hole.grid else 0
    border = f"  +{'─' * (cols * 2)}+"

    lines: list[str] = [
        f"  {_BOLD}Hole {hole.number:>2}  ·  Par {hole.par}{_RESET}",
        f"  Tee col {tc+1}  →  Pin col {pc+1}  ({direction}, {offset} cols)",
        border,
    ]

    for r in range(rows):
        row = "  |"
        for c in range(cols):
            if (c, r) == hole.pin:
                row += _block(_WHITE_BG, f"{_BOLD}\033[30m", "O")
            elif (c, r) == hole.tee:
                row += _block(_WHITE_BG, f"{_BOLD}\033[30m", "T")
            elif ball_pos == (c, r):
                row += _block("\033[43m", f"{_BOLD}\033[30m", "@")
            else:
                t  = hole.grid[r][c]
                bg = TERRAIN_PROPS[t].bg
                fg = _FG[t]
                if t == Terrain.SLOPE:
                    row += _block(bg, fg, hole.slope_dirs.get((c, r), "↗"))
                else:
                    row += _plain(bg)
        row += "|"
        lines.append(row)

    lines.append(border)
    return "\n".join(lines)


# ── Legend ────────────────────────────────────────────────────────────────────

def _build_legend() -> list[str]:
    lines = [
        f"  {'─'*24}",
        f"  {'Legend':^24}",
        f"  {'─'*24}",
    ]
    for t in Terrain:
        props  = TERRAIN_PROPS[t]
        swatch = f"{props.bg}  {_RESET}"
        if t == Terrain.SLOPE:
            lines.append(
                f"  {swatch}  {t.value:<8}  {props.shot_factor:.0%}"
                f"  \033[37m↑↗→↘↓↙←↖{_RESET}"
            )
        else:
            lines.append(f"  {swatch}  {t.value:<8}  {props.shot_factor:.0%}")
    lines += [
        f"  {_WHITE_BG}{_BOLD}\033[30mT {_RESET}  tee box",
        f"  {_WHITE_BG}{_BOLD}\033[30mO {_RESET}  pin",
    ]
    return lines


_LEGEND_LINES = _build_legend()


def _wind_lines(hole: HoleData) -> list[str]:
    w = 24
    sep   = f"  {'─'*w}"
    label = "calm" if hole.wind_speed == 0 else f"{hole.wind_dir}  {'▪' * hole.wind_speed}"
    return [sep, f"  Wind: {label}", sep, "  Mulligans: "]


def render_hole_with_legend(hole: HoleData,
                            ball_pos: tuple[int, int] | None = None) -> str:
    hole_lines   = render_hole(hole, ball_pos).splitlines()
    legend_lines = _LEGEND_LINES[:] + _wind_lines(hole)

    n = max(len(hole_lines), len(legend_lines))
    hole_lines   += [""] * (n - len(hole_lines))
    legend_lines += [""] * (n - len(legend_lines))

    return "\n".join(f"{h}  {leg}" for h, leg in zip(hole_lines, legend_lines))


# ── Course summary ────────────────────────────────────────────────────────────

def _terrain_counts(hole: HoleData) -> dict[Terrain, int]:
    counts: dict[Terrain, int] = {}
    for row in hole.grid:
        for cell in row:
            counts[cell] = counts.get(cell, 0) + 1
    return counts


def _hole_tags(hole: HoleData) -> str:
    counts = _terrain_counts(hole)
    total  = sum(counts.values())
    tags   = []
    for t in (Terrain.WATER, Terrain.BUNKER, Terrain.TREES, Terrain.SLOPE):
        if counts.get(t, 0) / total > 0.06:
            swatch = f"{TERRAIN_PROPS[t].bg}  {_RESET}"
            tags.append(f"{swatch}{t.value}")
    return "  ".join(tags) if tags else "open"


def render_course_summary(course: CourseData) -> str:
    w = 52
    lines = [
        f"\n{_BOLD}{'═'*w}{_RESET}",
        f"  {_BOLD}{course.name}{_RESET}",
        f"  Total par: {course.total_par}  ·  18 holes",
        f"{'─'*w}",
        f"  {'#':>2}  {'Par'}  Features",
        f"{'─'*w}",
    ]
    for hole in course.holes:
        lines.append(f"  {hole.number:>2}   {hole.par}   {_hole_tags(hole)}")
    lines.append(f"{'═'*w}\n")
    return "\n".join(lines)
