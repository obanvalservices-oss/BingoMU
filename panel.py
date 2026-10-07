"""
JewelBingo Panel — clean Mac/Windows control UI.

Layout (top → bottom):
  1. START / STOP / Ver calibración
  2. Modo + opciones
  3. Dónde arrancar (movimientos que quedan) — siempre visible
  4. Patrón 5×5
  5. Log en vivo

Bot runs in a subprocess (macOS-safe with Tk).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

import tkinter as tk
from tkinter import messagebox
from typing import Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ERROR_LOG = ROOT / "panel_error.log"
CAL_PATH = ROOT / "assets" / "calibration" / "default.json"

# Light, high-contrast palette (readable on macOS system Tk)
BG = "#f0eee8"
FG = "#1a1a1a"
MUTED = "#5c5c5c"
CARD = "#ffffff"
ACCENT = "#0d6b3a"
START_BG = "#2e7d32"
STOP_BG = "#c62828"
CAL_BG = "#1565c0"
BTN = "#e0ddd4"
LOG_BG = "#1a1a1a"
LOG_FG = "#e8e8e8"


def _log_crash(where: str, exc: BaseException) -> None:
    msg = f"{where}: {exc}\n{traceback.format_exc()}"
    try:
        ERROR_LOG.write_text(msg, encoding="utf-8")
    except Exception:
        pass
    print(msg, file=sys.stderr)


class JewelBingoPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("JewelBingo")
        self.configure(bg=BG)
        self.minsize(720, 640)
        self.geometry("820x780")

        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._running = False
        self._cell_vars: list[list[tk.StringVar]] = []

        self.mode_var = tk.StringVar(value="template")
        self.countdown_var = tk.IntVar(value=5)
        self.max_games_var = tk.IntVar(value=1)
        self.left_var = tk.IntVar(value=14)
        self.dry_var = tk.BooleanVar(value=False)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            self._load_pattern()
        except Exception as e:
            self._log(f"Patron: {e}\n")
        try:
            self._refresh_stats()
        except Exception as e:
            self.stats_var.set(str(e))

        self.left_var.trace_add("write", lambda *_: self._update_start_hint())
        self._update_start_hint()
        self.after(80, self._front)

    def _front(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    # ── UI ──────────────────────────────────────────────────────────

    def _card(self, parent: tk.Misc, title: str) -> tk.Frame:
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            wrap, text=title, bg=BG, fg=MUTED, font=("Arial", 10, "bold"),
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 4))
        body = tk.Frame(wrap, bg=CARD, highlightbackground="#d0cdc4", highlightthickness=1)
        body.pack(fill=tk.X)
        inner = tk.Frame(body, bg=CARD, padx=12, pady=10)
        inner.pack(fill=tk.X)
        return inner

    def _build(self) -> None:
        from src.types import JEWEL_NAMES, JEWEL_TYPES

        root = tk.Frame(self, bg=BG, padx=16, pady=12)
        root.pack(fill=tk.BOTH, expand=True)

        # Header
        head = tk.Frame(root, bg=BG)
        head.pack(fill=tk.X, pady=(0, 8))
        tk.Label(
            head, text="JewelBingo", bg=BG, fg=FG, font=("Arial", 22, "bold"),
        ).pack(side=tk.LEFT)
        self.status_lbl = tk.Label(
            head, text="Listo", bg=BG, fg=ACCENT, font=("Arial", 13, "bold"),
        )
        self.status_lbl.pack(side=tk.RIGHT)

        # 1) Actions
        actions = self._card(root, "1. CONTROL")
        row = tk.Frame(actions, bg=CARD)
        row.pack(fill=tk.X)
        self.btn_start = tk.Button(
            row, text="START", command=self._start,
            bg=START_BG, fg="white", font=("Arial", 13, "bold"),
            width=12, height=2, relief=tk.FLAT, cursor="hand2",
        )
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_stop = tk.Button(
            row, text="STOP", command=self._stop,
            bg=STOP_BG, fg="white", font=("Arial", 13, "bold"),
            width=12, height=2, relief=tk.FLAT, state=tk.DISABLED, cursor="hand2",
        )
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(
            row, text="Ver calibracion", command=self._show_calibration,
            bg=CAL_BG, fg="white", font=("Arial", 11, "bold"),
            width=16, height=2, relief=tk.FLAT, cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(
            row, text="ESC / F8 tambien paran", bg=CARD, fg=MUTED, font=("Arial", 9),
        ).pack(side=tk.RIGHT)

        # 2) Mode
        opts = self._card(root, "2. MODO")
        r = tk.Frame(opts, bg=CARD)
        r.pack(fill=tk.X)
        tk.Radiobutton(
            r, text="TEMPLATE (patron)", variable=self.mode_var, value="template",
            bg=CARD, fg=FG, selectcolor=CARD, activebackground=CARD,
            font=("Arial", 11),
        ).pack(side=tk.LEFT, padx=(0, 16))
        tk.Radiobutton(
            r, text="AUTO-PLACE", variable=self.mode_var, value="auto",
            bg=CARD, fg=FG, selectcolor=CARD, activebackground=CARD,
            font=("Arial", 11),
        ).pack(side=tk.LEFT, padx=(0, 24))
        tk.Label(r, text="Countdown", bg=CARD, fg=MUTED).pack(side=tk.LEFT)
        tk.Spinbox(
            r, from_=0, to=30, width=3, textvariable=self.countdown_var, font=("Arial", 11),
        ).pack(side=tk.LEFT, padx=(4, 16))
        tk.Label(r, text="Max juegos", bg=CARD, fg=MUTED).pack(side=tk.LEFT)
        tk.Spinbox(
            r, from_=1, to=50, width=3, textvariable=self.max_games_var, font=("Arial", 11),
        ).pack(side=tk.LEFT, padx=(4, 16))
        tk.Checkbutton(
            r, text="Dry-run", variable=self.dry_var,
            bg=CARD, fg=MUTED, selectcolor=CARD, activebackground=CARD,
        ).pack(side=tk.LEFT)

        # 3) Where to start — ALWAYS full width, impossible to miss
        start = self._card(root, "3. DONDE ARRANCAR")
        tk.Label(
            start,
            text="Cuantos movimientos QUEDAN en el juego ahora?",
            bg=CARD, fg=FG, font=("Arial", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            start,
            text="14 = partida nueva completa.   Menos de 14 = resume (no gasta card).",
            bg=CARD, fg=MUTED, font=("Arial", 10),
        ).pack(anchor="w", pady=(2, 8))

        picker = tk.Frame(start, bg=CARD)
        picker.pack(fill=tk.X)
        tk.Button(
            picker, text="−", width=4, height=1, font=("Arial", 16, "bold"),
            command=lambda: self._nudge(-1), bg=BTN, relief=tk.FLAT,
        ).pack(side=tk.LEFT)
        self.left_spin = tk.Spinbox(
            picker, from_=0, to=14, width=4, textvariable=self.left_var,
            font=("Arial", 28, "bold"), justify="center",
        )
        self.left_spin.pack(side=tk.LEFT, padx=10)
        tk.Button(
            picker, text="+", width=4, height=1, font=("Arial", 16, "bold"),
            command=lambda: self._nudge(1), bg=BTN, relief=tk.FLAT,
        ).pack(side=tk.LEFT)

        quick = tk.Frame(picker, bg=CARD)
        quick.pack(side=tk.LEFT, padx=20)
        tk.Label(quick, text="Atajos:", bg=CARD, fg=MUTED).pack(side=tk.LEFT, padx=(0, 6))
        for n, label in ((14, "Nueva"), (10, "10"), (7, "7"), (5, "5"), (3, "3"), (1, "1")):
            tk.Button(
                quick, text=label, width=5, bg=BTN, relief=tk.FLAT,
                command=lambda v=n: self.left_var.set(v),
            ).pack(side=tk.LEFT, padx=2)

        self.hint_lbl = tk.Label(
            start, text="", bg=CARD, fg=ACCENT, font=("Arial", 12, "bold"),
            anchor="w", justify="left",
        )
        self.hint_lbl.pack(fill=tk.X, pady=(10, 0))

        self.stats_var = tk.StringVar(value="")
        tk.Label(
            start, textvariable=self.stats_var, bg=CARD, fg=MUTED,
            font=("Arial", 9), anchor="w", justify="left", wraplength=760,
        ).pack(fill=tk.X, pady=(6, 0))

        # 4) Pattern
        pat = self._card(root, "4. PATRON TEMPLATE (editar y Guardar)")
        grid = tk.Frame(pat, bg=CARD)
        grid.pack()
        choices = list(JEWEL_TYPES) + ["FREE"]
        for r in range(5):
            row_vars: list[tk.StringVar] = []
            for c in range(5):
                v = tk.StringVar(value="B")
                row_vars.append(v)
                if r == 2 and c == 2:
                    v.set("FREE")
                    tk.Label(
                        grid, text="FREE", width=5, bg="#c8c8c8", fg=FG,
                        relief=tk.SUNKEN, font=("Arial", 10, "bold"),
                    ).grid(row=r, column=c, padx=2, pady=2)
                else:
                    om = tk.OptionMenu(grid, v, *choices)
                    om.config(width=4, bg="white", fg=FG, highlightthickness=0, font=("Arial", 10))
                    om.grid(row=r, column=c, padx=2, pady=2)
            self._cell_vars.append(row_vars)

        prow = tk.Frame(pat, bg=CARD)
        prow.pack(fill=tk.X, pady=(8, 0))
        tk.Button(prow, text="Guardar patron", command=self._save_pattern, bg=BTN, relief=tk.FLAT).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        tk.Button(prow, text="Reset ChatGPT", command=self._reset_pattern, bg=BTN, relief=tk.FLAT).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        tk.Button(prow, text="Validar", command=self._validate_pattern, bg=BTN, relief=tk.FLAT).pack(
            side=tk.LEFT
        )
        legend = "   ".join(f"{k}={JEWEL_NAMES[k].replace('Jewel of ', '')}" for k in JEWEL_TYPES)
        tk.Label(prow, text=legend, bg=CARD, fg=MUTED, font=("Arial", 8)).pack(side=tk.RIGHT)

        # 5) Live log — bottom, expands
        log_wrap = tk.Frame(root, bg=BG)
        log_wrap.pack(fill=tk.BOTH, expand=True, pady=(0, 0))
        tk.Label(
            log_wrap, text="5. LOG EN VIVO", bg=BG, fg=MUTED,
            font=("Arial", 10, "bold"), anchor="w",
        ).pack(fill=tk.X, pady=(0, 4))
        log_card = tk.Frame(log_wrap, bg=LOG_BG, highlightthickness=0)
        log_card.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(
            log_card, height=12, bg=LOG_BG, fg=LOG_FG, insertbackground=LOG_FG,
            font=("Courier", 11), wrap=tk.WORD, relief=tk.FLAT, padx=8, pady=8,
            borderwidth=0,
        )
        sb = tk.Scrollbar(log_card, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._log(
            "Listo.\n"
            "1) Ver calibracion si los clics fallan\n"
            "2) Elige TEMPLATE o AUTO\n"
            "3) Pon cuantos movimientos QUEDAN (14 = nueva)\n"
            "4) START\n"
        )

    # ── helpers ─────────────────────────────────────────────────────

    def _nudge(self, d: int) -> None:
        try:
            n = int(self.left_var.get())
        except Exception:
            n = 14
        self.left_var.set(max(0, min(14, n + d)))

    def _update_start_hint(self, *_a) -> None:
        try:
            left = int(self.left_var.get())
        except Exception:
            return
        left = max(0, min(14, left))
        done = 14 - left
        if left >= 14:
            self.hint_lbl.configure(
                text="→ Partida NUEVA  ·  empieza en movimiento 1 / 14",
                fg=ACCENT,
            )
        else:
            self.hint_lbl.configure(
                text=(
                    f"→ RESUME  ·  quedan {left}  ·  "
                    f"arranca en movimiento {done + 1} / 14  ·  ya hechos ~{done}"
                ),
                fg="#b71c1c" if left <= 3 else "#e65100",
            )

    def _log(self, text: str) -> None:
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
            text="CORRIENDO…" if running else "Listo",
            fg="#c62828" if running else ACCENT,
        )

    def _pattern(self) -> list[list[str]]:
        return [[self._cell_vars[r][c].get() for c in range(5)] for r in range(5)]

    def _load_pattern(self) -> None:
        from src.patterns import load_active_template

        tmpl = load_active_template()
        for r in range(5):
            for c in range(5):
                self._cell_vars[r][c].set(tmpl[r][c])

    def _save_pattern(self) -> None:
        from src.patterns import save_active_template, validate_template

        tmpl = self._pattern()
        errs = validate_template(tmpl)
        if errs:
            messagebox.showerror("Patron invalido", "\n".join(errs))
            return
        path = save_active_template(tmpl, name="panel_custom")
        self._log(f"Patron guardado → {path}\n")
        messagebox.showinfo("OK", "Patron guardado.")

    def _reset_pattern(self) -> None:
        from src.patterns import default_template, save_active_template

        tmpl = default_template()
        for r in range(5):
            for c in range(5):
                self._cell_vars[r][c].set(tmpl[r][c])
        save_active_template(tmpl, name="chatgpt_default")
        self._log("Patron = ChatGPT default\n")

    def _validate_pattern(self) -> None:
        from src.patterns import validate_template

        errs = validate_template(self._pattern())
        if errs:
            messagebox.showerror("Invalido", "\n".join(errs))
        else:
            messagebox.showinfo("OK", "Patron valido (4 de cada + FREE).")

    def _refresh_stats(self) -> None:
        from src.history import history_summary, load_learned_priors, rebuild_learned_priors

        rebuild_learned_priors()
        learned = load_learned_priors()
        n = learned.get("games", 0)
        self.stats_var.set(f"{history_summary()}  ·  priors n={n}")

    def _show_calibration(self) -> None:
        if not CAL_PATH.exists():
            messagebox.showerror("Sin calibracion", f"Falta:\n{CAL_PATH}")
            return
        self._log(
            "\n--- Ver calibracion ---\n"
            "Mueve Chrome Remote Desktop hasta que los recuadros coincidan.\n"
            "Q o ESC cierra la vista.\n"
        )
        env = os.environ.copy()
        env["TK_SILENCE_DEPRECATION"] = "1"
        try:
            subprocess.Popen(
                [
                    sys.executable, "-u",
                    str(ROOT / "tools" / "show_calibration.py"),
                    "--cal", str(CAL_PATH),
                ],
                cwd=str(ROOT),
                env=env,
            )
        except Exception as e:
            _log_crash("show_calibration", e)
            messagebox.showerror("Error", str(e))

    # ── run bot ─────────────────────────────────────────────────────

    def _start(self) -> None:
        if self._running:
            return
        if not CAL_PATH.exists():
            messagebox.showerror(
                "Sin calibracion",
                f"Falta:\n{CAL_PATH}\nUsa 2-Calibrar.command primero.",
            )
            return

        from src.patterns import save_active_template, validate_template

        tmpl = self._pattern()
        if self.mode_var.get() == "template":
            errs = validate_template(tmpl)
            if errs:
                messagebox.showerror("Patron invalido", "\n".join(errs))
                return
            save_active_template(tmpl, name="panel_active")

        left = max(0, min(14, int(self.left_var.get())))
        resume = left < 14
        mode = self.mode_var.get()
        cd = int(self.countdown_var.get())
        max_games = 1 if resume else int(self.max_games_var.get())

        cmd = [
            sys.executable, "-u", str(ROOT / "main.py"),
            "--mode", mode,
            "--countdown", str(cd),
            "--max-games", str(max_games),
            "--cal", str(CAL_PATH),
            "--log-dir", str(ROOT / "logs"),
        ]
        if resume:
            cmd += ["--resume", "--left", str(left)]
        if self.dry_var.get():
            cmd.append("--dry-run")

        self._set_running(True)
        if resume:
            self._log(f"\n▶ RESUME — quedan {left} (mov. {14 - left + 1}/14)\n")
        else:
            self._log("\n▶ Partida NUEVA (14 sorteos)\n")

        env = os.environ.copy()
        env["TK_SILENCE_DEPRECATION"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        try:
            self._proc = subprocess.Popen(
                cmd, cwd=str(ROOT), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except Exception as e:
            _log_crash("popen", e)
            messagebox.showerror("No se pudo iniciar", str(e))
            self._set_running(False)
            return

        def reader() -> None:
            assert self._proc and self._proc.stdout
            try:
                for line in self._proc.stdout:
                    self._log(line)
            except Exception as e:
                self._log(f"[log] {e}\n")

        self._reader = threading.Thread(target=reader, daemon=True)
        self._reader.start()
        self.after(400, self._poll)

    def _poll(self) -> None:
        if not self._proc:
            return
        code = self._proc.poll()
        if code is None:
            self.after(400, self._poll)
            return
        self._log(f"\n— Fin (code={code}) —\n")
        self._proc = None
        self._set_running(False)
        try:
            self._refresh_stats()
        except Exception:
            pass

    def _stop(self) -> None:
        self._log("STOP…\n")
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            self.after(1500, self._kill)
        else:
            self._set_running(False)

    def _kill(self) -> None:
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        if self._running:
            self._proc = None
            self._set_running(False)

    def _on_close(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        self.destroy()


def main() -> int:
    print("Opening JewelBingo Panel…", flush=True)
    try:
        app = JewelBingoPanel()
        app.mainloop()
        return 0
    except Exception as e:
        _log_crash("main", e)
        try:
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("Error", f"{e}\n\n{ERROR_LOG}")
            r.destroy()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
