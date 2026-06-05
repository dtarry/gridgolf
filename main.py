"""Entry point — launches the GUI by default."""
from __future__ import annotations
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from .generator import generate_course


def main() -> None:
    seed   = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    course = generate_course("Procedural Pines Golf Club", seed=seed)

    from .gui import run_game
    run_game(course)


if __name__ == "__main__":
    main()
