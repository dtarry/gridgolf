"""Entry point: generate a course and browse holes interactively."""
from __future__ import annotations
import sys
import io

# Ensure UTF-8 output on Windows consoles that default to cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from .generator import generate_course
from .renderer  import render_course_summary, render_hole_with_legend


def main() -> None:
    seed   = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    course = generate_course("Procedural Pines Golf Club", seed=seed)

    print(render_course_summary(course))

    idx = 0
    while True:
        hole = course.holes[idx]
        print(render_hole_with_legend(hole))
        print(f"\n  Hole {idx+1}/18  —  [Enter] next  [p] prev  [#] jump  [q] quit")
        try:
            raw = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if raw == "q":
            break
        elif raw == "p":
            idx = (idx - 1) % 18
        elif raw.isdigit() and 1 <= int(raw) <= 18:
            idx = int(raw) - 1
        else:
            idx = (idx + 1) % 18


if __name__ == "__main__":
    main()
