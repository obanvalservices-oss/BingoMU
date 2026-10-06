# Jewel Bingo Bot — Final (Mac + Windows)

Autonomous **Jewel Bingo** bot for MU Online via **Chrome Remote Desktop**.

- Runs on **Mac or Windows** (the Remote Desktop *client*).
- Do **not** install on the game PC.
- Placement modes: **TEMPLATE** (ChatGPT pattern, default) or **AUTO**.

## Jewels (right panel, top → bottom)

| Code | Name |
|------|------|
| B | Jewel of Bless |
| S | Jewel of Soul |
| CR | Jewel of Creation |
| H | Jewel of Harmony |
| L | Jewel of Life |
| C | Jewel of Chaos |

## ChatGPT pattern (TEMPLATE)

```
S  | H  | B  | L  | H
CR | C  | C  | L  | C
B  | H  | MU | S  | C
B  | CR | CR | B  | L
S  | CR | H  | S  | L
```

## Setup

### Mac
```bash
cd JewelBingo
chmod +x *.command install_mac.sh
./1-Instalar.command
```

### Windows
```bat
cd JewelBingo
1-Install.bat
```

## Usage

1. Open Chrome Remote Desktop → Jewel Bingo visible, window fixed.
2. **2-Calibrate** — guided clicks (panel, grid, Auto, boxes, 6 jewels…).
3. **3-Simulate** — offline solver using the ChatGPT board.
4. **4-Play-Template** — place ChatGPT pattern and play (recommended).
5. **5-Play-Auto** — use in-game Auto-Place.
6. **6-DryRun** — one dry-run game.
7. **F8** = stop. Mouse to screen corner = failsafe.

## CLI

```bash
python main.py --mode template --max-games 5
python main.py --mode auto --dry-run --max-games 1
python tools/calibrate_wizard.py
python tools/simulate_offline.py --template --games 20
python main.py --show-pattern
```

## Mac permissions

System Settings → Privacy & Security:
- Screen Recording
- Accessibility
