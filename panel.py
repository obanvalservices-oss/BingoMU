"""
JewelBingo control panel (Mac + Windows).

Classic tk widgets + safe startup (errors go to panel_error.log and a dialog).
"""

from __future__ import annotations

import io
import os
import sys
import threading
import time
import traceback
from pathlib import Path

# Must be before tkinter on macOS
os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

import tkinter as tk
from tkinter import messagebox
from typing import Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ERROR_LOG = ROOT / "panel_error.log"

BG = "#f5f5f5"
FG = "#111111"
ACCENT = "#1b6b3a"
BTN = "#dddddd"
LOG_BG = "#111111"
LOG_FG = "#eeeeee"

CAL_PATH = ROOT / "assets" / "calibration" / "default.json"


def _log_crash(where: str, exc: BaseException) -> None:
    msg = f"{where}: {exc}\n{traceback.format_exc()}"
    try:
        ERROR_LOG.write_text(msg, encoding="utf-8")
    except Exception:
        pass
    print(msg, file=sys.stderr)


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
        try:
            self.geometry("880x680")
        except Exception:
            pass

        self._bot = None
        self._thread = None
        self._stop_listener = None
        self._running = False
        self._cell_vars: list[list[tk.StringVar]] = []

        self.mode_var = tk.StringVar(value="template")
        self.countdown_var = tk.IntVar(value=5)
        self.max_games_var = tk.IntVar(value=1)
        self.resume_var = tk.BooleanVar(value=False)
        self.left_var = tk.IntVar(value=5)
        self.dry_var = tk.BooleanVar(value=False)

        # Build UI first (always visible), then load data
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            self._load_pattern_into_grid()
        except Exception as e:
            self._append_log(f"Patron: {e}\n")

        try:
            self._refresh_history()
        except Exception as e:
            self.hist_lbl.configure(text=f"Historial: {e}")

        self.after(100, self._bring_front)

    def _bring_front(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _build_ui(self) -> None:
        from src.types import JEWEL_NAMES, JEWEL_TYPES

        cell_choices = list(JEWEL_TYPES) + ["FREE"]

        root = tk.Frame(self, bg=BG, padx=12, pady=10)
        root.pack(fill=tk.BOTH, expand=True)

        head = tk.Frame(root, bg=BG)
        head.pack(fill=tk.X)
        tk.Label(
            head, text="JewelBingo", font=("Arial", 18, "bold"), bg=BG, fg=FG
        ).pack(side=tk.LEFT)
        self.status_lbl = tk.Label(
            head, text="Listo", font=("Arial", 12, "bold"), bg=BG, fg=ACCENT
        )
        self.status_lbl.pack(side=tk.RIGHT)

        # --- Control ---
        ctrl = tk.LabelFrame(root, text="Control", bg=BG, fg=FG, padx=8, pady=6)
        ctrl.pack(fill=tk.X, pady=6)

        r1 = tk.Frame(ctrl, bg=BG)
        r1.pack(fill=tk.X)
        self.btn_start = tk.Button(
            r1, text="START", command=self._start, bg="#a5d6a7", fg=FG, width=10
        )
        self.btn_start.pack(side=tk.LEFT, padx=3)
        self.btn_stop = tk.Button(
            r1, text="STOP", command=self._stop, bg="#ef9a9a", fg=FG, width=10,
            state=tk.DISABLED,
        )
        self.btn_stop.pack(side=tk.LEFT, padx=3)

        tk.Radiobutton(
            r1, text="TEMPLATE", variable=self.mode_var, value="template",
            bg=BG, fg=FG, activebackground=BG, selectcolor=BG,
        ).pack(side=tk.LEFT, padx=6)
        tk.Radiobutton(
            r1, text="AUTO", variable=self.mode_var, value="auto",
            bg=BG, fg=FG, activebackground=BG, selectcolor=BG,
        ).pack(side=tk.LEFT)

        tk.Label(r1, text="Countdown", bg=BG, fg=FG).pack(side=tk.LEFT, padx=(12, 2))
        tk.Spinbox(
            r1, from_=0, to=30, width=4, textvariable=self.countdown_var
        ).pack(side=tk.LEFT)
        tk.Label(r1, text="Max", bg=BG, fg=FG).pack(side=tk.LEFT, padx=(8, 2))
        tk.Spinbox(
            r1, from_=1, to=100, width=4, textvariable=self.max_games_var
        ).pack(side=tk.LEFT)

        r2 = tk.Frame(ctrl, bg=BG)
        r2.pack(fill=tk.X, pady=4)
        tk.Checkbutton(
            r2, text="RESUME", variable=self.resume_var,
            command=self._toggle_resume, bg=BG, fg=FG, selectcolor=BG,
            activebackground=BG,
        ).pack(side=tk.LEFT)
        tk.Label(r2, text="Quedan", bg=BG, fg=FG).pack(side=tk.LEFT, padx=(8, 2))
        self.left_spin = tk.Spinbox(
            r2, from_=0, to=14, width=4, textvariable=self.left_var, state=tk.DISABLED
        )
        self.left_spin.pack(side=tk.LEFT)
        tk.Checkbutton(
            r2, text="Dry-run", variable=self.dry_var,
            bg=BG, fg=FG, selectcolor=BG, activebackground=BG,
        ).pack(side=tk.LEFT, padx=8)
        tk.Label(r2, text="ESC/F8 = stop", bg=BG, fg="#666666").pack(side=tk.RIGHT)

        # --- Pattern ---
        pat = tk.LabelFrame(
            root, text="Patron TEMPLATE (centro FREE, 4 de cada)", bg=BG, fg=FG,
            padx=8, pady=6,
        )
        pat.pack(fill=tk.X, pady=4)

        grid = tk.Frame(pat, bg=BG)
        grid.pack()
        for r in range(5):
            row_vars: list[tk.StringVar] = []
            for c in range(5):
                v = tk.StringVar(value="B")
                row_vars.append(v)
                if r == 2 and c == 2:
                    v.set("FREE")
                    tk.Label(
                        grid, text="FREE", width=6, bg="#cccccc", fg=FG,
                        relief=tk.SUNKEN,
                    ).grid(row=r, column=c, padx=2, pady=2)
                else:
                    menu = tk.OptionMenu(grid, v, *cell_choices)
                    menu.config(width=4, bg="white", fg=FG, highlightthickness=0)
                    menu.grid(row=r, column=c, padx=2, pady=2)
            self._cell_vars.append(row_vars)

        prow = tk.Frame(pat, bg=BG)
        prow.pack(fill=tk.X, pady=4)
        tk.Button(prow, text="Guardar", command=self._save_pattern, bg=BTN).pack(
            side=tk.LEFT, padx=2
        )
        tk.Button(prow, text="Reset ChatGPT", command=self._reset_pattern, bg=BTN).pack(
            side=tk.LEFT, padx=2
        )
        tk.Button(prow, text="Validar", command=self._validate_pattern_ui, bg=BTN).pack(
            side=tk.LEFT, padx=2
        )
        legend = " ".join(
            f"{k}={JEWEL_NAMES[k].replace('Jewel of ', '')}" for k in JEWEL_TYPES
        )
        tk.Label(prow, text=legend, bg=BG, fg="#555555", font=("Arial", 9)).pack(
            side=tk.RIGHT
        )

        # --- History ---
        hist = tk.LabelFrame(root, text="Historial", bg=BG, fg=FG, padx=8, pady=4)
        hist.pack(fill=tk.X, pady=4)
        self.hist_lbl = tk.Label(
            hist, text="...", bg=BG, fg=FG, justify=tk.LEFT, anchor="w",
            wraplength=820,
        )
        self.hist_lbl.pack(fill=tk.X)
        tk.Button(
            hist, text="Actualizar", command=self._refresh_history, bg=BTN
        ).pack(anchor=tk.W, pady=2)

        # --- Log ---
        logf = tk.LabelFrame(root, text="Log", bg=BG, fg=FG, padx=4, pady=4)
        logf.pack(fill=tk.BOTH, expand=True, pady=4)
        self.log = tk.Text(
            logf, height=12, bg=LOG_BG, fg=LOG_FG, insertbackground=LOG_FG,
            font=("Courier", 11), wrap=tk.WORD,
        )
        sb = tk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._append_log(
            "Panel OK. Remote Desktop al frente -> START.\n"
            f"Si falla, mira: {ERROR_LOG}\n"
        )

    def _toggle_resume(self) -> None:
        self.left_spin.configure(
            state=tk.NORMAL if self.resume_var.get() else tk.DISABLED
        )

    def _pattern_from_grid(self) -> list[list[str]]:
        return [[self._cell_vars[r][c].get() for c in range(5)] for r in range(5)]

    def _load_pattern_into_grid(self) -> None:
        from src.patterns import load_active_template

        tmpl = load_active_template()
        for r in range(5):
            for c in range(5):
                self._cell_vars[r][c].set(tmpl[r][c])

    def _save_pattern(self) -> None:
        from src.patterns import save_active_template, validate_template

        tmpl = self._pattern_from_grid()
        errs = validate_template(tmpl)
        if errs:
            messagebox.showerror("Patron invalido", "\n".join(errs))
            return
        path = save_active_template(tmpl, name="panel_custom")
        self._append_log(f"Guardado: {path}\n")
        messagebox.showinfo("OK", f"Guardado:\n{path}")

    def _reset_pattern(self) -> None:
        from src.patterns import default_template, save_active_template

        tmpl = default_template()
        for r in range(5):
            for c in range(5):
                self._cell_vars[r][c].set(tmpl[r][c])
        save_active_template(tmpl, name="chatgpt_default")
        self._append_log("Reset ChatGPT OK\n")

    def _validate_pattern_ui(self) -> None:
        from src.patterns import validate_template

        errs = validate_template(self._pattern_from_grid())
        if errs:
            messagebox.showerror("Invalido", "\n".join(errs))
        else:
            messagebox.showinfo("OK", "Patron valido")

    def _refresh_history(self) -> None:
        from src.history import history_summary, load_learned_priors, rebuild_learned_priors

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

    def _append_log(self, text: str) -> None:
        def _do() -> None:
            try:
                self.log.insert(tk.END, text)
                self.log.see(tk.END)
            except Exception:
                pass

        try:
            self.after(0, _do)
        except Exception:
            pass

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.btn_start.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.btn_stop.configure(state=tk.NORMAL if running else tk.DISABLED)
        self.status_lbl.configure(
            text="CORRIENDO" if running else "Listo",
            fg="#b71c1c" if running else ACCENT,
        )

    def _start(self) -> None:
        if self._running:
            return
        if not CAL_PATH.exists():
            messagebox.showerror(
                "Sin calibracion",
                f"Falta:\n{CAL_PATH}\nCorre 2-Calibrar.command primero.",
            )
            return

        from src.patterns import save_active_template, validate_template
        from src.types import Calibration, PlacementMode
        from src.fsm import BingoBot
        from src.control import install_kill_hotkey

        tmpl = self._pattern_from_grid()
        if self.mode_var.get() == "template":
            errs = validate_template(tmpl)
            if errs:
                messagebox.showerror("Patron invalido", "\n".join(errs))
                return
            save_active_template(tmpl, name="panel_active")

        resume = bool(self.resume_var.get())
        left = int(self.left_var.get()) if resume else None

        self._set_running(True)
        self._append_log(
            f"\nSTART mode={self.mode_var.get()} resume={resume} left={left}\n"
        )

        def worker() -> None:
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = TextRedirect(self._append_log)
            sys.stderr = TextRedirect(self._append_log)
            try:
                cd = int(self.countdown_var.get())
                for i in range(cd, 0, -1):
                    if self._bot and self._bot.controller.stopped:
                        break
                    print(f"  {i}...")
                    time.sleep(1.0)
                if cd > 0:
                    print("Listo!")

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
                _log_crash("bot_run", e)
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
        try:
            self._refresh_history()
        except Exception:
            pass
        self._append_log("Fin / STOP\n")

    def _stop(self) -> None:
        if self._bot:
            self._bot.stop()
        self._append_log("STOP\n")

    def _on_close(self) -> None:
        if self._running and self._bot:
            self._bot.stop()
        self.destroy()


def main() -> int:
    print("Opening JewelBingo Panel…", flush=True)
    try:
        # Lazy-import heavy deps after announcing
        app = JewelBingoPanel()
        print("Window created — if you don't see it, check Mission Control / other desktop.", flush=True)
        app.mainloop()
        return 0
    except Exception as e:
        _log_crash("main", e)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "JewelBingo Panel Error",
                f"{e}\n\nDetalle en:\n{ERROR_LOG}",
            )
            root.destroy()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
