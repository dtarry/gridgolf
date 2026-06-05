"""Tkinter GUI for Grid Golf — mouse-driven interface."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from .generator import WIDTH, HEIGHT, generate_course
from .models    import Terrain, HoleData, CourseData
from .game      import (HoleState, apply_shot, compute_shot, score_label,
                        MULLIGANS_PER_COURSE, DIRS, _roll_dice, _base_dist)

# ── Visual constants ───────────────────────────────────────────────────────────

CELL = 24   # pixels per grid cell

TERRAIN_BG: dict[Terrain, str] = {
    Terrain.FAIRWAY: "#5FFF00",
    Terrain.ROUGH:   "#5F8700",
    Terrain.TREES:   "#005F00",
    Terrain.BUNKER:  "#FFD787",
    Terrain.WATER:   "#0087FF",
    Terrain.SLOPE:   "#875F00",
}

_DARK   = "#1a1a1a"
_MID    = "#2d2d2d"
_WHITE  = "#FFFFFF"
_YELLOW = "#FFD700"
_DIM    = "#555555"

# Score colour by diff from par
def _score_color(strokes: int, par: int) -> str:
    d = strokes - par
    if   d <= -2: return "#FFD700"   # eagle or better – gold
    elif d == -1: return "#44FF88"   # birdie – green
    elif d ==  0: return _WHITE      # par – white
    elif d ==  1: return "#FFAA00"   # bogey – amber
    else:         return "#FF4444"   # double bogey+ – red


# ── Application ────────────────────────────────────────────────────────────────

class GolfApp:

    def __init__(self, root: tk.Tk, course: CourseData) -> None:
        self.root      = root
        self.course    = course
        self.hole_idx  = 0
        self.mulligans = MULLIGANS_PER_COURSE
        self.scores: list[int] = []

        # Turn state
        self.state: HoleState | None = None
        self.roll        = (1, 1)
        self.chosen      = None   # "d1" | "d2" | "p"
        self.choosing    = False
        self.first_roll  = True
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

        # 2×2 action buttons — all same style/size
        action = tk.Frame(ctrl, bg=_DARK)
        action.pack(pady=6)
        BTN = dict(width=6, height=2, font=("Consolas", 16, "bold"),
                   relief="raised", bd=3, activebackground="#555555")

        self.btn_d1 = tk.Button(action, text="?", bg="#333333", fg=_WHITE,
                                command=lambda: self._pick("d1"), **BTN)
        self.btn_d1.grid(row=0, column=0, padx=5, pady=4)

        self.btn_d2 = tk.Button(action, text="?", bg="#333333", fg=_WHITE,
                                command=lambda: self._pick("d2"), **BTN)
        self.btn_d2.grid(row=0, column=1, padx=5, pady=4)

        self.btn_putt = tk.Button(action, text="P", bg="#333333", fg=_WHITE,
                                  command=lambda: self._pick("p"), **BTN)
        self.btn_putt.grid(row=1, column=0, padx=5, pady=4)

        self.btn_mull = tk.Button(action, text="Mulli", bg="#333333", fg=_WHITE,
                                  command=self._mulligan, **BTN)
        self.btn_mull.grid(row=1, column=1, padx=5, pady=4)

        sep()

        # Distance hint
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
        sc_frame = tk.Frame(self.root, bg=_DARK)
        sc_frame.grid(row=0, column=2, padx=(4, 8), pady=8, sticky="n")
        self._build_scorecard(sc_frame)

    def _build_scorecard(self, parent: tk.Frame) -> None:
        """Build the static scorecard table; store mutable score cells."""
        BG, FG = _DARK, _WHITE
        HDR = ("Consolas", 9, "bold")
        ROW = ("Consolas", 9)
        PAD = dict(padx=3, pady=1)

        def hdr(text, r, c, span=1):
            tk.Label(parent, text=text, bg="#333333", fg=_YELLOW,
                     font=HDR, width=5, anchor="center").grid(
                         row=r, column=c, columnspan=span,
                         sticky="ew", padx=1, pady=1)

        def div(r, thick=False):
            tk.Frame(parent,
                     bg="#666666" if thick else "#444444",
                     height=2 if thick else 1).grid(
                         row=r, column=0, columnspan=3,
                         sticky="ew", pady=(2, 2))

        # Title
        tk.Label(parent, text="SCORECARD", bg=_DARK, fg=_YELLOW,
                 font=("Consolas", 9, "bold")).grid(
                     row=0, column=0, columnspan=3, pady=(0, 4))

        # Column headers
        hdr("#",     1, 0)
        hdr("Par",   1, 1)
        hdr("Score", 1, 2)
        div(2)

        self.score_cells: dict[int, tk.Label] = {}
        cur_row = 3

        for group_start, label in [(1, "FRONT"), (10, "BACK")]:
            for h_num in range(group_start, group_start + 9):
                hole = self.course.holes[h_num - 1]
                # Hole number
                tk.Label(parent, text=str(h_num), bg=_DARK, fg="#AAAAAA",
                         font=ROW, width=5, anchor="center").grid(
                             row=cur_row, column=0, sticky="ew", **PAD)
                # Par
                tk.Label(parent, text=str(hole.par), bg=_DARK, fg="#AAAAAA",
                         font=ROW, width=5, anchor="center").grid(
                             row=cur_row, column=1, sticky="ew", **PAD)
                # Score (mutable)
                sc = tk.Label(parent, text="–", bg=_DARK, fg=_DIM,
                              font=ROW, width=5, anchor="center")
                sc.grid(row=cur_row, column=2, sticky="ew", **PAD)
                self.score_cells[h_num] = sc
                cur_row += 1

            # Nine subtotal
            div(cur_row)
            cur_row += 1
            nine_par = sum(self.course.holes[i].par
                           for i in range(group_start - 1, group_start + 8))
            tk.Label(parent, text=label[:1] + "9", bg="#222222", fg=_YELLOW,
                     font=HDR, width=5, anchor="center").grid(
                         row=cur_row, column=0, sticky="ew", padx=1, pady=1)
            tk.Label(parent, text=str(nine_par), bg="#222222", fg="#AAAAAA",
                     font=HDR, width=5, anchor="center").grid(
                         row=cur_row, column=1, sticky="ew", padx=1, pady=1)
            lbl_nine = tk.Label(parent, text="–", bg="#222222", fg=_DIM,
                                font=HDR, width=5, anchor="center")
            lbl_nine.grid(row=cur_row, column=2, sticky="ew", padx=1, pady=1)
            if group_start == 1:
                self.lbl_front_total = lbl_nine
            else:
                self.lbl_back_total  = lbl_nine
            cur_row += 1
            div(cur_row, thick=True)
            cur_row += 1

        # Grand total
        tk.Label(parent, text="TOT", bg="#333333", fg=_YELLOW,
                 font=HDR, width=5, anchor="center").grid(
                     row=cur_row, column=0, sticky="ew", padx=1, pady=1)
        tk.Label(parent, text=str(self.course.total_par),
                 bg="#333333", fg="#AAAAAA",
                 font=HDR, width=5, anchor="center").grid(
                     row=cur_row, column=1, sticky="ew", padx=1, pady=1)
        self.lbl_total = tk.Label(parent, text="–", bg="#333333", fg=_DIM,
                                  font=HDR, width=5, anchor="center")
        self.lbl_total.grid(row=cur_row, column=2, sticky="ew", padx=1, pady=1)

    def _update_scorecard(self) -> None:
        """Refresh scorecard cells with current scores."""
        front, back = 0, 0
        front_par   = sum(h.par for h in self.course.holes[:9])
        back_par    = sum(h.par for h in self.course.holes[9:])

        for i, score in enumerate(self.scores):
            h_num = i + 1
            hole  = self.course.holes[i]
            color = _score_color(score, hole.par)
            self.score_cells[h_num].config(text=str(score), fg=color)
            if h_num <= 9:
                front += score
            else:
                back  += score

        played = len(self.scores)
        if played > 0:
            if played >= 9:
                self.lbl_front_total.config(
                    text=str(front),
                    fg=_score_color(front, front_par))
            if played > 9:
                self.lbl_back_total.config(
                    text=str(back),
                    fg=_score_color(back, back_par))
            total = front + back
            self.lbl_total.config(
                text=str(total),
                fg=_score_color(total, front_par + back_par if played == 18
                                else total))  # neutral while in progress

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
        if self.choosing:
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
                self.valid_moves[result.final_pos] = key
                if result.penalty_strokes > 0:
                    self.penalty_moves.add(result.final_pos)

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
        if self.hole_idx + 1 >= len(self.course.holes):
            self._show_final_scorecard()
            return
        self.hole_idx += 1
        self._start_hole()

    def _show_final_scorecard(self) -> None:
        total = sum(self.scores)
        par   = self.course.total_par
        diff  = total - par
        sign  = f"+{diff}" if diff > 0 else str(diff)
        lines = [self.course.name, f"Total  {total}  ({sign})", ""]
        for s, h in zip(self.scores, self.course.holes):
            d  = s - h.par
            ds = f"+{d}" if d > 0 else str(d)
            lines.append(f"  H{h.number:>2}  {s}  ({ds})  {score_label(s, h.par)}")
        messagebox.showinfo("Course Complete", "\n".join(lines))
        self.root.quit()

    # ── Rendering ──────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        hole    = self.state.hole
        bc, br  = self.state.ball
        terrain = hole.grid[br][bc]

        self.lbl_hole.config(
            text=f"Hole {self.hole_idx + 1} / 18  ·  Par {hole.par}")
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

        # Die buttons show current roll values; highlight chosen die
        def die_style(key):
            active = choosing and self.chosen == key
            return dict(bg=_YELLOW if active else "#333333",
                        fg="#000000" if active else _WHITE)

        self.btn_d1.config(text=str(self.roll[0]), **die_style("d1"))
        self.btn_d2.config(text=str(self.roll[1]), **die_style("d2"))
        self.btn_putt.config(**die_style("p"))
        self.btn_mull.config(
            text=("Retry" if (rolling and self.first_roll) else "Mulli"),
            bg="#444444" if can_mull else "#222222",
            fg=_WHITE    if can_mull else _DIM)

        self._en(self.btn_d1,   rolling)
        self._en(self.btn_d2,   rolling)
        self._en(self.btn_putt, rolling)
        self.btn_mull.config(state="normal" if can_mull else "disabled")

        # Distance hint
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

    def _log(self, msg: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")


# ── Entry point ────────────────────────────────────────────────────────────────

def run_game(course: CourseData | None = None, seed: int = 42) -> None:
    if course is None:
        course = generate_course("Procedural Pines Golf Club", seed=seed)
    root = tk.Tk()
    GolfApp(root, course)
    root.mainloop()
