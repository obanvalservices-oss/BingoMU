"""
JewelBingo control panel (Mac + Windows).

The bot runs in a SEPARATE process (not a thread). On macOS, mss/pyautogui
inside a Tk thread crashes Python — subprocess avoids that.
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


class JewelBingoPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("JewelBingo Panel")
        self.configure(bg=BG)
        try:
            self.geometry("880x680")
        except Exception:
            pass

        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._running = False
        self._cell_vars: list[list[tk.StringVar]] = []

        self.mode_var = tk.StringVar(value="template")
        self.countdown_var = tk.IntVar(value=5)
        self.max_games_var = tk.IntVar(value=1)
        self.resume_var = tk.BooleanVar(value=False)
        self.left_var = tk.IntVar(value=14)  # 14 = partida nueva
        self.dry_var = tk.BooleanVar(value=False)
        self.left_var.trace_add("write", lambda *_: self._on_left_changed())

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
        self.geometry("980x760")

        root = tk.Frame(self, bg=BG, padx=12, pady=8)
        root.pack(fill=tk.BOTH, expand=True)

        # —— Header / control ——
        head = tk.Frame(root, bg=BG)
        head.pack(fill=tk.X)
        tk.Label(
            head, text="JewelBingo", font=("Arial", 18, "bold"), bg=BG, fg=FG
        ).pack(side=tk.LEFT)
        self.status_lbl = tk.Label(
            head, text="Listo", font=("Arial", 12, "bold"), bg=BG, fg=ACCENT
        )
        self.status_lbl.pack(side=tk.RIGHT)

        ctrl = tk.LabelFrame(root, text="Control", bg=BG, fg=FG, padx=8, pady=6)
        ctrl.pack(fill=tk.X, pady=4)

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
        tk.Label(r1, text="Max juegos", bg=BG, fg=FG).pack(side=tk.LEFT, padx=(8, 2))
        tk.Spinbox(
            r1, from_=1, to=100, width=4, textvariable=self.max_games_var
        ).pack(side=tk.LEFT)
        tk.Checkbutton(
            r1, text="Dry-run", variable=self.dry_var,
            bg=BG, fg=FG, selectcolor=BG, activebackground=BG,
        ).pack(side=tk.LEFT, padx=10)
        tk.Button(
            r1, text="Ver calibracion", command=self._show_calibration,
            bg="#90caf9", fg=FG,
        ).pack(side=tk.LEFT, padx=6)
        tk.Label(r1, text="ESC/F8 = stop", bg=BG, fg="#666666").pack(side=tk.RIGHT)

        # —— Middle: pattern | resumen ——
        mid = tk.Frame(root, bg=BG)
        mid.pack(fill=tk.X, pady=4)

        pat = tk.LabelFrame(
            mid, text="Patron TEMPLATE", bg=BG, fg=FG, padx=8, pady=6,
        )
        pat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

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
                        grid, text="FREE", width=6, bg="#cccccc", fg=FG, relief=tk.SUNKEN,
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
        tk.Label(prow, text=legend, bg=BG, fg="#555555", font=("Arial", 8)).pack(
            anchor=tk.W, pady=2
        )

        # Resumen lateral — movimientos restantes + stats
        side = tk.LabelFrame(
            mid, text="Resumen / desde donde arrancar", bg=BG, fg=FG, padx=10, pady=8,
        )
        side.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))

        tk.Label(
            side, text="Movimientos que QUEDAN", bg=BG, fg=FG,
            font=("Arial", 11, "bold"),
        ).pack(anchor=tk.W)
        tk.Label(
            side,
            text="14 = partida nueva\n<14 = resume (sin gastar card)",
            bg=BG, fg="#555555", justify=tk.LEFT, font=("Arial", 9),
        ).pack(anchor=tk.W, pady=(0, 4))

        left_row = tk.Frame(side, bg=BG)
        left_row.pack(anchor=tk.W, pady=4)
        tk.Button(
            left_row, text="-", width=3, command=lambda: self._nudge_left(-1), bg=BTN,
        ).pack(side=tk.LEFT)
        self.left_spin = tk.Spinbox(
            left_row, from_=0, to=14, width=4, textvariable=self.left_var,
            font=("Arial", 16, "bold"), justify=tk.CENTER,
        )
        self.left_spin.pack(side=tk.LEFT, padx=6)
        tk.Button(
            left_row, text="+", width=3, command=lambda: self._nudge_left(1), bg=BTN,
        ).pack(side=tk.LEFT)

        quick = tk.Frame(side, bg=BG)
        quick.pack(anchor=tk.W, pady=2)
        for n in (14, 10, 7, 5, 3, 1):
            tk.Button(
                quick, text=str(n), width=3, bg=BTN,
                command=lambda v=n: self.left_var.set(v),
            ).pack(side=tk.LEFT, padx=1)

        self.resume_hint = tk.Label(
            side, text="", bg=BG, fg=ACCENT, font=("Arial", 10, "bold"),
            justify=tk.LEFT, wraplength=260,
        )
        self.resume_hint.pack(anchor=tk.W, pady=6)
        self._on_left_changed()

        tk.Label(
            side, text="Historial de partidas", bg=BG, fg=FG, font=("Arial", 10, "bold"),
        ).pack(anchor=tk.W, pady=(8, 2))
        self.hist_lbl = tk.Label(
            side, text="...", bg=BG, fg=FG, justify=tk.LEFT, anchor="nw",
            wraplength=260, font=("Arial", 9),
        )
        self.hist_lbl.pack(anchor=tk.W, fill=tk.X)
        tk.Button(
            side, text="Actualizar resumen", command=self._refresh_history, bg=BTN,
        ).pack(anchor=tk.W, pady=4)

        # —— Bottom: live log history ——
        logf = tk.LabelFrame(
            root, text="Historial de logs (partida en vivo)", bg=BG, fg=FG,
            padx=4, pady=4,
        )
        logf.pack(fill=tk.BOTH, expand=True, pady=4)
        self.log = tk.Text(
            logf, height=16, bg=LOG_BG, fg=LOG_FG, insertbackground=LOG_FG,
            font=("Courier", 11), wrap=tk.WORD,
        )
        sb = tk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._append_log(
            "Logs en vivo aqui abajo.\n"
            "A la derecha: elige cuantos movimientos QUEDAN (ej. 5) y START.\n"
            "Si pones 14 = partida nueva completa.\n"
        )

    def _nudge_left(self, delta: int) -> None:
        try:
            n = int(self.left_var.get())
        except Exception:
            n = 14
        self.left_var.set(max(0, min(14, n + delta)))

    def _show_calibration(self) -> None:
        """Open live overlay of calibration boxes (subprocess — Mac-safe)."""
        if not CAL_PATH.exists():
            messagebox.showerror(
                "Sin calibracion",
                f"Falta:\n{CAL_PATH}\nCorre 2-Calibrar.command primero.",
            )
            return
        script = ROOT / "tools" / "show_calibration.py"
        self._append_log(
            "\nAbriendo vista de calibracion…\n"
            "Mueve Chrome Remote Desktop hasta que los recuadros coincidan.\n"
            "Q o ESC cierra la vista.\n"
        )
        env = os.environ.copy()
        env["TK_SILENCE_DEPRECATION"] = "1"
        try:
            subprocess.Popen(
                [sys.executable, "-u", str(script), "--cal", str(CAL_PATH)],
                cwd=str(ROOT),
                env=env,
            )
        except Exception as e:
            _log_crash("show_calibration", e)
            messagebox.showerror("Error", str(e))

    def _on_left_changed(self, *_args) -> None:
        try:
            left = int(self.left_var.get())
        except Exception:
            return
        left = max(0, min(14, left))
        done = 14 - left
        if left >= 14:
            self.resume_var.set(False)
            self.resume_hint.configure(
                text="Partida NUEVA\n(movimiento 1 de 14)",
                fg=ACCENT,
            )
        else:
            self.resume_var.set(True)
            self.resume_hint.configure(
                text=(
                    f"RESUME — quedan {left}\n"
                    f"Arranca en movimiento {done + 1} de 14\n"
                    f"(ya hechos ~{done})"
                ),
                fg="#b71c1c" if left <= 3 else "#e65100",
            )

    def _toggle_resume(self) -> None:
        # Kept for compatibility; left spinner drives resume now
        if self.resume_var.get() and int(self.left_var.get()) >= 14:
            self.left_var.set(5)
        elif not self.resume_var.get():
            self.left_var.set(14)

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
        from src.history import (
            history_summary,
            load_history,
            load_learned_priors,
            rebuild_learned_priors,
        )

        rebuild_learned_priors()
        learned = load_learned_priors()
        summary = history_summary()
        n = learned.get("games", 0)
        overall = learned.get("overall") or {}
        top = ", ".join(
            f"{j}:{overall.get(j, 0):.0%}"
            for j, _ in sorted(overall.items(), key=lambda kv: -kv[1])[:4]
        )
        lines = [summary, f"Priors (n={n}): {top}", ""]
        games = load_history()[-5:]
        if games:
            lines.append("Ultimas partidas:")
            for g in reversed(games):
                draws = g.get("draws") or []
                seq = "→".join(draws[:6])
                if len(draws) > 6:
                    seq += "…"
                sc = g.get("final_score", "?")
                mode = g.get("placement_mode", "?")
                hit = "OK1000" if g.get("target_met") else "no"
                lines.append(f"  [{mode}] {sc} {hit} | {seq}")
        else:
            lines.append("Sin partidas guardadas aun.")
        self.hist_lbl.configure(text="\n".join(lines))

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

        tmpl = self._pattern_from_grid()
        if self.mode_var.get() == "template":
            errs = validate_template(tmpl)
            if errs:
                messagebox.showerror("Patron invalido", "\n".join(errs))
                return
            save_active_template(tmpl, name="panel_active")

        resume = int(self.left_var.get()) < 14
        self.resume_var.set(resume)
        left = int(self.left_var.get())
        mode = self.mode_var.get()
        cd = int(self.countdown_var.get())
        max_games = 1 if resume else int(self.max_games_var.get())

        cmd = [
            sys.executable,
            "-u",
            str(ROOT / "main.py"),
            "--mode",
            mode,
            "--countdown",
            str(cd),
            "--max-games",
            str(max_games),
            "--cal",
            str(CAL_PATH),
            "--log-dir",
            str(ROOT / "logs"),
        ]
        if resume:
            cmd.append("--resume")
            cmd.extend(["--left", str(left)])
        if self.dry_var.get():
            cmd.append("--dry-run")

        self._set_running(True)
        if resume:
            self._append_log(
                f"\nRESUME — quedan {left} (movimiento {14 - left + 1}/14)\n"
            )
        else:
            self._append_log("\nPartida NUEVA (14 sorteos)\n")
        self._append_log(f"cmd: {' '.join(cmd[3:])}\n")

        env = os.environ.copy()
        env["TK_SILENCE_DEPRECATION"] = "1"
        env["PYTHONUNBUFFERED"] = "1"

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            _log_crash("popen", e)
            messagebox.showerror("No se pudo iniciar", str(e))
            self._set_running(False)
            return

        def reader() -> None:
            assert self._proc is not None and self._proc.stdout is not None
            try:
                for line in self._proc.stdout:
                    self._append_log(line)
            except Exception as e:
                self._append_log(f"[log reader] {e}\n")

        self._reader = threading.Thread(target=reader, daemon=True)
        self._reader.start()
        self.after(400, self._poll_proc)

    def _poll_proc(self) -> None:
        if not self._proc:
            return
        code = self._proc.poll()
        if code is None:
            self.after(400, self._poll_proc)
            return
        self._append_log(f"\nProceso terminado (code={code})\n")
        self._proc = None
        self._set_running(False)
        try:
            self._refresh_history()
        except Exception:
            pass

    def _stop(self) -> None:
        self._append_log("STOP — cerrando proceso del bot…\n")
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            self.after(1500, self._force_kill)
        else:
            self._set_running(False)

    def _force_kill(self) -> None:
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.kill()
                self._append_log("Proceso kill()\n")
            except Exception:
                pass
        if self._running and (not proc or proc.poll() is not None):
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
        print("Window created.", flush=True)
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
