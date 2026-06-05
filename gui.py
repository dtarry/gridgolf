"""Tkinter GUI for Grid Golf — mouse-driven interface."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from .generator import WIDTH, HEIGHT, generate_course
from .models    import Terrain, HoleData, CourseData
from .game      import (HoleState, apply_shot, compute_shot, score_label,
                        MULLIGANS_PER_COURSE, DIRS, _roll_dice, _base_dist)

# ── Visual constants ───────────────────────────────────────────────────────────

CELL = 24

TERRAIN_BG: dict[Terrain, str] = {
    Terrain.FAIRWAY: "#5FFF00",
    Terrain.ROUGH:   "#5F8700",
    Terrain.TREES:   "#005F00",
    Terrain.BUNKER:  "#FFD787",
    Terrain.WATER:   "#0087FF",
    Terrain.SLOPE:   "#875F00",
}

_DARK   = "#1a1a1a"
_WHITE  = "#FFFFFF"
_YELLOW = "#FFD700"
_DIM    = "#555555"


def _score_color(strokes: int, par: int) -> str:
    d = strokes - par
    if   d <= -2: return _YELLOW    # eagle or better
    elif d == -1: return "#44FF88"  # birdie
    elif d ==  0: return _WHITE     # par
    elif d ==  1: return "#FFAA00"  # bogey
    else:         return "#FF4444"  # double bogey+


# ── Start / New-Course dialog ──────────────────────────────────────────────────

def _show_start_dialog(root: tk.Tk,
                       default_seed: int = 42) -> tuple[int, int] | None:
    """
    Show a modal dialog for seed entry and course-length selection.
    Returns (seed, holes_to_play) or None if the window is closed.
    """
    result: list[tuple[int, int] | None] = [None]

    dlg = tk.Toplevel(root)
    dlg.title("Grid Golf")
    dlg.configure(bg=_DARK)
    dlg.resizable(False, False)
    dlg.grab_set()   # modal

    # Centre on the screen.
    dlg.update_idletasks()
    dw, dh = 320, 220
    sw = dlg.winfo_screenwidth()
    sh = dlg.winfo_screenheight()
    dlg.geometry(f"{dw}x{dh}+{(sw - dw) // 2}+{(sh - dh) // 2}")

    tk.Label(dlg, text="Grid Golf", bg=_DARK, fg=_YELLOW,
             font=("Consolas", 20, "bold")).pack(pady=(20, 8))

    # Seed row
    seed_row = tk.Frame(dlg, bg=_DARK)
    seed_row.pack(pady=6)
    tk.Label(seed_row, text="Seed:", bg=_DARK, fg=_WHITE,
             font=("Consolas", 11)).pack(side="left", padx=(0, 8))
    seed_var = tk.StringVar(value=str(default_seed))
    tk.Entry(seed_row, textvariable=seed_var, width=8,
             bg="#333333", fg=_WHITE, insertbackground=_WHITE,
             font=("Consolas", 13), relief="flat", bd=4).pack(side="left")

    # Course-length buttons
    btn_row = tk.Frame(dlg, bg=_DARK)
    btn_row.pack(pady=14)

    def _start(holes: int) -> None:
        try:
            seed = int(seed_var.get())
        except ValueError:
            seed = 42
        result[0] = (seed, holes)
        dlg.destroy()

    BTN = dict(width=11, height=2, font=("Consolas", 11, "bold"),
               relief="raised", bd=3, activebackground="#666666")
    tk.Button(btn_row, text="Front 9",    bg="#444444", fg=_WHITE,
              command=lambda: _start(9),  **BTN).pack(side="left", padx=8)
    tk.Button(btn_row, text="Full Course", bg="#444444", fg=_WHITE,
              command=lambda: _start(18), **BTN).pack(side="left", padx=8)

    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    root.wait_window(dlg)
    return result[0]


# ── Main application ───────────────────────────────────────────────────────────

class GolfApp:

    def __init__(self, root: tk.Tk, course: CourseData,
                 holes_to_play: int = 18, seed: int = 42) -> None:
        self.root          = root
        self.course        = course
        self.holes_to_play = holes_to_play   # 9 or 18
        self.seed          = seed
        self.mulligans     = MULLIGANS_PER_COURSE
        self.scores: list[int] = []

        # Turn state
        self.state: HoleState | None = None
        self.hole_idx  = 0
        self.roll      = (1, 1)
        self.chosen    = None
        self.choosing  = False
        self.first_roll = True
        self.valid_moves:   dict[tuple[int, int], str] = {}
        self.penalty_moves: set[tuple[int, int]]       = set()

        self.root.title("Grid Golf")
        self.root.resizable(False, False)
        self.root.configure(bg=_DARK)

        self._build_ui()
        self._start_hole()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        GRID_W = WIDTH  * CELL
        GRID_H = HEIGHT * CELL

        # ── Column 0: game grid ────────────────────────────────────────────────
        self.canvas = tk.Canvas(
            self.root, width=GRID_W, height=GRID_H,
            bg="#111111", highlightthickness=2, highlightbackground="#333333",
        )
        self.canvas.grid(row=0, column=0, padx=(8, 4), pady=8, sticky="n")
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        # ── Column 1: controls ────────────────────────────────────────────────
        self.root.grid_columnconfigure(1, minsize=240)
        ctrl = tk.Frame(self.root, bg=_DARK)
        ctrl.grid(row=0, column=1, padx=4, pady=8, sticky="ns")

        def lbl(text="", fg=_WHITE, size=10, bold=False):
            return tk.Label(ctrl, text=text, bg=_DARK, fg=fg, anchor="w",
                            font=("Consolas", size, "bold" if bold else "normal"))

        def sep():
            tk.Frame(ctrl, bg="#444444", height=1).pack(fill="x", pady=5)

        # New Course button (top)
        tk.Button(ctrl, text="New Course", command=self._new_game,
                  bg="#334455", fg=_WHITE, activebackground="#446677",
                  font=("Consolas", 9, "bold"), relief="raised",
                  width=14).pack(anchor="e", pady=(0, 4))

        self.lbl_hole   = lbl(size=11, bold=True)
        self.lbl_hole.pack(anchor="w")
        self.lbl_stroke = lbl(fg="#AAAAAA")
        self.lbl_stroke.pack(anchor="w", pady=(0, 2))
        sep()

        self.lbl_wind = lbl(fg="#88AACC")
        self.lbl_wind.pack(anchor="w")
        self.lbl_mull = lbl(fg="#CCCC88")
        self.lbl_mull.pack(anchor="w", pady=(0, 2))
        sep()

        # 2×2 action buttons
        action = tk.Frame(ctrl, bg=_DARK)
        action.pack(pady=6)
        BTN = dict(width=6, height=2, font=("Consolas", 16, "bold"),
                   relief="raised", bd=3, activebackground="#555555")

        self.btn_d1   = tk.Button(action, text="?", bg="#333333", fg=_WHITE,
                                  command=lambda: self._pick("d1"), **BTN)
        self.btn_d1.grid(row=0, column=0, padx=5, pady=4)

        self.btn_d2   = tk.Button(action, text="?", bg="#333333", fg=_WHITE,
                                  command=lambda: self._pick("d2"), **BTN)
        self.btn_d2.grid(row=0, column=1, padx=5, pady=4)

        self.btn_putt = tk.Button(action, text="P", bg="#333333", fg=_WHITE,
                                  command=lambda: self._pick("p"), **BTN)
        self.btn_putt.grid(row=1, column=0, padx=5, pady=4)

        self.btn_mull = tk.Button(action, text="Mulli", bg="#333333", fg=_WHITE,
                                  command=self._mulligan, **BTN)
        self.btn_mull.grid(row=1, column=1, padx=5, pady=4)

        sep()

        self.lbl_dist = lbl(fg=_YELLOW)
        self.lbl_dist.pack(anchor="w", pady=(0, 4))

        sep()

        # Message log
        log_fr = tk.Frame(ctrl, bg=_DARK)
        log_fr.pack(fill="both", expand=True)
        sb = tk.Scrollbar(log_fr)
        sb.pack(side="right", fill="y")
        self.log = tk.Text(
            log_fr, width=26, height=14,
            bg="#111111", fg="#CCCCCC", font=("Consolas", 9),
            state="disabled", wrap="word", yscrollcommand=sb.set,
        )
        self.log.pack(side="left", fill="both", expand=True)
        sb.config(command=self.log.yview)

        # ── Column 2: scorecard ───────────────────────────────────────────────
        self.root.grid_columnconfigure(2, minsize=145)
        self.sc_frame = tk.Frame(self.root, bg=_DARK)
        self.sc_frame.grid(row=0, column=2, padx=(4, 8), pady=8, sticky="n")
        self._build_scorecard()

    def _build_scorecard(self) -> None:
        """Build (or rebuild) the scorecard table inside self.sc_frame."""
        for w in self.sc_frame.winfo_children():
            w.destroy()

        parent = self.sc_frame
        HDR = ("Consolas", 9, "bold")
        ROW = ("Consolas", 9)
        PAD = dict(padx=2, pady=1)

        def cell(text, r, c, fg=_WHITE, bg=_DARK, font=ROW, w=5):
            tk.Label(parent, text=text, bg=bg, fg=fg, font=font,
                     width=w, anchor="center").grid(
                         row=r, column=c, sticky="ew", **PAD)

        def hdr(text, r, c):
            cell(text, r, c, fg=_YELLOW, bg="#333333", font=HDR)

        def divrow(r, thick=False):
            tk.Frame(parent, bg="#666666" if thick else "#444444",
                     height=2 if thick else 1).grid(
                         row=r, column=0, columnspan=3,
                         sticky="ew", pady=2)

        # Title
        tk.Label(parent, text="SCORECARD", bg=_DARK, fg=_YELLOW,
                 font=("Consolas", 9, "bold")).grid(
                     row=0, column=0, columnspan=3, pady=(0, 4))

        hdr("#", 1, 0); hdr("Par", 1, 1); hdr("Score", 1, 2)
        divrow(2)

        self.score_cells: dict[int, tk.Label] = {}
        cur = 3
        holes = self.course.holes[:self.holes_to_play]
        nine  = min(9, self.holes_to_play)

        # Front nine (always present)
        for i in range(nine):
            h = holes[i]
            cell(str(h.number), cur, 0, fg="#AAAAAA")
            cell(str(h.par),    cur, 1, fg="#AAAAAA")
            sc = tk.Label(parent, text="–", bg=_DARK, fg=_DIM,
                          font=ROW, width=5, anchor="center")
            sc.grid(row=cur, column=2, sticky="ew", **PAD)
            self.score_cells[h.number] = sc
            cur += 1

        divrow(cur); cur += 1
        front_par = sum(h.par for h in holes[:nine])
        cell("F9", cur, 0, fg=_YELLOW, bg="#222222", font=HDR)
        cell(str(front_par), cur, 1, fg="#AAAAAA", bg="#222222", font=HDR)
        self.lbl_front_total = tk.Label(parent, text="–", bg="#222222",
                                        fg=_DIM, font=HDR, width=5, anchor="center")
        self.lbl_front_total.grid(row=cur, column=2, sticky="ew", **PAD)
        cur += 1

        if self.holes_to_play == 18:
            divrow(cur, thick=True); cur += 1
            # Back nine
            for i in range(9, 18):
                h = holes[i]
                cell(str(h.number), cur, 0, fg="#AAAAAA")
                cell(str(h.par),    cur, 1, fg="#AAAAAA")
                sc = tk.Label(parent, text="–", bg=_DARK, fg=_DIM,
                              font=ROW, width=5, anchor="center")
                sc.grid(row=cur, column=2, sticky="ew", **PAD)
                self.score_cells[h.number] = sc
                cur += 1

            divrow(cur); cur += 1
            back_par = sum(h.par for h in holes[9:])
            cell("B9",  cur, 0, fg=_YELLOW, bg="#222222", font=HDR)
            cell(str(back_par), cur, 1, fg="#AAAAAA", bg="#222222", font=HDR)
            self.lbl_back_total = tk.Label(parent, text="–", bg="#222222",
                                           fg=_DIM, font=HDR, width=5, anchor="center")
            self.lbl_back_total.grid(row=cur, column=2, sticky="ew", **PAD)
            cur += 1

            divrow(cur, thick=True); cur += 1
            total_par = sum(h.par for h in holes)
            cell("TOT", cur, 0, fg=_YELLOW, bg="#333333", font=HDR)
            cell(str(total_par), cur, 1, fg="#AAAAAA", bg="#333333", font=HDR)
            self.lbl_total = tk.Label(parent, text="–", bg="#333333",
                                      fg=_DIM, font=HDR, width=5, anchor="center")
            self.lbl_total.grid(row=cur, column=2, sticky="ew", **PAD)
        else:
            # Front 9 only — F9 row doubles as the total
            self.lbl_back_total = self.lbl_front_total  # alias so update code works
            self.lbl_total      = self.lbl_front_total

    def _update_scorecard(self) -> None:
        holes  = self.course.holes[:self.holes_to_play]
        front  = 0
        back   = 0
        fp     = sum(h.par for h in holes[:min(9, self.holes_to_play)])
        bp     = sum(h.par for h in holes[9:]) if self.holes_to_play == 18 else 0

        for i, score in enumerate(self.scores):
            h     = holes[i]
            color = _score_color(score, h.par)
            self.score_cells[h.number].config(text=str(score), fg=color)
            if i < 9:
                front += score
            else:
                back  += score

        played = len(self.scores)
        if played >= min(9, self.holes_to_play):
            self.lbl_front_total.config(
                text=str(front), fg=_score_color(front, fp))
        if self.holes_to_play == 18:
            if played > 9:
                self.lbl_back_total.config(
                    text=str(back), fg=_score_color(back, bp))
            if played == 18:
                self.lbl_total.config(
                    text=str(front + back),
                    fg=_score_color(front + back, fp + bp))

    # ── Game management ────────────────────────────────────────────────────────

    def _new_game(self) -> None:
        """Open the start dialog and, if confirmed, reset to a new course."""
        opts = _show_start_dialog(self.root, default_seed=self.seed)
        if opts is None:
            return
        new_seed, new_holes = opts
        self.seed          = new_seed
        self.holes_to_play = new_holes
        self.course        = generate_course("Procedural Pines Golf Club",
                                              seed=new_seed)
        self.mulligans     = MULLIGANS_PER_COURSE
        self.scores        = []
        self.hole_idx      = 0

        # Clear the log
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

        self._build_scorecard()
        self._start_hole()

    # ── Game flow ──────────────────────────────────────────────────────────────

    def _start_hole(self) -> None:
        hole            = self.course.holes[self.hole_idx]
        self.state      = HoleState.start(hole)
        self.first_roll = True
        self._do_roll()

    def _do_roll(self) -> None:
        self.valid_moves.clear()
        self.penalty_moves.clear()
        self.roll     = _roll_dice()
        self.chosen   = None
        self.choosing = False
        self._log(f"Rolled  [{self.roll[0]}]  [{self.roll[1]}]")
        self._refresh()

    def _mulligan(self) -> None:
        if self.choosing:
            return
        if self.first_roll:
            self.first_roll = False
            self.roll = _roll_dice()
            self._log(f"Retry  [{self.roll[0]}]  [{self.roll[1]}]")
        elif self.mulligans > 0:
            self.mulligans -= 1
            self.roll = _roll_dice()
            self._log(f"Mulli  [{self.roll[0]}]  [{self.roll[1]}]"
                      f"  ({self.mulligans} left)")
        self._refresh()

    def _pick(self, choice: str) -> None:
        if self.choosing and choice != 'p':
            return
        self.first_roll = False
        self.chosen     = choice
        self.choosing   = True
        self._compute_valid_moves()
        bc, br  = self.state.ball
        terrain = self.state.hole.grid[br][bc]
        if choice == "p":
            self._log("Putt — 1 sq.  Click destination.")
        else:
            die_val = self.roll[0] if choice == "d1" else self.roll[1]
            _, desc = _base_dist(terrain, die_val)
            self._log(desc + ".  Click destination.")
        self._refresh()

    def _compute_valid_moves(self) -> None:
        roll = None if self.chosen == "p" else (
            self.roll[0] if self.chosen == "d1" else self.roll[1]
        )
        self.valid_moves.clear()
        self.penalty_moves.clear()
        for key in DIRS:
            result = compute_shot(self.state, key, roll)
            if result.valid:
                self.valid_moves[result.landing_pos] = key
                if result.penalty_strokes > 0:
                    self.penalty_moves.add(result.landing_pos)

    def _on_canvas_click(self, event: tk.Event) -> None:
        if not self.choosing:
            return
        c = event.x // CELL
        r = event.y // CELL
        if 0 <= c < WIDTH and 0 <= r < HEIGHT:
            pos = (c, r)
            if pos in self.valid_moves:
                self._shoot(self.valid_moves[pos])

    def _shoot(self, key: str) -> None:
        if not self.choosing:
            return
        roll = None if self.chosen == "p" else (
            self.roll[0] if self.chosen == "d1" else self.roll[1]
        )
        new_state, result = apply_shot(self.state, key, roll)
        if not result.valid:
            self._log(f"✗  {result.error}")
            return
        self.state = new_state
        for msg in result.messages:
            self._log(f"   {msg}")
        if self.state.complete:
            self.choosing = False
            label = score_label(self.state.strokes, self.state.hole.par)
            self._log(f"⛳  {self.state.strokes} strokes — {label}")
            self._refresh()
            self.root.after(1500, self._next_hole)
        else:
            self._do_roll()

    def _next_hole(self) -> None:
        self.scores.append(self.state.strokes)
        self._update_scorecard()
        if self.hole_idx + 1 >= self.holes_to_play:
            self._show_final_scorecard()
            return
        self.hole_idx += 1
        self._start_hole()

    def _show_final_scorecard(self) -> None:
        holes = self.course.holes[:self.holes_to_play]
        total = sum(self.scores)
        par   = sum(h.par for h in holes)
        diff  = total - par
        sign  = f"+{diff}" if diff > 0 else str(diff)
        lines = [self.course.name,
                 f"{'Front 9' if self.holes_to_play == 9 else 'Full Course'}",
                 f"Total  {total}  ({sign})", ""]
        for s, h in zip(self.scores, holes):
            d  = s - h.par
            ds = f"+{d}" if d > 0 else str(d)
            lines.append(f"  H{h.number:>2}  {s}  ({ds})  {score_label(s, h.par)}")
        messagebox.showinfo("Round Complete", "\n".join(lines))

    # ── Rendering ──────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        hole    = self.state.hole
        bc, br  = self.state.ball
        terrain = hole.grid[br][bc]

        self.lbl_hole.config(
            text=f"Hole {self.hole_idx + 1} / {self.holes_to_play}  ·  Par {hole.par}")
        near = (terrain == Terrain.FAIRWAY
                and abs(bc - hole.pin[0]) <= 2
                and abs(br - hole.pin[1]) <= 2)
        self.lbl_stroke.config(
            text=f"Stroke {self.state.strokes + 1}  ·  "
                 f"{'green' if near else terrain.value}")
        wind = ("Calm" if hole.wind_speed == 0
                else f"Wind {hole.wind_dir}  {'▪' * hole.wind_speed}")
        self.lbl_wind.config(text=wind)
        self.lbl_mull.config(text=f"Mulligans: {self.mulligans}")

        rolling  = not self.choosing and not self.state.complete
        choosing = self.choosing
        can_mull = rolling and (self.first_roll or self.mulligans > 0)

        def die_style(key):
            active = choosing and self.chosen == key
            return dict(bg=_YELLOW if active else "#333333",
                        fg="#000000" if active else _WHITE)

        self.btn_d1.config(text=str(self.roll[0]), **die_style("d1"))
        self.btn_d2.config(text=str(self.roll[1]), **die_style("d2"))
        self.btn_putt.config(**die_style("p"))
        self.btn_mull.config(
            text="Retry" if (rolling and self.first_roll) else "Mulli",
            bg="#444444" if can_mull else "#222222",
            fg=_WHITE    if can_mull else _DIM)

        self._en(self.btn_d1,   rolling)
        self._en(self.btn_d2,   rolling)
        self._en(self.btn_putt, rolling or choosing)
        self.btn_mull.config(state="normal" if can_mull else "disabled")

        if choosing:
            if self.chosen == "p":
                self.lbl_dist.config(text="Putt: 1 sq")
            else:
                die_val = self.roll[0] if self.chosen == "d1" else self.roll[1]
                dist, _ = _base_dist(terrain, die_val)
                self.lbl_dist.config(text=f"Distance: {dist} sq")
        else:
            self.lbl_dist.config(text="")

        self._draw_grid()

    def _en(self, btn: tk.Button, on: bool) -> None:
        btn.config(state="normal" if on else "disabled",
                   bg="#444444" if on else "#222222",
                   fg=_WHITE    if on else _DIM)

    def _cell_center(self, c: int, r: int) -> tuple[int, int]:
        return c * CELL + CELL // 2, r * CELL + CELL // 2

    def _draw_grid(self) -> None:
        self.canvas.delete("all")
        hole   = self.state.hole
        ghosts = set(self.state.history)
        bpos   = self.state.ball

        for r in range(HEIGHT):
            for c in range(WIDTH):
                x1, y1 = c * CELL,        r * CELL
                x2, y2 = x1 + CELL,       y1 + CELL
                mx, my  = x1 + CELL // 2, y1 + CELL // 2
                pos     = (c, r)
                t       = hole.grid[r][c]
                bg      = TERRAIN_BG[t]

                self.canvas.create_rectangle(
                    x1, y1, x2, y2, fill=bg, outline="#111111", width=1)

                if t == Terrain.SLOPE:
                    self.canvas.create_text(mx, my, text=hole.slope_dirs.get(pos, "↗"),
                                            fill=_WHITE, font=("Consolas", 10))

                if pos == hole.tee:
                    self.canvas.create_rectangle(x1, y1, x2, y2,
                                                 fill=_WHITE, outline="#111111")
                    self.canvas.create_text(mx, my, text="T", fill="#000000",
                                            font=("Consolas", 10, "bold"))
                elif pos == hole.pin:
                    self.canvas.create_rectangle(x1, y1, x2, y2,
                                                 fill=_WHITE, outline="#111111")
                    self.canvas.create_text(mx, my, text="O", fill="#000000",
                                            font=("Consolas", 10, "bold"))
                elif pos == bpos:
                    pad = 4
                    self.canvas.create_oval(x1+pad, y1+pad, x2-pad, y2-pad,
                                            fill=_YELLOW, outline="#CC8800", width=2)
                elif pos in ghosts:
                    pad = 6
                    self.canvas.create_oval(x1+pad, y1+pad, x2-pad, y2-pad,
                                            fill="", outline="#BBBBBB", width=1)

                if self.choosing and pos in self.valid_moves:
                    border = "#FF8800" if pos in self.penalty_moves else _YELLOW
                    self.canvas.create_rectangle(x1+1, y1+1, x2-1, y2-1,
                                                 fill="", outline=border, width=2)

        # ── History trail — line connecting every ghost to ball ───────────────
        trail = list(self.state.history) + [bpos]
        for i in range(len(trail) - 1):
            x1, y1 = self._cell_center(*trail[i])
            x2, y2 = self._cell_center(*trail[i + 1])
            self.canvas.create_line(x1, y1, x2, y2,
                                    fill="#555555", width=1, dash=(3, 3))

        # ── Shot-direction lines to each valid destination ────────────────────
        if self.choosing and self.valid_moves:
            bx, by = self._cell_center(*bpos)
            for dest in self.valid_moves:
                dx, dy = self._cell_center(*dest)
                self.canvas.create_line(bx, by, dx, dy,
                                        fill="#888866", width=1, dash=(2, 4))

    def _log(self, msg: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")


# ── Entry point ────────────────────────────────────────────────────────────────

def run_game(course: CourseData | None = None, seed: int = 42) -> None:
    """Show the start dialog then launch the game window."""
    root = tk.Tk()
    root.withdraw()   # hide until options are chosen

    opts = _show_start_dialog(root, default_seed=seed)
    if opts is None:
        root.destroy()
        return

    chosen_seed, holes_to_play = opts
    if course is None:
        course = generate_course("Procedural Pines Golf Club", seed=chosen_seed)

    root.deiconify()
    GolfApp(root, course, holes_to_play=holes_to_play, seed=chosen_seed)

    # Centre the fully-built window on the screen.
    root.update_idletasks()
    w  = root.winfo_width()
    h  = root.winfo_height()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    root.mainloop()
