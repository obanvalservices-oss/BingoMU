"""
JewelBingo control panel (Mac + Windows) — Start/Stop, pattern editor, resume, history.

Uses classic tk widgets (not ttk) so macOS system Tk does not show a blank window.
"""

from __future__ import annotations

import io
import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Optional

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.control import install_kill_hotkey
from src.fsm import BingoBot
from src.history import history_summary, load_learned_priors, rebuild_learned_priors
from src.patterns import (
    default_template,
    load_active_template,
    save_active_template,
    validate_template,
)
from src.types import JEWEL_NAMES, JEWEL_TYPES, Calibration, PlacementMode

CAL_PATH = ROOT / "assets" / "calibration" / "default.json"
CELL_CHOICES = list(JEWEL_TYPES) + ["FREE"]

# Explicit colors — macOS dark-mode + system Tk often paints ttk as invisible
BG = "#f4f4f0"
FG = "#1a1a1a"
ACCENT = "#1b6b3a"
BTN_BG = "#e8e4d8"
LOG_BG = "#1e1e1e"
LOG_FG = "#d6d6d6"


class TextRedirect(io.TextIOBase):
    def __init__(self, write_fn) -> None:
        super().__init__()
        self._write_fn = write_fn

    def write(self, s: str) -> int:
        if s:
            self._write_fn(s)
        return len(s) if s else 0

    def flush(self) -> None:
        pass


class JewelBingoPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("JewelBingo Panel")
        self.configure(bg=BG)
        self.geometry("900x700")
        self.minsize(720, 560)

        self._bot: Optional[BingoBot] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_listener = None
        self._running = False

        self.mode_var = tk.StringVar(value="template")
        self.countdown_var = tk.IntVar(value=5)
        self.max_games_var = tk.IntVar(value=1)
        self.resume_var = tk.BooleanVar(value=False)
        self.left_var = tk.IntVar(value=5)
        self.dry_var = tk.BooleanVar(value=False)

        self._cell_vars: list[list[tk.StringVar]] = []
        self._build()
        self._load_pattern_into_grid()
        self._refresh_history()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Force Mac to paint + bring to front
        self.update_idletasks()
        self.lift()
        self.attributes("-topmost", True)
        self.after(400, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def _lbl(self, parent, text, **kw) -> tk.Label:
        opts = {"bg": BG, "fg": FG, "anchor": "w"}
        opts.update(kw)
        return tk.Label(parent, text=text, **opts)

    def _btn(self, parent, text, cmd, **kw) -> tk.Button:
        opts = {
            "text": text,
            "command": cmd,
            "bg": BTN_BG,
            "fg": FG,
            "activebackground": "#ddd8c8",
            "relief": tk.RAISED,
            "padx": 10,
            "pady": 4,
        }
        opts.update(kw)
        return tk.Button(parent, **opts)

    def _build(self) -> None:
        outer = tk.Frame(self, bg=BG, padx=10, pady=8)
        outer.pack(fill=tk.BOTH, expand=True)

        # Header
        top = tk.Frame(outer, bg=BG)
        top.pack(fill=tk.X, pady=(0, 8))
        self._lbl(top, "JewelBingo", font=("Helvetica", 20, "bold")).pack(side=tk.LEFT)
        self.status_lbl = self._lbl(top, "Listo", fg=ACCENT, font=("Helvetica", 12, "bold"))
        self.status_lbl.pack(side=tk.RIGHT)

        # Control
        ctrl = tk.LabelFrame(
            outer, text=" Control ", bg=BG, fg=FG, padx=8, pady=6, font=("Helvetica", 11)
        )
        ctrl.pack(fill=tk.X, pady=4)

        row1 = tk.Frame(ctrl, bg=BG)
        row1.pack(fill=tk.X, pady=2)
        self.btn_start = self._btn(row1, "START", self._start, bg="#c8e6c9")
        self.btn_start.pack(side=tk.LEFT, padx=3)
        self.btn_stop = self._btn(row1, "STOP", self._stop, bg="#ffcdd2", state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=3)

        tk.Radiobutton(
            row1, text="TEMPLATE", variable=self.mode_var, value="template",
            bg=BG, fg=FG, selectcolor=BG, activebackground=BG,
        ).pack(side=tk.LEFT, padx=8)
        tk.Radiobutton(
            row1, text="AUTO", variable=self.mode_var, value="auto",
            bg=BG, fg=FG, selectcolor=BG, activebackground=BG,
        ).pack(side=tk.LEFT, padx=4)

        self._lbl(row1, "Countdown").pack(side=tk.LEFT, padx=(14, 2))
        tk.Spinbox(
            row1, from_=0, to=30, width=4, textvariable=self.countdown_var,
            bg="white", fg=FG,
        ).pack(side=tk.LEFT)
        self._lbl(row1, "Max juegos").pack(side=tk.LEFT, padx=(10, 2))
        tk.Spinbox(
            row1, from_=1, to=100, width=4, textvariable=self.max_games_var,
            bg="white", fg=FG,
        ).pack(side=tk.LEFT)

        row2 = tk.Frame(ctrl, bg=BG)
        row2.pack(fill=tk.X, pady=4)
        tk.Checkbutton(
            row2, text="RESUME (partida en curso)", variable=self.resume_var,
            command=self._toggle_resume, bg=BG, fg=FG, selectcolor=BG,
            activebackground=BG,
        ).pack(side=tk.LEFT)
        self._lbl(row2, "Quedan").pack(side=tk.LEFT, padx=(10, 2))
        self.left_spin = tk.Spinbox(
            row2, from_=0, to=14, width=4, textvariable=self.left_var,
            bg="white", fg=FG, state=tk.DISABLED,
        )
        self.left_spin.pack(side=tk.LEFT)
        tk.Checkbutton(
            row2, text="Dry-run", variable=self.dry_var,
            bg=BG, fg=FG, selectcolor=BG, activebackground=BG,
        ).pack(side=tk.LEFT, padx=10)
        self._lbl(row2, "ESC / F8 también paran", fg="#666666").pack(side=tk.RIGHT)

        # Pattern
        pat = tk.LabelFrame(
            outer,
            text=" Patron TEMPLATE (4x cada joya, centro FREE) ",
            bg=BG, fg=FG, padx=8, pady=6, font=("Helvetica", 11),
        )
        pat.pack(fill=tk.X, pady=4)

        grid_f = tk.Frame(pat, bg=BG)
        grid_f.pack(pady=4)
        for r in range(5):
            row_vars: list[tk.StringVar] = []
            for c in range(5):
                v = tk.StringVar(value="B")
                row_vars.append(v)
                if r == 2 and c == 2:
                    v.set("FREE")
                    cell = tk.Label(
                        grid_f, text="FREE", width=5, bg="#ddd", fg=FG,
                        relief=tk.SUNKEN, padx=4, pady=4,
                    )
                    cell.grid(row=r, column=c, padx=2, pady=2)
                else:
                    om = tk.OptionMenu(grid_f, v, *CELL_CHOICES)
                    om.config(bg="white", fg=FG, width=4, highlightthickness=0)
                    om["menu"].config(bg="white", fg=FG)
                    om.grid(row=r, column=c, padx=2, pady=2)
            self._cell_vars.append(row_vars)

        prow = tk.Frame(pat, bg=BG)
        prow.pack(fill=tk.X, pady=4)
        self._btn(prow, "Guardar patron", self._save_pattern).pack(side=tk.LEFT, padx=3)
        self._btn(prow, "Reset ChatGPT", self._reset_pattern).pack(side=tk.LEFT, padx=3)
        self._btn(prow, "Validar", self._validate_pattern_ui).pack(side=tk.LEFT, padx=3)
        legend = "  ".join(
            f"{k}={JEWEL_NAMES[k].replace('Jewel of ', '')}" for k in JEWEL_TYPES
        )
        self._lbl(prow, legend, fg="#555555", font=("Helvetica", 9)).pack(side=tk.RIGHT)

        # History
        hist = tk.LabelFrame(
            outer, text=" Historial / aprendizaje ", bg=BG, fg=FG,
            padx=8, pady=6, font=("Helvetica", 11),
        )
        hist.pack(fill=tk.X, pady=4)
        self.hist_lbl = self._lbl(hist, "...", justify=tk.LEFT, wraplength=860)
        self.hist_lbl.pack(anchor=tk.W, fill=tk.X)
        self._btn(hist, "Actualizar stats", self._refresh_history).pack(anchor=tk.W, pady=4)

        # Log
        logf = tk.LabelFrame(
            outer, text=" Log ", bg=BG, fg=FG, padx=6, pady=4, font=("Helvetica", 11)
        )
        logf.pack(fill=tk.BOTH, expand=True, pady=4)
        self.log = tk.Text(
            logf, height=14, wrap=tk.WORD, bg=LOG_BG, fg=LOG_FG,
            insertbackground=LOG_FG, font=("Courier", 11),
        )
        scroll = tk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._append_log(
            "Panel listo. Pon Chrome Remote Desktop visible y pulsa START.\n"
            "Cada partida se guarda en logs/history.jsonl.\n"
        )

    def _toggle_resume(self) -> None:
        self.left_spin.configure(
            state=tk.NORMAL if self.resume_var.get() else tk.DISABLED
        )

    def _pattern_from_grid(self) -> list[list[str]]:
        return [[self._cell_vars[r][c].get() for c in range(5)] for r in range(5)]

    def _load_pattern_into_grid(self) -> None:
        tmpl = load_active_template()
        for r in range(5):
            for c in range(5):
                self._cell_vars[r][c].set(tmpl[r][c])

    def _save_pattern(self) -> None:
        tmpl = self._pattern_from_grid()
        errs = validate_template(tmpl)
        if errs:
            messagebox.showerror("Patron invalido", "\n".join(errs))
            return
        path = save_active_template(tmpl, name="panel_custom")
        self._append_log(f"Patron guardado -> {path}\n")
        messagebox.showinfo("OK", f"Patron guardado:\n{path}")

    def _reset_pattern(self) -> None:
        tmpl = default_template()
        for r in range(5):
            for c in range(5):
                self._cell_vars[r][c].set(tmpl[r][c])
        save_active_template(tmpl, name="chatgpt_default")
        self._append_log("Patron restaurado al default ChatGPT.\n")

    def _validate_pattern_ui(self) -> None:
        errs = validate_template(self._pattern_from_grid())
        if errs:
            messagebox.showerror("Invalido", "\n".join(errs))
        else:
            messagebox.showinfo("OK", "Patron valido (4x cada joya + FREE).")

    def _refresh_history(self) -> None:
        try:
            rebuild_learned_priors()
            learned = load_learned_priors()
            summary = history_summary()
            n = learned.get("games", 0)
            overall = learned.get("overall") or {}
            top = ", ".join(
                f"{j}:{overall.get(j, 0):.0%}"
                for j, _ in sorted(overall.items(), key=lambda kv: -kv[1])[:4]
            )
            self.hist_lbl.configure(text=f"{summary}\nPriors (n={n}): {top}")
        except Exception as e:
            self.hist_lbl.configure(text=f"Historial: {e}")

    def _append_log(self, text: str) -> None:
        def _do() -> None:
            self.log.insert(tk.END, text)
            self.log.see(tk.END)

        self.after(0, _do)

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.btn_start.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.btn_stop.configure(state=tk.NORMAL if running else tk.DISABLED)
        self.status_lbl.configure(
            text="CORRIENDO..." if running else "Listo",
            fg="#b71c1c" if running else ACCENT,
        )

    def _start(self) -> None:
        if self._running:
            return
        if not CAL_PATH.exists():
            messagebox.showerror(
                "Sin calibracion",
                f"No existe {CAL_PATH}\nCorre el wizard de calibracion primero.",
            )
            return

        tmpl = self._pattern_from_grid()
        if self.mode_var.get() == "template":
            errs = validate_template(tmpl)
            if errs:
                messagebox.showerror("Patron invalido", "\n".join(errs))
                return
            try:
                save_active_template(tmpl, name="panel_active")
            except Exception as e:
                messagebox.showerror("Error guardando patron", str(e))
                return

        resume = bool(self.resume_var.get())
        left = int(self.left_var.get()) if resume else None
        if resume and left is not None and not (0 <= left <= 14):
            messagebox.showerror("RESUME", "Quedan debe ser 0-14")
            return

        self._set_running(True)
        self._append_log(
            f"\n-- START mode={self.mode_var.get()} resume={resume} "
            f"left={left} countdown={self.countdown_var.get()}s --\n"
        )

        def worker() -> None:
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = TextRedirect(self._append_log)
            sys.stderr = TextRedirect(self._append_log)
            try:
                cd = int(self.countdown_var.get())
                if cd > 0:
                    print(f"Countdown {cd}s — pon Remote Desktop al frente…")
                    for i in range(cd, 0, -1):
                        if self._bot and self._bot.controller.stopped:
                            break
                        print(f"  {i}...")
                        time.sleep(1.0)
                    print("  Listo!")

                cal = Calibration.load(str(CAL_PATH))
                mode = (
                    PlacementMode.AUTO
                    if self.mode_var.get() == "auto"
                    else PlacementMode.TEMPLATE
                )
                self._bot = BingoBot(
                    calibration=cal,
                    placement_mode=mode,
                    dry_run=bool(self.dry_var.get()),
                    use_mc=True,
                    n_sims=600,
                    max_games=1 if resume else int(self.max_games_var.get()),
                    log_dir=str(ROOT / "logs"),
                    template_dir=str(ROOT / "assets" / "templates"),
                    resume=resume,
                    resume_left=left,
                    template=tmpl,
                )
                self._stop_listener = install_kill_hotkey(
                    self._bot.controller, keys=("esc", "f8")
                )
                self._bot.run()
            except Exception as e:
                print(f"ERROR: {e}")
            finally:
                if self._stop_listener:
                    try:
                        self._stop_listener()
                    except Exception:
                        pass
                    self._stop_listener = None
                self._bot = None
                sys.stdout, sys.stderr = old_out, old_err
                self.after(0, self._on_worker_done)

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def _on_worker_done(self) -> None:
        self._set_running(False)
        self._refresh_history()
        self._append_log("-- STOP / fin --\n")

    def _stop(self) -> None:
        if self._bot:
            self._bot.stop()
        self._append_log("STOP pulsado.\n")

    def _on_close(self) -> None:
        if self._running and self._bot:
            self._bot.stop()
        self.destroy()


def main() -> int:
    try:
        app = JewelBingoPanel()
        app.mainloop()
    except Exception as e:
        print(f"Panel failed to open: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
