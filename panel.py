"""
JewelBingo Panel v5 — Mac-proof UI.

macOS Tk often hides Frame/Label backgrounds and ttk widgets.
This build draws primary buttons on Canvas and keeps a scrollable form
so START / Quedan / Log are always visible.
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
PANEL_VERSION = "2026-10-07-v5"

# High-contrast
WIN = "#121212"
CARD = "#f5f5f5"
INK = "#111111"
WHITE = "#ffffff"
GREEN = "#00e676"
RED = "#ff1744"
BLUE = "#40c4ff"
ORANGE = "#ffab00"
PURPLE = "#e040fb"
MUTED = "#666666"
LOG_BG = "#000000"
LOG_FG = "#69f0ae"


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


class CanvasBtn(tk.Canvas):
    """Always-visible colored button (drawn, not native aqua)."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
        bg: str,
        fg: str = INK,
        w: int = 140,
        h: int = 48,
        font: tuple = ("Arial", 14, "bold"),
    ) -> None:
        super().__init__(
            parent, width=w, height=h, bg=bg, highlightthickness=2,
            highlightbackground="#000000", cursor="hand2",
        )
        self._command = command
        self._enabled = True
        self._bg = bg
        self._fg = fg
        self._text = text
        self._font = font
        self._w = w
        self._h = h
        self._redraw()
        self.bind("<Button-1>", self._on_click)

    def _redraw(self) -> None:
        self.delete("all")
        self.configure(bg=self._bg if self._enabled else "#555555")
        color = self._fg if self._enabled else "#aaaaaa"
        self.create_text(
            self._w // 2, self._h // 2, text=self._text, fill=color, font=self._font,
        )

    def _on_click(self, _e=None) -> None:
        if self._enabled and self._command:
            self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()


class ScrollBody(tk.Frame):
    """Vertical scroll area for the whole form."""

    def __init__(self, parent: tk.Misc, **kw) -> None:
        super().__init__(parent, **kw)
        self.canvas = tk.Canvas(self, bg=WIN, highlightthickness=0)
        self.sb = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=WIN)
        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.sb.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", self._stretch)
        # mouse wheel (Mac + Windows)
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.canvas.bind_all("<Button-4>", self._wheel)
        self.canvas.bind_all("<Button-5>", self._wheel)

    def _stretch(self, event) -> None:
        self.canvas.itemconfigure(self._win, width=event.width)

    def _wheel(self, event) -> None:
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            self.canvas.yview_scroll(-1, "units")
        else:
            self.canvas.yview_scroll(1, "units")


class JewelBingoPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"JewelBingo  [{PANEL_VERSION}]")
        self.configure(bg=WIN)
        self.geometry("900x820")
        self.minsize(780, 640)

        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._running = False
        self._cell_vars: list[list[tk.StringVar]] = []

        self.mode_var = tk.StringVar(value="template")
        self.countdown_var = tk.IntVar(value=5)
        self.max_games_var = tk.IntVar(value=1)
        self.left_var = tk.IntVar(value=14)
        self.dry_var = tk.BooleanVar(value=False)

        try:
            BUILD_LOG.write_text(f"build start {PANEL_VERSION}\n", encoding="utf-8")
            self._build()
            _blog("build ok")
        except Exception as e:
            _crash("build", e)
            messagebox.showerror(
                "Panel build error",
                f"{e}\n\nSee {ERROR_LOG} and {BUILD_LOG}",
            )
            raise

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
        self.after(100, self._front)
        self._log(
            f"OK — {PANEL_VERSION}\n"
            "Si ves este log negro, el panel nuevo cargo bien.\n"
            "START verde / STOP rojo / calibracion azul arriba.\n"
        )

    def _front(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _banner(self, parent: tk.Misc, text: str, bg: str) -> None:
        tk.Label(
            parent, text=f"  {text}", bg=bg, fg=WHITE if bg != ORANGE else INK,
            font=("Arial", 13, "bold"), anchor="w", pady=8,
        ).pack(fill="x")

    def _card(self, parent: tk.Misc) -> tk.Frame:
        outer = tk.Frame(parent, bg="#000000", padx=2, pady=2)
        outer.pack(fill="x", pady=(0, 12))
        inner = tk.Frame(outer, bg=CARD, padx=14, pady=12)
        inner.pack(fill="x")
        return inner

    def _build(self) -> None:
        from src.types import JEWEL_NAMES, JEWEL_TYPES

        # Fixed top bar (always visible)
        top = tk.Frame(self, bg=WIN, padx=12, pady=8)
        top.pack(fill="x")
        tk.Label(
            top, text="JewelBingo", bg=WIN, fg=WHITE, font=("Arial", 22, "bold"),
        ).pack(side="left")
        tk.Label(
            top, text=f"  {PANEL_VERSION}  ", bg=ORANGE, fg=INK,
            font=("Arial", 12, "bold"),
        ).pack(side="left", padx=10)
        self.status_lbl = tk.Label(
            top, text="● LISTO", bg=WIN, fg=GREEN, font=("Arial", 13, "bold"),
        )
        self.status_lbl.pack(side="right")

        # Scrollable body
        body = ScrollBody(self, bg=WIN)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        form = body.inner

        # --- 1 CONTROL ---
        _blog("section control")
        self._banner(form, "1. CONTROL", "#1b5e20")
        c1 = self._card(form)
        row = tk.Frame(c1, bg=CARD)
        row.pack(fill="x")
        self.btn_start = CanvasBtn(row, "START", self._start, GREEN, INK, 130, 52)
        self.btn_start.pack(side="left", padx=(0, 10))
        self.btn_stop = CanvasBtn(row, "STOP", self._stop, RED, WHITE, 130, 52)
        self.btn_stop.set_enabled(False)
        self.btn_stop.pack(side="left", padx=(0, 10))
        CanvasBtn(
            row, "Ver calibracion", self._show_calibration, BLUE, INK, 180, 52,
            font=("Arial", 12, "bold"),
        ).pack(side="left", padx=(0, 10))
        tk.Label(row, text="ESC / F8 = stop", bg=CARD, fg=MUTED, font=("Arial", 10)).pack(
            side="right"
        )

        # --- 2 MODE ---
        _blog("section mode")
        self._banner(form, "2. MODO", "#0d47a1")
        c2 = self._card(form)
        r = tk.Frame(c2, bg=CARD)
        r.pack(fill="x")
        tk.Radiobutton(
            r, text="TEMPLATE", variable=self.mode_var, value="template",
            bg=CARD, fg=INK, selectcolor=WHITE, font=("Arial", 12, "bold"),
        ).pack(side="left", padx=(0, 16))
        tk.Radiobutton(
            r, text="AUTO-PLACE", variable=self.mode_var, value="auto",
            bg=CARD, fg=INK, selectcolor=WHITE, font=("Arial", 12, "bold"),
        ).pack(side="left", padx=(0, 20))
        tk.Label(r, text="Countdown", bg=CARD, fg=INK).pack(side="left")
        tk.Spinbox(
            r, from_=0, to=30, width=4, textvariable=self.countdown_var,
            font=("Arial", 12, "bold"), bg=WHITE, fg=INK,
        ).pack(side="left", padx=(4, 14))
        tk.Label(r, text="Max juegos", bg=CARD, fg=INK).pack(side="left")
        tk.Spinbox(
            r, from_=1, to=50, width=4, textvariable=self.max_games_var,
            font=("Arial", 12, "bold"), bg=WHITE, fg=INK,
        ).pack(side="left", padx=(4, 14))
        tk.Checkbutton(
            r, text="Dry-run", variable=self.dry_var,
            bg=CARD, fg=INK, selectcolor=WHITE, font=("Arial", 11),
        ).pack(side="left")

        # --- 3 WHERE TO START ---
        _blog("section left")
        self._banner(form, "3. DONDE ARRANCAR — cuantos movimientos QUEDAN", ORANGE)
        c3 = self._card(form)
        tk.Label(
            c3, text="Cuantos movimientos quedan en el juego ahora?",
            bg=CARD, fg=INK, font=("Arial", 14, "bold"),
        ).pack(anchor="w")
        tk.Label(
            c3, text="14 = partida NUEVA.   Menos de 14 = RESUME (no gasta card).",
            bg=CARD, fg=MUTED, font=("Arial", 11),
        ).pack(anchor="w", pady=(2, 10))

        picker = tk.Frame(c3, bg=CARD)
        picker.pack(fill="x")
        CanvasBtn(picker, "−", lambda: self._nudge(-1), ORANGE, INK, 56, 48, ("Arial", 22, "bold")).pack(
            side="left"
        )
        self.left_spin = tk.Spinbox(
            picker, from_=0, to=14, width=3, textvariable=self.left_var,
            font=("Arial", 28, "bold"), justify="center", bg=WHITE, fg=INK,
            highlightthickness=2, highlightbackground=ORANGE, relief="solid", bd=2,
        )
        self.left_spin.pack(side="left", padx=12, ipady=4)
        CanvasBtn(picker, "+", lambda: self._nudge(1), ORANGE, INK, 56, 48, ("Arial", 22, "bold")).pack(
            side="left"
        )

        quick = tk.Frame(picker, bg=CARD)
        quick.pack(side="left", padx=16)
        for n, label, col in (
            (14, "Nueva", GREEN),
            (10, "10", "#ffcc80"),
            (7, "7", "#ffcc80"),
            (5, "5", "#ffcc80"),
            (3, "3", "#ef9a9a"),
            (1, "1", "#ef9a9a"),
        ):
            CanvasBtn(
                quick, label, lambda v=n: self.left_var.set(v), col, INK, 58, 36,
                ("Arial", 11, "bold"),
            ).pack(side="left", padx=3)

        self.hint_frame = tk.Frame(c3, bg="#c8e6c9", highlightbackground="#000", highlightthickness=2)
        self.hint_frame.pack(fill="x", pady=(12, 0))
        self.hint_lbl = tk.Label(
            self.hint_frame, text="", bg="#c8e6c9", fg="#1b5e20",
            font=("Arial", 13, "bold"), anchor="w", padx=10, pady=8,
        )
        self.hint_lbl.pack(fill="x")

        self.stats_var = tk.StringVar(value="")
        tk.Label(
            c3, textvariable=self.stats_var, bg=CARD, fg=MUTED,
            font=("Arial", 10), anchor="w", justify="left", wraplength=820,
        ).pack(fill="x", pady=(8, 0))

        # --- 4 PATTERN ---
        _blog("section pattern")
        self._banner(form, "4. PATRON TEMPLATE", PURPLE)
        c4 = self._card(form)
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
                        grid, text="FREE", width=6, bg="#9e9e9e", fg=INK,
                        relief="solid", bd=2, font=("Menlo", 12, "bold"),
                    ).grid(row=r, column=c, padx=3, pady=3)
                else:
                    om = tk.OptionMenu(grid, v, *choices)
                    om.config(
                        width=5, bg=WHITE, fg=INK, font=("Menlo", 12, "bold"),
                        highlightthickness=1, highlightbackground="#000",
                        activebackground="#eee", activeforeground=INK,
                    )
                    om["menu"].config(bg=WHITE, fg=INK, font=("Menlo", 12))
                    om.grid(row=r, column=c, padx=3, pady=3)
            self._cell_vars.append(row_vars)

        prow = tk.Frame(c4, bg=CARD)
        prow.pack(fill="x", pady=(10, 0))
        CanvasBtn(prow, "Guardar", self._save_pattern, "#e0e0e0", INK, 110, 36, ("Arial", 11, "bold")).pack(
            side="left", padx=(0, 8)
        )
        CanvasBtn(prow, "Reset ChatGPT", self._reset_pattern, "#e0e0e0", INK, 140, 36, ("Arial", 11, "bold")).pack(
            side="left", padx=(0, 8)
        )
        CanvasBtn(prow, "Validar", self._validate_pattern, "#e0e0e0", INK, 100, 36, ("Arial", 11, "bold")).pack(
            side="left"
        )
        legend = "  ".join(f"{k}={JEWEL_NAMES[k].replace('Jewel of ', '')}" for k in JEWEL_TYPES)
        tk.Label(prow, text=legend, bg=CARD, fg=MUTED, font=("Arial", 9)).pack(side="right")

        # --- 5 LOG ---
        _blog("section log")
        self._banner(form, "5. LOG EN VIVO", "#000000")
        log_outer = tk.Frame(form, bg=LOG_FG, padx=2, pady=2)
        log_outer.pack(fill="both", expand=True, pady=(0, 20))
        log_inner = tk.Frame(log_outer, bg=LOG_BG)
        log_inner.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_inner, height=14, bg=LOG_BG, fg=LOG_FG, insertbackground=LOG_FG,
            font=("Menlo", 12), wrap="word", padx=10, pady=8, borderwidth=0,
        )
        sb = tk.Scrollbar(log_inner, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

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
            bg, fg, text = "#c8e6c9", "#1b5e20", "→ Partida NUEVA  ·  movimiento 1 / 14"
        elif left <= 3:
            bg, fg = "#ffcdd2", "#b71c1c"
            text = f"→ RESUME  ·  quedan {left}  ·  arranca en {done + 1}/14"
        else:
            bg, fg = "#ffe0b2", "#e65100"
            text = f"→ RESUME  ·  quedan {left}  ·  arranca en {done + 1}/14"
        self.hint_frame.configure(bg=bg)
        self.hint_lbl.configure(text=text, bg=bg, fg=fg)

    def _log(self, text: str) -> None:
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
        self._log("\n--- Ver calibracion (mueve RD hasta coincidir; Q/ESC cierra) ---\n")
        env = os.environ.copy()
        env["TK_SILENCE_DEPRECATION"] = "1"
        try:
            subprocess.Popen(
                [sys.executable, "-u", str(ROOT / "tools" / "show_calibration.py"),
                 "--cal", str(CAL_PATH)],
                cwd=str(ROOT), env=env,
            )
        except Exception as e:
            _crash("show_calibration", e)
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
        self._log(
            f"\n▶ RESUME quedan {left}\n" if resume else "\n▶ Partida NUEVA\n"
        )

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
                    self._log(line)
            except Exception as e:
                self._log(f"[log] {e}\n")

        threading.Thread(target=reader, daemon=True).start()
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
        _crash("main", e)
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
