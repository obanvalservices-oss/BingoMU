"""
JewelBingo control panel (Mac + Windows) — Start/Stop, pattern editor, resume, history.

No Terminal required for day-to-day use:
  python panel.py
  or double-click 0-Panel.command
"""

from __future__ import annotations

import io
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Optional

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


class TextRedirect(io.TextIOBase):
    """Pipe print() into the panel log."""

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
        self.title("JewelBingo — Panel")
        self.geometry("920x720")
        self.minsize(780, 600)

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

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        top = ttk.Frame(self)
        top.pack(fill=tk.X, **pad)

        ttk.Label(top, text="JewelBingo", font=("Helvetica", 18, "bold")).pack(
            side=tk.LEFT
        )
        self.status_lbl = ttk.Label(top, text="Listo", foreground="#2a6")
        self.status_lbl.pack(side=tk.RIGHT)

        # Controls
        ctrl = ttk.LabelFrame(self, text="Control")
        ctrl.pack(fill=tk.X, **pad)

        row1 = ttk.Frame(ctrl)
        row1.pack(fill=tk.X, **pad)
        self.btn_start = ttk.Button(row1, text="▶  START", command=self._start)
        self.btn_start.pack(side=tk.LEFT, padx=4)
        self.btn_stop = ttk.Button(
            row1, text="■  STOP", command=self._stop, state=tk.DISABLED
        )
        self.btn_stop.pack(side=tk.LEFT, padx=4)

        ttk.Radiobutton(
            row1, text="TEMPLATE", variable=self.mode_var, value="template"
        ).pack(side=tk.LEFT, padx=8)
        ttk.Radiobutton(
            row1, text="AUTO", variable=self.mode_var, value="auto"
        ).pack(side=tk.LEFT, padx=4)

        ttk.Label(row1, text="Countdown").pack(side=tk.LEFT, padx=(16, 2))
        ttk.Spinbox(
            row1, from_=0, to=30, width=4, textvariable=self.countdown_var
        ).pack(side=tk.LEFT)
        ttk.Label(row1, text="Max juegos").pack(side=tk.LEFT, padx=(12, 2))
        ttk.Spinbox(
            row1, from_=1, to=100, width=4, textvariable=self.max_games_var
        ).pack(side=tk.LEFT)

        row2 = ttk.Frame(ctrl)
        row2.pack(fill=tk.X, **pad)
        ttk.Checkbutton(
            row2,
            text="RESUME (partida ya en curso)",
            variable=self.resume_var,
            command=self._toggle_resume,
        ).pack(side=tk.LEFT)
        ttk.Label(row2, text="Quedan").pack(side=tk.LEFT, padx=(12, 2))
        self.left_spin = ttk.Spinbox(
            row2, from_=0, to=14, width=4, textvariable=self.left_var, state=tk.DISABLED
        )
        self.left_spin.pack(side=tk.LEFT)
        ttk.Checkbutton(row2, text="Dry-run", variable=self.dry_var).pack(
            side=tk.LEFT, padx=12
        )
        ttk.Label(
            row2, text="ESC / F8 también paran", foreground="#666"
        ).pack(side=tk.RIGHT)

        # Pattern editor
        pat = ttk.LabelFrame(
            self, text="Patrón TEMPLATE (editable — 4× cada joya, centro FREE)"
        )
        pat.pack(fill=tk.X, **pad)
        grid_f = ttk.Frame(pat)
        grid_f.pack(**pad)
        for r in range(5):
            row_vars: list[tk.StringVar] = []
            for c in range(5):
                v = tk.StringVar(value="B")
                row_vars.append(v)
                cb = ttk.Combobox(
                    grid_f,
                    textvariable=v,
                    values=CELL_CHOICES,
                    width=5,
                    state="readonly",
                )
                cb.grid(row=r, column=c, padx=2, pady=2)
                if r == 2 and c == 2:
                    v.set("FREE")
                    cb.configure(state=tk.DISABLED)
            self._cell_vars.append(row_vars)

        prow = ttk.Frame(pat)
        prow.pack(fill=tk.X, **pad)
        ttk.Button(prow, text="Guardar patrón", command=self._save_pattern).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(
            prow, text="Reset ChatGPT default", command=self._reset_pattern
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(prow, text="Validar", command=self._validate_pattern_ui).pack(
            side=tk.LEFT, padx=4
        )
        legend = "  ".join(f"{k}={JEWEL_NAMES[k].replace('Jewel of ', '')}" for k in JEWEL_TYPES)
        ttk.Label(prow, text=legend, foreground="#555").pack(side=tk.RIGHT)

        # History
        hist = ttk.LabelFrame(self, text="Historial / aprendizaje")
        hist.pack(fill=tk.X, **pad)
        self.hist_lbl = ttk.Label(hist, text="…", justify=tk.LEFT)
        self.hist_lbl.pack(anchor=tk.W, **pad)
        ttk.Button(hist, text="Actualizar stats", command=self._refresh_history).pack(
            anchor=tk.W, padx=8, pady=2
        )

        # Log
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill=tk.BOTH, expand=True, **pad)
        self.log = scrolledtext.ScrolledText(
            logf, height=16, wrap=tk.WORD, font=("Menlo", 11)
        )
        self.log.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self._append_log(
            "Panel listo. Pon Chrome Remote Desktop visible y pulsa START.\n"
            "Cada partida se guarda en logs/history.jsonl y alimenta priors.\n"
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
            messagebox.showerror("Patrón inválido", "\n".join(errs))
            return
        path = save_active_template(tmpl, name="panel_custom")
        self._append_log(f"Patrón guardado → {path}\n")
        messagebox.showinfo("OK", f"Patrón guardado:\n{path}")

    def _reset_pattern(self) -> None:
        tmpl = default_template()
        for r in range(5):
            for c in range(5):
                self._cell_vars[r][c].set(tmpl[r][c])
        save_active_template(tmpl, name="chatgpt_default")
        self._append_log("Patrón restaurado al default ChatGPT.\n")

    def _validate_pattern_ui(self) -> None:
        errs = validate_template(self._pattern_from_grid())
        if errs:
            messagebox.showerror("Inválido", "\n".join(errs))
        else:
            messagebox.showinfo("OK", "Patrón válido (4× cada joya + FREE).")

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
            self.hist_lbl.configure(
                text=f"{summary}\nPriors (n={n}): {top}"
            )
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
            text="CORRIENDO…" if running else "Listo",
            foreground="#c40" if running else "#2a6",
        )

    def _start(self) -> None:
        if self._running:
            return
        if not CAL_PATH.exists():
            messagebox.showerror(
                "Sin calibración",
                f"No existe {CAL_PATH}\nCorre el wizard de calibración primero.",
            )
            return

        tmpl = self._pattern_from_grid()
        if self.mode_var.get() == "template":
            errs = validate_template(tmpl)
            if errs:
                messagebox.showerror("Patrón inválido", "\n".join(errs))
                return
            try:
                save_active_template(tmpl, name="panel_active")
            except Exception as e:
                messagebox.showerror("Error guardando patrón", str(e))
                return

        resume = bool(self.resume_var.get())
        left = int(self.left_var.get()) if resume else None
        if resume and not (0 <= left <= 14):
            messagebox.showerror("RESUME", "Quedan debe ser 0–14")
            return

        self._set_running(True)
        self._append_log(
            f"\n—— START mode={self.mode_var.get()} resume={resume} "
            f"left={left} countdown={self.countdown_var.get()}s ——\n"
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
                    print("  ¡Listo!")

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
        self._append_log("—— STOP / fin ——\n")

    def _stop(self) -> None:
        if self._bot:
            print("STOP solicitado…")
            self._bot.stop()
        self._append_log("STOP pulsado.\n")

    def _on_close(self) -> None:
        if self._running and self._bot:
            self._bot.stop()
        self.destroy()


def main() -> int:
    app = JewelBingoPanel()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
