"""Mouse / keyboard control relative to calibrated ROIs."""

from __future__ import annotations

import time
from typing import Callable, Optional

import pyautogui

from .types import JEWEL_TYPES, Calibration, Rect

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.08


class Controller:
    def __init__(self, calibration: Calibration, dry_run: bool = False) -> None:
        self.cal = calibration
        self.dry_run = dry_run
        self._kill = False

    def request_stop(self) -> None:
        self._kill = True

    @property
    def stopped(self) -> bool:
        return self._kill

    def click_xy(self, x: int, y: int, clicks: int = 1) -> None:
        if self._kill:
            return
        if self.dry_run:
            print(f"[dry-run] click ({x}, {y}) x{clicks}")
            return
        # Move first so GRD registers hover, then click (more reliable remotely)
        pyautogui.moveTo(x, y, duration=0.12)
        time.sleep(0.12)
        pyautogui.click(x, y, clicks=clicks)
        time.sleep(self.cal.click_delay_s)

    def click_rect(self, rect: Rect, clicks: int = 1) -> None:
        x, y = rect.center
        self.click_xy(x, y, clicks=clicks)

    def click_cell(self, row: int, col: int) -> None:
        """Click bingo cell (row, col) inside calibrated grid ROI."""
        g = self.cal.grid
        cell_w = g.w / 5
        cell_h = g.h / 5
        cx = int(g.x + (col + 0.5) * cell_w)
        cy = int(g.y + (row + 0.5) * cell_h)
        if self.dry_run:
            print(f"[dry-run] click cell ({row},{col}) -> ({cx},{cy})")
            return
        pyautogui.moveTo(cx, cy, duration=0.10)
        time.sleep(0.08)
        pyautogui.click(cx, cy)
        time.sleep(self.cal.place_delay_s)

    def click_jewel_btn(self, jewel: str) -> None:
        """Click right-panel jewel selector (B/S/CR/H/L/C)."""
        if jewel not in self.cal.jewel_btns:
            a = self.cal.auto_btn
            idx = list(JEWEL_TYPES).index(jewel) if jewel in JEWEL_TYPES else 0
            slot_h = max(18, a.h)
            cx = a.x + a.w // 2
            cy = a.y + a.h + 12 + idx * (slot_h + 6) + slot_h // 2
            self.click_xy(cx, cy)
            return
        self.click_rect(self.cal.jewel_btns[jewel])

    def select_jewel(self, jewel: str) -> None:
        """
        Reliably select a jewel type over GRD:
        click twice with a settle pause (first jewel often misses if too fast).
        """
        self.click_jewel_btn(jewel)
        self.wait(0.55)
        self.click_jewel_btn(jewel)
        self.wait(0.65)

    def click_top_left_box(self) -> None:
        """Fallback: calibrated boxes ROI center."""
        self.click_rect(self.cal.boxes)

    def click_xy_box(self, x: int, y: int) -> None:
        self.click_xy(x, y)

    def press_auto(self) -> None:
        self.click_rect(self.cal.auto_btn)

    def press_start(self) -> None:
        self.click_rect(self.cal.start_btn)

    def accept_reward(self) -> None:
        self.click_rect(self.cal.reward_btn)

    def wait(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end and not self._kill:
            time.sleep(0.05)


def install_kill_hotkey(
    controller: Controller,
    keys: tuple[str, ...] = ("esc", "f8"),
) -> Optional[Callable]:
    """Press Esc (or F8) to stop the bot. Returns stopper or None if pynput unavailable."""
    try:
        from pynput import keyboard
    except ImportError:
        return None

    watch = {k.lower() for k in keys}

    def on_press(k):
        try:
            name = getattr(k, "name", None)
            if name and name.lower() in watch:
                controller.request_stop()
                print(f"\n[kill] {name.upper()} pressed — stopping.")
        except Exception:
            pass

    listener = keyboard.Listener(on_press=on_press)
    listener.daemon = True
    listener.start()
    return listener.stop
