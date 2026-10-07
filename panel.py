"""
JewelBingo Panel — high-contrast UI that actually colors on macOS.

macOS system Tk ignores tk.Button bg/fg (everything looks aqua gray).
This panel uses Label-buttons + clam ttk where needed so colors show.
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
from tkinter import messagebox, ttk
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ERROR_LOG = ROOT / "panel_error.log"
CAL_PATH = ROOT / "assets" / "calibration" / "default.json"
PANEL_VERSION = "2026-10-07-v4"

# Stark palette — must be obvious on Mac
WIN_BG = "#1e1e1e"
CARD_BG = "#fafafa"
TEXT = "#111111"
TEXT_LIGHT = "#ffffff"
MUTED = "#555555"
GREEN = "#00c853"
GREEN_DK = "#1b5e20"
RED = "#ff1744"
BLUE = "#2979ff"
ORANGE = "#ff6d00"
PURPLE = "#7b1fa2"
BLACK = "#000000"
LOG_BG = "#0a0a0a"
LOG_FG = "#69f0ae"


def _log_crash(where: str, exc: BaseException) -> None:
    msg = f"{where}: {exc}\n{traceback.format_exc()}"
    try:
        ERROR_LOG.write_text(msg, encoding="utf-8")
    except Exception:
        pass
    print(msg, file=sys.stderr)


class ColorButton(tk.Frame):
    """Colored clickable button that works on macOS (Label-based, not native Button)."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
        bg: str,
        fg: str = TEXT_LIGHT,
        width: int = 14,
        height: int = 2,
        font: tuple = ("Arial", 13, "bold"),
        **kwargs,
    ) -> None:
        super().__init__(parent, bg=bg, highlightbackground=BLACK, highlightthickness=2, **kwargs)
        self._command = command
        self._bg = bg
        self._enabled = True
        self._label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=fg,
            font=font,
            width=width,
            height=height,
            cursor="hand2",
        )
        self._label.pack(padx=2, pady=2)
        for w in (self, self._label):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", lambda e: self._hover(True))
            w.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, on: bool) -> None:
        if not self._enabled:
            return
        # slight darken via border
        self.configure(highlightthickness=4 if on else 2)

    def _click(self, _event=None) -> None:
        if self._enabled and self._command:
            self._command()

    def configure_state(self, state: str) -> None:
        self._enabled = state != tk.DISABLED
        self._label.configure(fg="#888888" if not self._enabled else self._label.cget("fg"))
        self.configure(cursor="arrow" if not self._enabled else "hand2")

    def set_text_color(self, fg: str) -> None:
        if self._enabled:
            self._label.configure(fg=fg)


class JewelBingoPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"JewelBingo  [{PANEL_VERSION}]")
        self.configure(bg=WIN_BG)
        self.minsize(760, 700)
        self.geometry("860x820")

        # Force ttk clam so OptionMenu/Spinbox aren't aqua-gray
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TCombobox", fieldbackground="#ffffff", foreground="#000000")
        style.configure(
            "Big.TSpinbox",
            fieldbackground="#ffffff",
            foreground="#000000",
            background=ORANGE,
            arrowsize=16,
        )

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

        self.left_var.trace_add("write", lambda *_: self._update_hint())
        self._update_hint()
        self.after(80, self._front)
        self._log(f"Panel version {PANEL_VERSION} (si no ves colores fuertes, git pull otra vez)\n")

    def _front(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _section(self, parent: tk.Misc, title: str, color: str) -> tk.Frame:
        wrap = tk.Frame(parent, bg=WIN_BG)
        wrap.pack(fill=tk.X, pady=(0, 12))
        tk.Label(
            wrap,
            text=f"  {title}",
            bg=color,
            fg=TEXT_LIGHT,
            font=("Arial", 13, "bold"),
            anchor="w",
            pady=8,
        ).pack(fill=tk.X)
        body = tk.Frame(
            wrap, bg=CARD_BG, highlightbackground=BLACK, highlightthickness=3,
        )
        body.pack(fill=tk.X)
        inner = tk.Frame(body, bg=CARD_BG, padx=14, pady=12)
        inner.pack(fill=tk.X)
        return inner

    def _build(self) -> None:
        from src.types import JEWEL_NAMES, JEWEL_TYPES

        root = tk.Frame(self, bg=WIN_BG, padx=14, pady=12)
        root.pack(fill=tk.BOTH, expand=True)

        head = tk.Frame(root, bg=WIN_BG)
        head.pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            head, text="JewelBingo", bg=WIN_BG, fg=TEXT_LIGHT,
            font=("Arial", 26, "bold"),
        ).pack(side=tk.LEFT)
        # Giant version strip — if you don't see this, git pull failed
        tk.Label(
            head,
            text=f"  UI {PANEL_VERSION}  ",
            bg=ORANGE,
            fg=TEXT,
            font=("Arial", 12, "bold"),
            padx=8,
            pady=4,
        ).pack(side=tk.LEFT, padx=12)
        self.status_lbl = tk.Label(
            head, text="● LISTO", bg=WIN_BG, fg=GREEN, font=("Arial", 14, "bold"),
        )
        self.status_lbl.pack(side=tk.RIGHT)

        # 1 CONTROL
        a = self._section(root, "1. CONTROL", GREEN_DK)
        row = tk.Frame(a, bg=CARD_BG)
        row.pack(fill=tk.X)
        self.btn_start = ColorButton(
            row, "START", self._start, GREEN, TEXT, width=12, height=2,
        )
        self.btn_start.pack(side=tk.LEFT, padx=(0, 10))
        self.btn_stop = ColorButton(
            row, "STOP", self._stop, RED, TEXT_LIGHT, width=12, height=2,
        )
        self.btn_stop.configure_state(tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 10))
        ColorButton(
            row, "Ver calibracion", self._show_calibration, BLUE, TEXT_LIGHT,
            width=16, height=2,
        ).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(
            row, text="ESC / F8 = stop", bg=CARD_BG, fg=MUTED, font=("Arial", 10),
        ).pack(side=tk.RIGHT)

        # 2 MODO
        m = self._section(root, "2. MODO", BLUE)
        r = tk.Frame(m, bg=CARD_BG)
        r.pack(fill=tk.X)
        tk.Radiobutton(
            r, text="TEMPLATE", variable=self.mode_var, value="template",
            bg=CARD_BG, fg=TEXT, selectcolor="#ffffff", activebackground=CARD_BG,
            font=("Arial", 12, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 16))
        tk.Radiobutton(
            r, text="AUTO-PLACE", variable=self.mode_var, value="auto",
            bg=CARD_BG, fg=TEXT, selectcolor="#ffffff", activebackground=CARD_BG,
            font=("Arial", 12, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 20))
        tk.Label(r, text="Countdown", bg=CARD_BG, fg=TEXT, font=("Arial", 11)).pack(
            side=tk.LEFT
        )
        ttk.Spinbox(
            r, from_=0, to=30, width=4, textvariable=self.countdown_var,
            style="Big.TSpinbox", font=("Arial", 12, "bold"),
        ).pack(side=tk.LEFT, padx=(6, 14))
        tk.Label(r, text="Max", bg=CARD_BG, fg=TEXT, font=("Arial", 11)).pack(side=tk.LEFT)
        ttk.Spinbox(
            r, from_=1, to=50, width=4, textvariable=self.max_games_var,
            style="Big.TSpinbox", font=("Arial", 12, "bold"),
        ).pack(side=tk.LEFT, padx=(6, 14))
        tk.Checkbutton(
            r, text="Dry-run", variable=self.dry_var,
            bg=CARD_BG, fg=TEXT, selectcolor="#ffffff", font=("Arial", 11),
        ).pack(side=tk.LEFT)

        # 3 DONDE ARRANCAR
        s = self._section(root, "3. DONDE ARRANCAR — movimientos que QUEDAN", ORANGE)
        tk.Label(
            s, text="Cuantos movimientos quedan ahora en el juego?",
            bg=CARD_BG, fg=TEXT, font=("Arial", 14, "bold"),
        ).pack(anchor="w")
        tk.Label(
            s, text="14 = partida NUEVA.   Menos de 14 = RESUME (no gasta card).",
            bg=CARD_BG, fg=MUTED, font=("Arial", 11),
        ).pack(anchor="w", pady=(2, 10))

        picker = tk.Frame(s, bg=CARD_BG)
        picker.pack(fill=tk.X)
        ColorButton(
            picker, "−", lambda: self._nudge(-1), ORANGE, TEXT,
            width=4, height=1, font=("Arial", 20, "bold"),
        ).pack(side=tk.LEFT)
        self.left_spin = ttk.Spinbox(
            picker, from_=0, to=14, width=3, textvariable=self.left_var,
            style="Big.TSpinbox", font=("Arial", 28, "bold"),
            justify="center",
        )
        self.left_spin.pack(side=tk.LEFT, padx=14, ipady=6)
        ColorButton(
            picker, "+", lambda: self._nudge(1), ORANGE, TEXT,
            width=4, height=1, font=("Arial", 20, "bold"),
        ).pack(side=tk.LEFT)

        quick = tk.Frame(picker, bg=CARD_BG)
        quick.pack(side=tk.LEFT, padx=16)
        for n, label, bg in (
            (14, "Nueva", GREEN),
            (10, "10", "#ffcc80"),
            (7, "7", "#ffcc80"),
            (5, "5", "#ffcc80"),
            (3, "3", "#ef9a9a"),
            (1, "1", "#ef9a9a"),
        ):
            ColorButton(
                quick, label, lambda v=n: self.left_var.set(v), bg, TEXT,
                width=5, height=1, font=("Arial", 11, "bold"),
            ).pack(side=tk.LEFT, padx=3)

        self.hint_frame = tk.Frame(s, bg="#c8e6c9", highlightbackground=BLACK, highlightthickness=2)
        self.hint_frame.pack(fill=tk.X, pady=(12, 0))
        self.hint_lbl = tk.Label(
            self.hint_frame, text="", bg="#c8e6c9", fg=GREEN_DK,
            font=("Arial", 13, "bold"), anchor="w", justify="left", padx=10, pady=8,
        )
        self.hint_lbl.pack(fill=tk.X)

        self.stats_var = tk.StringVar(value="")
        tk.Label(
            s, textvariable=self.stats_var, bg=CARD_BG, fg=MUTED,
            font=("Arial", 10), anchor="w", justify="left", wraplength=780,
        ).pack(fill=tk.X, pady=(8, 0))

        # 4 PATRON
        p = self._section(root, "4. PATRON TEMPLATE", PURPLE)
        grid = tk.Frame(p, bg=CARD_BG)
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
                        grid, text="FREE", width=5, bg="#9e9e9e", fg=TEXT,
                        relief=tk.SOLID, bd=2, font=("Arial", 11, "bold"),
                    ).grid(row=r, column=c, padx=3, pady=3)
                else:
                    om = tk.OptionMenu(grid, v, *choices)
                    om.config(
                        width=4, bg="#ffffff", fg=TEXT,
                        activebackground="#eeeeee", activeforeground=TEXT,
                        highlightthickness=2, highlightbackground=BLACK,
                        font=("Arial", 11, "bold"), relief=tk.SOLID, bd=1,
                    )
                    om["menu"].config(bg="#ffffff", fg=TEXT)
                    om.grid(row=r, column=c, padx=3, pady=3)
            self._cell_vars.append(row_vars)

        prow = tk.Frame(p, bg=CARD_BG)
        prow.pack(fill=tk.X, pady=(10, 0))
        ColorButton(
            prow, "Guardar", self._save_pattern, "#eeeeee", TEXT,
            width=10, height=1, font=("Arial", 11, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 8))
        ColorButton(
            prow, "Reset ChatGPT", self._reset_pattern, "#eeeeee", TEXT,
            width=14, height=1, font=("Arial", 11, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 8))
        ColorButton(
            prow, "Validar", self._validate_pattern, "#eeeeee", TEXT,
            width=10, height=1, font=("Arial", 11, "bold"),
        ).pack(side=tk.LEFT)
        legend = "   ".join(
            f"{k}={JEWEL_NAMES[k].replace('Jewel of ', '')}" for k in JEWEL_TYPES
        )
        tk.Label(prow, text=legend, bg=CARD_BG, fg=MUTED, font=("Arial", 9)).pack(
            side=tk.RIGHT
        )

        # 5 LOG
        log_wrap = tk.Frame(root, bg=WIN_BG)
        log_wrap.pack(fill=tk.BOTH, expand=True)
        tk.Label(
            log_wrap, text="  5. LOG EN VIVO", bg=BLACK, fg=LOG_FG,
            font=("Arial", 13, "bold"), anchor="w", pady=8,
        ).pack(fill=tk.X)
        log_card = tk.Frame(
            log_wrap, bg=LOG_BG, highlightbackground=LOG_FG, highlightthickness=3,
        )
        log_card.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(
            log_card, height=10, bg=LOG_BG, fg=LOG_FG, insertbackground=LOG_FG,
            font=("Courier", 12), wrap=tk.WORD, relief=tk.FLAT, padx=10, pady=8,
            borderwidth=0,
        )
        sb = tk.Scrollbar(log_card, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # ── logic ───────────────────────────────────────────────────────

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
            bg, fg = "#c8e6c9", GREEN_DK
            text = "→ Partida NUEVA  ·  movimiento 1 / 14"
        elif left <= 3:
            bg, fg = "#ffcdd2", "#b71c1c"
            text = f"→ RESUME  ·  quedan {left}  ·  arranca en {done + 1}/14  ·  hechos ~{done}"
        else:
            bg, fg = "#ffe0b2", "#e65100"
            text = f"→ RESUME  ·  quedan {left}  ·  arranca en {done + 1}/14  ·  hechos ~{done}"
        self.hint_frame.configure(bg=bg)
        self.hint_lbl.configure(text=text, bg=bg, fg=fg)

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
        self.btn_start.configure_state(tk.DISABLED if running else tk.NORMAL)
        self.btn_stop.configure_state(tk.NORMAL if running else tk.DISABLED)
        self.status_lbl.configure(
            text="● CORRIENDO" if running else "● LISTO",
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
            messagebox.showinfo("OK", "Patron valido.")

    def _refresh_stats(self) -> None:
        from src.history import history_summary, load_learned_priors, rebuild_learned_priors

        rebuild_learned_priors()
        learned = load_learned_priors()
        self.stats_var.set(f"{history_summary()}  ·  priors n={learned.get('games', 0)}")

    def _show_calibration(self) -> None:
        if not CAL_PATH.exists():
            messagebox.showerror("Sin calibracion", f"Falta:\n{CAL_PATH}")
            return
        self._log(
            "\n--- Ver calibracion ---\n"
            "Mueve Remote Desktop hasta que coincidan los recuadros. Q/ESC cierra.\n"
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

    def _start(self) -> None:
        if self._running:
            return
        if not CAL_PATH.exists():
            messagebox.showerror("Sin calibracion", f"Falta:\n{CAL_PATH}")
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
            messagebox.showerror("Error", str(e))
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
    print(f"Opening JewelBingo Panel {PANEL_VERSION}…", flush=True)
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
