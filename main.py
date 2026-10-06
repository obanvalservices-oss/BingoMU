"""CLI entrypoint for the Jewel Bingo bot (Mac + Windows)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.control import install_kill_hotkey
from src.fsm import BingoBot
from src.patterns import format_template, validate_template
from src.types import TEMPLATE_CHATGPT, Calibration, PlacementMode


def default_cal_path() -> Path:
    return ROOT / "assets" / "calibration" / "default.json"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MU Online Jewel Bingo bot (Mac/Windows)")
    p.add_argument("--cal", type=Path, default=default_cal_path())
    p.add_argument(
        "--mode",
        choices=["auto", "template"],
        default="template",
        help="Jewel placement: auto=Auto-Place button, template=ChatGPT pattern (default)",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-mc", action="store_true")
    p.add_argument(
        "--sims",
        type=int,
        default=600,
        help="Monte Carlo sims per decision (lower = faster clicks)",
    )
    p.add_argument("--max-games", type=int, default=None)
    p.add_argument("--log-dir", type=Path, default=ROOT / "logs")
    p.add_argument(
        "--countdown",
        type=float,
        default=5.0,
        help="Seconds to bring Remote Desktop to front before first click",
    )
    p.add_argument("--show-pattern", action="store_true", help="Print ChatGPT pattern and exit")
    return p.parse_args()


def interactive_mode() -> PlacementMode:
    print("\n=== Placement mode ===")
    print("  [1] AUTO      — click Auto-Place (random board)")
    print("  [2] TEMPLATE  — place ChatGPT pattern manually (recommended)")
    print()
    print(format_template(TEMPLATE_CHATGPT))
    print()
    choice = input("Choose 1 or 2 [default 2]: ").strip() or "2"
    return PlacementMode.AUTO if choice == "1" else PlacementMode.TEMPLATE


def pre_start_countdown(seconds: float) -> None:
    seconds = max(0.0, float(seconds))
    if seconds <= 0:
        return
    print()
    print("=" * 56)
    print("  Pon Chrome Remote Desktop al FRENTE (Jewel Bingo).")
    print("  Minimiza o mueve la Terminal.")
    print(f"  Empieza en {seconds:.0f}s  |  F8 = parar")
    print("=" * 56)
    remaining = int(seconds)
    while remaining > 0:
        print(f"  {remaining}...", flush=True)
        time.sleep(1.0)
        remaining -= 1
    print("  ¡Empezando!", flush=True)


def main() -> int:
    args = parse_args()
    if args.show_pattern:
        errs = validate_template(TEMPLATE_CHATGPT)
        print(format_template())
        print("valid" if not errs else "INVALID: " + "; ".join(errs))
        return 0 if not errs else 1

    if not args.cal.exists():
        print(f"Calibration not found: {args.cal}")
        print("Run the calibration wizard first:")
        print("  python tools/calibrate_wizard.py")
        return 1

    # If launched without explicit mode via launcher scripts, ask
    if "--mode" in sys.argv:
        mode = PlacementMode(args.mode)
    else:
        mode = interactive_mode()

    cal = Calibration.load(str(args.cal))
    bot = BingoBot(
        calibration=cal,
        placement_mode=mode,
        dry_run=args.dry_run,
        use_mc=not args.no_mc,
        n_sims=args.sims,
        max_games=args.max_games,
        log_dir=str(args.log_dir),
        template_dir=str(ROOT / "assets" / "templates"),
    )
    stop_listener = install_kill_hotkey(bot.controller, keys=("esc", "f8"))
    print("Running. ESC = stop (also F8 / Fn+F8). FAILSAFE = mouse to screen corner.")
    pre_start_countdown(args.countdown)
    try:
        bot.run()
    finally:
        if stop_listener:
            stop_listener()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
