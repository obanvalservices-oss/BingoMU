"""
JewelBingo Panel v6 — Mac-stable UI (no fragile Canvas scroll tricks).

Fix: v5 crashed with TclError invalid command name "130" on macOS Tk.
Uses simple pack layout + Canvas only for colored action buttons.
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
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ERROR_LOG = ROOT / "panel_error.log"
BUILD_LOG = ROOT / "panel_build.log"
CAL_PATH = ROOT / "assets" / "calibration" / "default.json"
PANEL_VERSION = "2026-10-07-v6"

WIN = "#1a1a1a"
CARD = "#f0f0f0"
INK = "#111111"
WHITE = "#ffffff"
GREEN = "#00c853"
RED = "#d50000"
BLUE = "#0091ea"
ORANGE = "#ff6d00"
PURPLE = "#aa00ff"
MUTED = "#444444"
LOG_BG = "#000000"
LOG_FG = "#00e676"


def _crash(where: str, exc: BaseException) -> None:
    msg = f"{where}: {exc}\n{traceback.format_exc()}"
    try:
        ERROR_LOG.write_text(msg, encoding="utf-8")
    except Exception:
        pass
    print(msg, file=sys.stderr)


def _blog(msg: str) -> None:
    line = msg
    try:
        with BUILD_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


class ActionButton(tk.Frame):
    """Colored button that works on macOS (Label, not native aqua Button)."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
        bg: str,
        fg: str = WHITE,
        padx: int = 18,
        pady: int = 12,
        font: tuple = ("Helvetica", 14, "bold"),
    ) -> None:
        super().__init__(parent, bg="#000000", padx=2, pady=2)
        self._command = command
        self._enabled = True
        self._bg = bg
        self._fg = fg
        self._lbl = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=fg,
            font=font,
            padx=padx,
            pady=pady,
            cursor="hand2",
        )
        self._lbl.pack()
        self._lbl.bind("<ButtonRelease-1>", self._click)
        self.bind("<ButtonRelease-1>", self._click)

    def _click(self, _event=None) -> None:
        if self._enabled:
            self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if enabled:
            self._lbl.configure(bg=self._bg, fg=self._fg, cursor="hand2")
        else:
            self._lbl.configure(bg="#666666", fg="#cccccc", cursor="arrow")


class JewelBingoPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"JewelBingo [{PANEL_VERSION}]")
        self.configure(bg=WIN)
        self.geometry("880x780")
        self.minsize(760, 600)

        self._proc: Optional[subprocess.Popen] = None
        self._running = False
        self._cell_vars: list[list[tk.StringVar]] = []

        self.mode_var = tk.StringVar(value="template")
        self.countdown_var = tk.IntVar(value=5)
        self.max_games_var = tk.IntVar(value=1)
        self.left_var = tk.IntVar(value=14)
        self.dry_var = tk.BooleanVar(value=False)

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
            "1 START/STOP/calibracion  2 modo  3 quedan  4 patron  5 log\n"
        )

    def _front(self) -> None:
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _section(self, parent: tk.Misc, title: str, color: str) -> tk.Frame:
        wrap = tk.Frame(parent, bg=WIN)
        wrap.pack(fill="x", pady=(0, 8))
        tk.Label(
            wrap,
            text=f"  {title}",
            bg=color,
            fg=WHITE if color != ORANGE else INK,
            font=("Helvetica", 12, "bold"),
            anchor="w",
            pady=6,
        ).pack(fill="x")
        box = tk.Frame(wrap, bg="#000000", padx=2, pady=2)
        box.pack(fill="x")
        inner = tk.Frame(box, bg=CARD, padx=12, pady=10)
        inner.pack(fill="x")
        return inner

    def _build(self) -> None:
        from src.types import JEWEL_NAMES, JEWEL_TYPES

        root = tk.Frame(self, bg=WIN, padx=10, pady=8)
        root.pack(fill="both", expand=True)

        # Header
        head = tk.Frame(root, bg=WIN)
        head.pack(fill="x", pady=(0, 8))
        tk.Label(
            head, text="JewelBingo", bg=WIN, fg=WHITE, font=("Helvetica", 20, "bold"),
        ).pack(side="left")
        tk.Label(
            head, text=f"  {PANEL_VERSION}  ", bg=ORANGE, fg=INK,
            font=("Helvetica", 11, "bold"),
        ).pack(side="left", padx=8)
        self.status_lbl = tk.Label(
            head, text="LISTO", bg=WIN, fg=GREEN, font=("Helvetica", 12, "bold"),
        )
        self.status_lbl.pack(side="right")

        # 1 Control
        _blog("control")
        c1 = self._section(root, "1. CONTROL", "#1b5e20")
        row = tk.Frame(c1, bg=CARD)
        row.pack(fill="x")
        self.btn_start = ActionButton(row, "START", self._start, GREEN, INK)
        self.btn_start.pack(side="left", padx=(0, 8))
        self.btn_stop = ActionButton(row, "STOP", self._stop, RED, WHITE)
        self.btn_stop.set_enabled(False)
        self.btn_stop.pack(side="left", padx=(0, 8))
        ActionButton(
            row, "Ver calibracion", self._show_calibration, BLUE, WHITE,
            font=("Helvetica", 12, "bold"),
        ).pack(side="left", padx=(0, 8))
        tk.Label(row, text="ESC/F8 = stop", bg=CARD, fg=MUTED).pack(side="right")

        # 2 Mode
        _blog("mode")
        c2 = self._section(root, "2. MODO", "#0d47a1")
        r = tk.Frame(c2, bg=CARD)
        r.pack(fill="x")
        tk.Radiobutton(
            r, text="TEMPLATE", variable=self.mode_var, value="template",
            bg=CARD, fg=INK, selectcolor=WHITE, font=("Helvetica", 11, "bold"),
        ).pack(side="left", padx=(0, 12))
        tk.Radiobutton(
            r, text="AUTO-PLACE", variable=self.mode_var, value="auto",
            bg=CARD, fg=INK, selectcolor=WHITE, font=("Helvetica", 11, "bold"),
        ).pack(side="left", padx=(0, 16))
        tk.Label(r, text="Countdown", bg=CARD, fg=INK).pack(side="left")
        tk.Spinbox(
            r, from_=0, to=30, width=3, textvariable=self.countdown_var,
            font=("Helvetica", 12, "bold"), bg=WHITE, fg=INK,
        ).pack(side="left", padx=4)
        tk.Label(r, text="Max", bg=CARD, fg=INK).pack(side="left", padx=(10, 0))
        tk.Spinbox(
            r, from_=1, to=50, width=3, textvariable=self.max_games_var,
            font=("Helvetica", 12, "bold"), bg=WHITE, fg=INK,
        ).pack(side="left", padx=4)
        tk.Checkbutton(
            r, text="Dry-run", variable=self.dry_var,
            bg=CARD, fg=INK, selectcolor=WHITE,
        ).pack(side="left", padx=12)

        # 3 Remaining draws
        _blog("left")
        c3 = self._section(root, "3. DONDE ARRANCAR — movimientos que QUEDAN", ORANGE)
        tk.Label(
            c3, text="Cuantos movimientos quedan ahora?",
            bg=CARD, fg=INK, font=("Helvetica", 13, "bold"),
        ).pack(anchor="w")
        tk.Label(
            c3, text="14 = partida NUEVA.  Menos de 14 = RESUME (no gasta card).",
            bg=CARD, fg=MUTED,
        ).pack(anchor="w", pady=(0, 8))

        picker = tk.Frame(c3, bg=CARD)
        picker.pack(fill="x")
        ActionButton(
            picker, "-", lambda: self._nudge(-1), ORANGE, INK,
            padx=14, pady=8, font=("Helvetica", 16, "bold"),
        ).pack(side="left")
        tk.Spinbox(
            picker, from_=0, to=14, width=3, textvariable=self.left_var,
            font=("Helvetica", 24, "bold"), justify="center",
            bg=WHITE, fg=INK, relief="solid", bd=2,
        ).pack(side="left", padx=10, ipady=6)
        ActionButton(
            picker, "+", lambda: self._nudge(1), ORANGE, INK,
            padx=14, pady=8, font=("Helvetica", 16, "bold"),
        ).pack(side="left")

        quick = tk.Frame(picker, bg=CARD)
        quick.pack(side="left", padx=12)
        for n, label, bg in (
            (14, "Nueva", GREEN),
            (10, "10", "#ffcc80"),
            (7, "7", "#ffcc80"),
            (5, "5", "#ffcc80"),
            (3, "3", "#ef9a9a"),
            (1, "1", "#ef9a9a"),
        ):
            ActionButton(
                quick, label, lambda v=n: self.left_var.set(v), bg, INK,
                padx=8, pady=6, font=("Helvetica", 10, "bold"),
            ).pack(side="left", padx=2)

        self.hint_frame = tk.Frame(c3, bg="#c8e6c9", highlightbackground="#000", highlightthickness=1)
        self.hint_frame.pack(fill="x", pady=(10, 0))
        self.hint_lbl = tk.Label(
            self.hint_frame, text="", bg="#c8e6c9", fg="#1b5e20",
            font=("Helvetica", 12, "bold"), anchor="w", padx=8, pady=6,
        )
        self.hint_lbl.pack(fill="x")
        self.stats_var = tk.StringVar(value="")
        tk.Label(
            c3, textvariable=self.stats_var, bg=CARD, fg=MUTED, anchor="w",
            justify="left", wraplength=800,
        ).pack(fill="x", pady=(6, 0))

        # 4 Pattern
        _blog("pattern")
        c4 = self._section(root, "4. PATRON TEMPLATE", PURPLE)
        grid = tk.Frame(c4, bg=CARD)
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
                        grid, text="FREE", width=5, bg="#9e9e9e", fg=INK,
                        relief="solid", bd=1, font=("Menlo", 11, "bold"),
                    ).grid(row=r, column=c, padx=2, pady=2)
                else:
                    om = tk.OptionMenu(grid, v, *choices)
                    om.configure(
                        width=4, bg=WHITE, fg=INK, font=("Menlo", 11, "bold"),
                        highlightthickness=1, activebackground="#eee",
                    )
                    om["menu"].configure(bg=WHITE, fg=INK, font=("Menlo", 11))
                    om.grid(row=r, column=c, padx=2, pady=2)
            self._cell_vars.append(row_vars)

        prow = tk.Frame(c4, bg=CARD)
        prow.pack(fill="x", pady=(8, 0))
        ActionButton(
            prow, "Guardar", self._save_pattern, "#ddd", INK,
            padx=10, pady=6, font=("Helvetica", 10, "bold"),
        ).pack(side="left", padx=(0, 6))
        ActionButton(
            prow, "Reset ChatGPT", self._reset_pattern, "#ddd", INK,
            padx=10, pady=6, font=("Helvetica", 10, "bold"),
        ).pack(side="left", padx=(0, 6))
        ActionButton(
            prow, "Validar", self._validate_pattern, "#ddd", INK,
            padx=10, pady=6, font=("Helvetica", 10, "bold"),
        ).pack(side="left")
        legend = "  ".join(
            f"{k}={JEWEL_NAMES[k].replace('Jewel of ', '')}" for k in JEWEL_TYPES
        )
        tk.Label(prow, text=legend, bg=CARD, fg=MUTED, font=("Helvetica", 8)).pack(
            side="right"
        )

        # 5 Log
        _blog("log")
        tk.Label(
            root, text="  5. LOG EN VIVO", bg="#000000", fg=LOG_FG,
            font=("Helvetica", 12, "bold"), anchor="w", pady=6,
        ).pack(fill="x")
        log_box = tk.Frame(root, bg=LOG_FG, padx=2, pady=2)
        log_box.pack(fill="both", expand=True)
        log_inner = tk.Frame(log_box, bg=LOG_BG)
        log_inner.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_inner, height=10, bg=LOG_BG, fg=LOG_FG, insertbackground=LOG_FG,
            font=("Menlo", 11), wrap="word", padx=8, pady=6, borderwidth=0,
        )
        sb = tk.Scrollbar(log_inner, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

    def _nudge(self, d: int) -> None:
        try:
            n = int(self.left_var.get())
        except Exception:
            n = 14
        self.left_var.set(max(0, min(14, n + d)))

    def _update_hint(self, *_a) -> None:
        try:
            left = int(self.left_var.get())
        except Exception:
            return
        left = max(0, min(14, left))
        done = 14 - left
        if left >= 14:
            bg, fg, text = "#c8e6c9", "#1b5e20", "Partida NUEVA — movimiento 1/14"
        elif left <= 3:
            bg, fg = "#ffcdd2", "#b71c1c"
            text = f"RESUME — quedan {left} — arranca en {done + 1}/14"
        else:
            bg, fg = "#ffe0b2", "#e65100"
            text = f"RESUME — quedan {left} — arranca en {done + 1}/14"
        self.hint_frame.configure(bg=bg)
        self.hint_lbl.configure(text=text, bg=bg, fg=fg)

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
        self.btn_start.set_enabled(not running)
        self.btn_stop.set_enabled(running)
        self.status_lbl.configure(
            text="CORRIENDO" if running else "LISTO",
            fg=RED if running else GREEN,
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

    def _show_calibration(self) -> None:
        if not CAL_PATH.exists():
            messagebox.showerror("Sin calibracion", str(CAL_PATH))
            return
        self._append("Abriendo calibracion (Q/ESC cierra)\n")
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

        left = max(0, min(14, int(self.left_var.get())))
        resume = left < 14
        cmd = [
            sys.executable, "-u", str(ROOT / "main.py"),
            "--mode", self.mode_var.get(),
            "--countdown", str(int(self.countdown_var.get())),
            "--max-games", str(1 if resume else int(self.max_games_var.get())),
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
