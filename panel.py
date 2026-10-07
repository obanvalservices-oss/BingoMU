"""
JewelBingo Panel v9 — Mac dark mode: ALL titles WHITE.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Optional

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

import tkinter as tk
from tkinter import messagebox

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ERROR_LOG = ROOT / "panel_error.log"
BUILD_LOG = ROOT / "panel_build.log"
CAL_PATH = ROOT / "assets" / "calibration" / "default.json"
PANEL_VERSION = "2026-10-07-v12"

# Mac dark window → titles must be white or they vanish.
WHITE = "#ffffff"
INK = "#111111"


def _crash(where: str, exc: BaseException) -> None:
    msg = f"{where}: {exc}\n{traceback.format_exc()}"
    try:
        ERROR_LOG.write_text(msg, encoding="utf-8")
    except Exception:
        pass
    print(msg, file=sys.stderr)


def _blog(msg: str) -> None:
    try:
        with BUILD_LOG.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass
    print(msg, flush=True)


class JewelBingoPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"JewelBingo [{PANEL_VERSION}]")
        self.geometry("920x860")
        self.minsize(800, 700)

        self._proc: Optional[subprocess.Popen] = None
        self._running = False
        self._cell_vars: list[list[tk.StringVar]] = []

        self.mode_var = tk.StringVar(value="template")
        self.countdown_var = tk.StringVar(value="5")
        self.max_games_var = tk.StringVar(value="1")
        self.left_var = tk.StringVar(value="14")
        self.dry_var = tk.BooleanVar(value=False)
        self.hint_var = tk.StringVar(value="")
        self.stats_var = tk.StringVar(value="")

        try:
            BUILD_LOG.write_text(f"build {PANEL_VERSION}\n", encoding="utf-8")
            self._build()
            _blog("build ok")
        except Exception as e:
            _crash("build", e)
            messagebox.showerror("Panel build error", f"{e}\n\n{ERROR_LOG}")
            raise

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            self._load_pattern()
        except Exception as e:
            self._append(f"Patron: {e}\n")
        try:
            self._refresh_stats()
        except Exception as e:
            self.stats_var.set(str(e))

        self.left_var.trace_add("write", lambda *_: self._update_hint())
        self._update_hint()
        self.after(100, self._front)
        self._append(
            f"OK {PANEL_VERSION}\n"
            "Usa Quedan N + START. ESC/F8 = stop.\n"
        )

    def _front(self) -> None:
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _btn(self, parent: tk.Misc, text: str, cmd, *, width: int = 12) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=cmd,
            width=width,
            font=("Helvetica", 13, "bold"),
            padx=6,
            pady=5,
        )

    def _hdr(self, parent: tk.Misc, text: str) -> None:
        # WHITE — Mac dark window + black text = invisible.
        tk.Button(
            parent,
            text=text,
            state="disabled",
            disabledforeground=WHITE,
            fg=WHITE,
            font=("Helvetica", 13, "bold"),
            anchor="w",
            padx=8,
            pady=5,
            relief="groove",
            highlightbackground="#444444",
        ).pack(fill="x", pady=(8, 4))

    def _entry(self, parent: tk.Misc, var: tk.StringVar, *, width: int = 4, font=None) -> tk.Entry:
        e = tk.Entry(
            parent,
            textvariable=var,
            width=width,
            font=font or ("Helvetica", 14, "bold"),
            justify="center",
            relief="solid",
            bd=2,
        )
        return e

    def _build(self) -> None:
        from src.types import JEWEL_NAMES, JEWEL_TYPES

        # --- Log FIRST at bottom so it never collapses ---
        _blog("log")
        log_wrap = tk.Frame(self, padx=8, pady=6)
        log_wrap.pack(side="bottom", fill="x")
        self._hdr(log_wrap, f"5. LOG EN VIVO   [{PANEL_VERSION}]")
        log_row = tk.Frame(log_wrap)
        log_row.pack(fill="x")
        self.log = tk.Text(
            log_row,
            height=9,
            font=("Menlo", 11),
            wrap="word",
            padx=6,
            pady=4,
            relief="solid",
            bd=1,
        )
        sb = tk.Scrollbar(log_row, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        # --- Top form ---
        root = tk.Frame(self, padx=10, pady=6)
        root.pack(side="top", fill="both", expand=True)

        head = tk.Frame(root)
        head.pack(fill="x")
        tk.Button(
            head, text="JewelBingo", state="disabled",
            disabledforeground=WHITE, fg=WHITE, font=("Helvetica", 18, "bold"),
            relief="flat", padx=4,
        ).pack(side="left")
        tk.Button(
            head, text=PANEL_VERSION, state="disabled",
            disabledforeground=WHITE, fg=WHITE, font=("Helvetica", 11, "bold"),
            relief="solid", bd=1, padx=8,
        ).pack(side="left", padx=8)
        self.status_btn = tk.Button(
            head, text="LISTO", state="disabled",
            disabledforeground=WHITE, fg=WHITE, font=("Helvetica", 12, "bold"),
            relief="flat",
        )
        self.status_btn.pack(side="right")

        # 1 Control
        _blog("control")
        self._hdr(root, "1. CONTROL")
        row = tk.Frame(root)
        row.pack(fill="x")
        self.btn_start = self._btn(row, "START", self._start, width=10)
        self.btn_start.pack(side="left", padx=(0, 6))
        self.btn_stop = self._btn(row, "STOP", self._stop, width=10)
        self.btn_stop.configure(state="disabled")
        self.btn_stop.pack(side="left", padx=(0, 6))
        self._btn(row, "Calibrar", self._run_calibrate, width=10).pack(
            side="left", padx=(0, 6)
        )
        self._btn(row, "Ver calibracion", self._show_calibration, width=14).pack(
            side="left", padx=(0, 6)
        )
        tk.Button(
            row, text="ESC / F8 = stop", state="disabled",
            disabledforeground=WHITE, fg=WHITE, relief="flat",
        ).pack(side="right")

        # 2 Mode
        _blog("mode")
        self._hdr(root, "2. MODO")
        r = tk.Frame(root)
        r.pack(fill="x")
        tk.Radiobutton(
            r, text="TEMPLATE", variable=self.mode_var, value="template",
            font=("Helvetica", 12, "bold"), fg=WHITE,
        ).pack(side="left", padx=(0, 12))
        tk.Radiobutton(
            r, text="AUTO-PLACE", variable=self.mode_var, value="auto",
            font=("Helvetica", 12, "bold"), fg=WHITE,
        ).pack(side="left", padx=(0, 16))
        tk.Button(
            r, text="Countdown", state="disabled",
            disabledforeground=WHITE, fg=WHITE, relief="flat",
        ).pack(side="left")
        self._entry(r, self.countdown_var, width=3).pack(side="left", padx=4)
        tk.Button(
            r, text="Max", state="disabled",
            disabledforeground=WHITE, fg=WHITE, relief="flat",
        ).pack(side="left", padx=(10, 0))
        self._entry(r, self.max_games_var, width=3).pack(side="left", padx=4)
        tk.Checkbutton(r, text="Dry-run", variable=self.dry_var, fg=WHITE).pack(
            side="left", padx=12
        )

        # 3 Remaining
        _blog("left")
        self._hdr(root, "3. DONDE ARRANCAR — cuantos movimientos QUEDAN")
        tk.Button(
            root,
            text="14 = partida NUEVA.  Menos de 14 = RESUME (no gasta card).",
            state="disabled", disabledforeground=WHITE, fg=WHITE, relief="flat",
            anchor="w",
        ).pack(fill="x")

        picker = tk.Frame(root)
        picker.pack(fill="x", pady=4)
        self._btn(picker, "-", lambda: self._nudge(-1), width=3).pack(side="left")
        self.left_entry = self._entry(
            picker, self.left_var, width=3, font=("Helvetica", 32, "bold"),
        )
        self.left_entry.pack(side="left", padx=10, ipady=8)
        self._btn(picker, "+", lambda: self._nudge(1), width=3).pack(side="left")

        quick = tk.Frame(picker)
        quick.pack(side="left", padx=12)
        for n, label in ((14, "Nueva"), (10, "10"), (7, "7"), (5, "5"), (3, "3"), (1, "1")):
            self._btn(quick, label, lambda v=n: self.left_var.set(str(v)), width=5).pack(
                side="left", padx=2
            )

        self.hint_btn = tk.Button(
            root, textvariable=self.hint_var, state="disabled",
            disabledforeground=WHITE, fg=WHITE, font=("Helvetica", 12, "bold"),
            relief="solid", bd=1, anchor="w", padx=8, pady=6,
        )
        self.hint_btn.pack(fill="x", pady=(6, 0))
        tk.Button(
            root, textvariable=self.stats_var, state="disabled",
            disabledforeground=WHITE, fg=WHITE, relief="flat", anchor="w",
            wraplength=860, justify="left",
        ).pack(fill="x")

        # 4 Pattern
        _blog("pattern")
        self._hdr(root, "4. PATRON TEMPLATE")
        grid = tk.Frame(root)
        grid.pack()
        choices = list(JEWEL_TYPES) + ["FREE"]
        for rr in range(5):
            row_vars: list[tk.StringVar] = []
            for cc in range(5):
                v = tk.StringVar(value="B")
                row_vars.append(v)
                if rr == 2 and cc == 2:
                    v.set("FREE")
                    tk.Button(
                        grid, text="FREE", width=5, state="disabled",
                        disabledforeground=WHITE, fg=WHITE, font=("Menlo", 11, "bold"),
                        relief="solid", bd=1,
                    ).grid(row=rr, column=cc, padx=2, pady=2)
                else:
                    om = tk.OptionMenu(grid, v, *choices)
                    om.configure(width=4, font=("Menlo", 11, "bold"))
                    om.grid(row=rr, column=cc, padx=2, pady=2)
            self._cell_vars.append(row_vars)

        prow = tk.Frame(root)
        prow.pack(fill="x", pady=(6, 0))
        self._btn(prow, "Guardar", self._save_pattern, width=10).pack(side="left", padx=(0, 6))
        self._btn(prow, "Reset ChatGPT", self._reset_pattern, width=14).pack(
            side="left", padx=(0, 6)
        )
        self._btn(prow, "Validar", self._validate_pattern, width=10).pack(side="left")
        legend = "  ".join(
            f"{k}={JEWEL_NAMES[k].replace('Jewel of ', '')}" for k in JEWEL_TYPES
        )
        tk.Button(
            prow, text=legend, state="disabled",
            disabledforeground=WHITE, fg=WHITE,
            relief="flat", font=("Helvetica", 8),
        ).pack(side="right")

    def _left_int(self) -> int:
        try:
            return max(0, min(14, int(str(self.left_var.get()).strip())))
        except Exception:
            return 14

    def _nudge(self, d: int) -> None:
        self.left_var.set(str(max(0, min(14, self._left_int() + d))))

    def _update_hint(self, *_a) -> None:
        left = self._left_int()
        done = 14 - left
        if left >= 14:
            text = "Partida NUEVA — movimiento 1/14"
        elif left <= 3:
            text = f"RESUME — quedan {left} — arranca en {done + 1}/14"
        else:
            text = f"RESUME — quedan {left} — arranca en {done + 1}/14"
        self.hint_var.set(text)
        try:
            self.hint_btn.configure(disabledforeground=WHITE, fg=WHITE)
        except Exception:
            pass

    def _append(self, text: str) -> None:
        def _do() -> None:
            try:
                self.log.insert("end", text)
                self.log.see("end")
            except Exception:
                pass

        try:
            self.after(0, _do)
        except Exception:
            pass

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")
        self.status_btn.configure(
            text="CORRIENDO" if running else "LISTO",
            disabledforeground=WHITE,
            fg=WHITE,
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
            messagebox.showerror("Invalido", "\n".join(errs))
            return
        save_active_template(tmpl, name="panel_custom")
        self._append("Patron guardado\n")
        messagebox.showinfo("OK", "Patron guardado")

    def _reset_pattern(self) -> None:
        from src.patterns import default_template, save_active_template

        tmpl = default_template()
        for r in range(5):
            for c in range(5):
                self._cell_vars[r][c].set(tmpl[r][c])
        save_active_template(tmpl, name="chatgpt_default")
        self._append("Reset ChatGPT\n")

    def _validate_pattern(self) -> None:
        from src.patterns import validate_template

        errs = validate_template(self._pattern())
        if errs:
            messagebox.showerror("Invalido", "\n".join(errs))
        else:
            messagebox.showinfo("OK", "Patron valido")

    def _refresh_stats(self) -> None:
        from src.history import history_summary, load_learned_priors, rebuild_learned_priors

        rebuild_learned_priors()
        n = load_learned_priors().get("games", 0)
        self.stats_var.set(f"{history_summary()} | priors n={n}")

    def _run_calibrate(self) -> None:
        """Launch guided wizard → saves assets/calibration/default.json."""
        wizard = ROOT / "tools" / "calibrate_wizard.py"
        if not wizard.exists():
            messagebox.showerror("Falta wizard", str(wizard))
            return
        ok = messagebox.askokcancel(
            "Calibrar",
            "Vas a recalibrar.\n\n"
            "1) Pon Chrome Remote Desktop con Jewel Bingo visible\n"
            "2) Acepta — hay 8 segundos de cuenta atras y se toma screenshot\n"
            "3) Click en cada punto que pida (+ zoom, ENTER al terminar)\n\n"
            "Se guarda en assets/calibration/default.json",
        )
        if not ok:
            return
        self._append(
            "CALIBRAR: cuenta atras 8s — deja RD al frente | "
            "+ zoom | ENTER guarda | q cancela\n"
        )
        env = os.environ.copy()
        env["TK_SILENCE_DEPRECATION"] = "1"
        subprocess.Popen(
            [
                sys.executable, "-u", str(wizard),
                "--out", str(CAL_PATH),
                "--delay", "8",
            ],
            cwd=str(ROOT), env=env,
        )

    def _show_calibration(self) -> None:
        if not CAL_PATH.exists():
            messagebox.showerror(
                "Sin calibracion",
                f"No hay {CAL_PATH}\n\nPulsa CALIBRAR primero.",
            )
            return
        self._append(
            "Overlay TRANSPARENTE — ves Chrome debajo | SPACE=ocultar para arrastrar "
            "RD | Q=cerrar\n"
        )
        env = os.environ.copy()
        env["TK_SILENCE_DEPRECATION"] = "1"
        subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "tools" / "show_calibration.py"),
             "--cal", str(CAL_PATH)],
            cwd=str(ROOT), env=env,
        )

    def _start(self) -> None:
        if self._running:
            return
        if not CAL_PATH.exists():
            messagebox.showerror("Sin calibracion", str(CAL_PATH))
            return

        from src.patterns import save_active_template, validate_template

        tmpl = self._pattern()
        if self.mode_var.get() == "template":
            errs = validate_template(tmpl)
            if errs:
                messagebox.showerror("Patron invalido", "\n".join(errs))
                return
            save_active_template(tmpl, name="panel_active")

        left = self._left_int()
        try:
            countdown = max(0, int(str(self.countdown_var.get()).strip()))
        except Exception:
            countdown = 5
        try:
            max_games = max(1, int(str(self.max_games_var.get()).strip()))
        except Exception:
            max_games = 1

        resume = left < 14
        cmd = [
            sys.executable, "-u", str(ROOT / "main.py"),
            "--mode", self.mode_var.get(),
            "--countdown", str(countdown),
            "--max-games", str(1 if resume else max_games),
            "--cal", str(CAL_PATH),
            "--log-dir", str(ROOT / "logs"),
        ]
        if resume:
            cmd += ["--resume", "--left", str(left)]
        if self.dry_var.get():
            cmd.append("--dry-run")

        self._set_running(True)
        self._append(f"\nSTART left={left} resume={resume}\n")

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
            _crash("popen", e)
            messagebox.showerror("Error", str(e))
            self._set_running(False)
            return

        def reader() -> None:
            assert self._proc and self._proc.stdout
            try:
                for line in self._proc.stdout:
                    self._append(line)
            except Exception as e:
                self._append(f"[log] {e}\n")

        threading.Thread(target=reader, daemon=True).start()
        self.after(400, self._poll)

    def _poll(self) -> None:
        if not self._proc:
            return
        code = self._proc.poll()
        if code is None:
            self.after(400, self._poll)
            return
        self._append(f"\nFin code={code}\n")
        self._proc = None
        self._set_running(False)
        try:
            self._refresh_stats()
        except Exception:
            pass

    def _stop(self) -> None:
        self._append("STOP\n")
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self.after(1500, self._kill)
        else:
            self._set_running(False)

    def _kill(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass
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
    print(f"Opening JewelBingo Panel {PANEL_VERSION}…", flush=True)
    try:
        app = JewelBingoPanel()
        app.mainloop()
        return 0
    except Exception as e:
        _crash("main", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
