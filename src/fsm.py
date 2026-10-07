"""Finite-state machine driving Jewel Bingo (Auto or Template placement)."""

from __future__ import annotations

import gc
import time
from collections import Counter
from typing import Callable, Optional

import numpy as np

from .capture import ScreenCapture, crop, shift_calibration, vision_grab_rect
from .control import Controller
from .logger import GameLogger
from .patterns import (
    board_from_template,
    format_template,
    load_active_template,
    placement_plan,
)
from .solver.montecarlo import JewelPriors, choose_cell
from .solver.scoring import score_board
from .types import (
    DRAWS_PER_GAME,
    JEWEL_NAMES,
    TARGET_SCORE,
    BoardState,
    Calibration,
    DecisionRecord,
    GameRecord,
    GameState,
    PlacementMode,
)
from .vision.board import BoardReader
from .vision.boxes import find_blue_chest_center
from .vision.draw import DrawDetector, MarkedCellDetector, patch_delta
from .vision.score import read_remaining_draws, read_total_score
from .vision.templates import JewelClassifier


class BingoBot:
    def __init__(
        self,
        calibration: Calibration,
        placement_mode: PlacementMode = PlacementMode.TEMPLATE,
        dry_run: bool = False,
        use_mc: bool = True,
        n_sims: int = 2000,
        max_games: Optional[int] = None,
        log_dir: str = "logs",
        template_dir: str | None = "assets/templates",
        resume: bool = False,
        resume_left: int | None = None,
        template: list[list[str]] | None = None,
        on_status: Optional[Callable[[str], None]] = None,
        verbose: bool = True,
    ) -> None:
        self.cal = calibration
        self.placement_mode = placement_mode
        self.dry_run = dry_run
        self.use_mc = use_mc
        self.n_sims = n_sims
        self.max_games = max_games if max_games is not None else (1 if resume else None)
        self.resume = resume
        self.resume_left = resume_left
        self.template = template if template is not None else load_active_template()
        self.on_status = on_status
        self.verbose = verbose
        # Clicks use absolute screen coords; vision grabs ONLY the game ROI
        # (cuts Retina full-desktop frames that ballooned RAM to tens of GB).
        grab_r = vision_grab_rect(calibration, pad=80)
        self._grab_ox = grab_r.x
        self._grab_oy = grab_r.y
        self.vcal = shift_calibration(calibration, grab_r.x, grab_r.y)
        self.capture = ScreenCapture(region=grab_r)
        self._say(
            f"Capture ROI {grab_r.w}x{grab_r.h} @ ({grab_r.x},{grab_r.y}) "
            f"(not full desktop — RAM safe)"
        )
        self.controller = Controller(calibration, dry_run=dry_run)
        self.classifier = JewelClassifier(template_dir=template_dir)
        if not self.classifier.has_templates():
            print(
                "WARNING: no hay plantillas B/S/CR/H/L/C.png en assets/templates.\n"
                "  Recalibra O corre: python tools/capture_jewel_templates.py --delay 8"
            )
        self.board_reader = BoardReader(self.vcal, self.classifier)
        self.draw_detector = DrawDetector(self.vcal, self.classifier)
        self.marked_detector = MarkedCellDetector(self.vcal)
        self.logger = GameLogger(log_dir)
        self.priors = JewelPriors.from_logs(log_dir)
        self.state = GameState.IDLE
        self.games_played = 0
        self._active: Optional[GameRecord] = None
        self._draws_done_offset = 0
        self._frame_i = 0
        # Consecutive games that never got a first draw → out of cards
        self._no_draw_streak = 0

    def frame(self) -> np.ndarray:
        return self.capture.grab()

    def _say(self, msg: str) -> None:
        """Always print important status (short)."""
        print(msg, flush=True)

    def _vprint(self, msg: str) -> None:
        """Verbose-only — skipped with --quiet (stops Terminal/panel RAM flood)."""
        if self.verbose:
            print(msg, flush=True)

    def _gc_tick(self) -> None:
        self._frame_i += 1
        if self._frame_i % 40 == 0:
            gc.collect(0)

    def _cleanup_vision(self) -> None:
        """Drop frame buffers so RAM drops when stopping / no-cards."""
        try:
            self.draw_detector.reset()
        except Exception:
            pass
        try:
            self.marked_detector._baseline = None
        except Exception:
            pass
        self._active = None
        gc.collect()

    def stop(self) -> None:
        self.controller.request_stop()

    def run(self) -> None:
        self.logger.log_event(
            "bot_start",
            dry_run=self.dry_run,
            use_mc=self.use_mc,
            placement_mode=self.placement_mode.value,
            resume=self.resume,
        )
        print(f"Placement mode: {self.placement_mode.value.upper()}")
        if self.placement_mode == PlacementMode.TEMPLATE:
            print("Active template:\n" + format_template(self.template))
        if self.resume:
            print(
                "\n=== RESUME: juego YA en curso ===\n"
                "No Start / no colocación / no caja — solo marca sorteos.\n"
            )
            self.state = GameState.CALIBRATE  # reuse as resume entry
        else:
            self.state = GameState.PRESS_START
        try:
            while not self.controller.stopped:
                if self.max_games is not None and self.games_played >= self.max_games:
                    self.logger.log_event("max_games_reached", n=self.games_played)
                    break
                try:
                    cont = self._step()
                except Exception as exc:
                    self.logger.log_event("error", error=str(exc), state=self.state.name)
                    self.state = GameState.ERROR
                    break
                if not cont:
                    break
        finally:
            self._cleanup_vision()
            try:
                self.capture.close()
            except Exception:
                pass
            self.logger.log_event("bot_stop", games=self.games_played)
            gc.collect()

    def _step(self) -> bool:
        s = self.state
        if s == GameState.CALIBRATE:
            return self._resume_playing()
        if s == GameState.PRESS_START:
            return self._press_start()
        if s == GameState.PLACE_JEWELS:
            return self._place_jewels()
        if s == GameState.READ_BOARD:
            return self._read_board_and_pick_box()
        if s == GameState.WAIT_DRAW:
            return self._draw_loop()
        if s == GameState.ACCEPT_REWARD:
            return self._accept_reward()
        if s == GameState.NO_CARDS:
            self.logger.log_event("no_cards", games=self.games_played)
            self._say("SIN CARDS — paro limpio (no reintento Start).")
            self._cleanup_vision()
            return False
        if s == GameState.ERROR:
            self._cleanup_vision()
            return False
        if s == GameState.IDLE:
            self.state = GameState.PRESS_START
            return True
        return True

    def _resume_playing(self) -> bool:
        """Join a game already in PLAYING: lock template board + scan blue marks."""
        self.controller.focus_panel()
        self.controller.park_mouse()
        self.controller.wait(0.4)
        frame = self.frame()

        if self.placement_mode == PlacementMode.TEMPLATE:
            board = board_from_template(self.template)
        else:
            board = self.board_reader.read(frame)

        # Score blue-glow ratio per cell (FREE always marked)
        import cv2

        ratios: list[tuple[float, int, int]] = []
        for r in range(5):
            for c in range(5):
                if (r, c) == (2, 2):
                    board.marked[r][c] = True
                    continue
                board.marked[r][c] = False
                patch = crop(frame, self.marked_detector._cells[r][c])
                ratio = 0.0
                if patch.size > 0:
                    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
                    blue = cv2.inRange(
                        hsv,
                        np.array([95, 70, 100], dtype=np.uint8),
                        np.array([135, 255, 255], dtype=np.uint8),
                    )
                    ratio = cv2.countNonZero(blue) / float(
                        patch.shape[0] * patch.shape[1] or 1
                    )
                ratios.append((ratio, r, c))

        ratios.sort(reverse=True)
        strong = [(rt, r, c) for rt, r, c in ratios if rt >= 0.22]
        soft = [(rt, r, c) for rt, r, c in ratios if rt >= 0.12]

        ocr_left = read_remaining_draws(frame, self.vcal.score_roi)
        by_strong = max(0, DRAWS_PER_GAME - len(strong))

        # User-provided remaining is authoritative (auto blue/OCR often wrong)
        if self.resume_left is not None:
            left = int(self.resume_left)
            source = "user"
        elif ocr_left is not None:
            left = int(ocr_left)
            source = "ocr_counter"
        else:
            left = by_strong
            source = "marked_cells"

        left = int(max(0, min(left, DRAWS_PER_GAME)))
        expected_marked = DRAWS_PER_GAME - left  # non-FREE cells that should be blue
        self._draws_done_offset = expected_marked

        # Mark exactly the top-N bluest cells (avoids over-count that killed resume)
        for _, r, c in ratios:
            board.marked[r][c] = False
        board.marked[2][2] = True
        picked = soft[:expected_marked] if expected_marked else []
        # If not enough soft blues, still take top-N by ratio
        if len(picked) < expected_marked:
            picked = ratios[:expected_marked]
        for rt, r, c in picked:
            board.marked[r][c] = True
        marked_n = len(picked)

        print()
        print("=" * 56)
        print("  RESUME — partida en curso")
        print("=" * 56)
        print(f"  Movimientos hechos (aprox): {self._draws_done_offset}/{DRAWS_PER_GAME}")
        print(f"  Sorteos que quedan:         {left}")
        print(f"  Celdas marcadas (top blue): {marked_n}")
        print(f"  Blue fuertes (≥0.22):       {len(strong)}  → auto-quedarían {by_strong}")
        if ocr_left is not None:
            print(f"  Contador OCR (score ROI):   {ocr_left}")
        print(f"  Origen del conteo:          {source}")
        print("  Celdas marcadas:")
        for rt, r, c in picked:
            print(f"    R{r+1}C{c+1} {board.cells[r][c]:3s}  blue={rt:.2f}")
        print("=" * 56)
        print("Board:")
        for row in board.cells:
            print(" ", row)
        self.logger.log_event(
            "resume_playing",
            marked=marked_n,
            left=left,
            ocr_left=ocr_left,
            source=source,
            strong_blue=len(strong),
        )

        if left <= 0:
            print("No quedan sorteos — voy a Get Reward (sin gastar card).")
            self._active = GameRecord(
                board=board,
                placement_mode=self.placement_mode.value,
            )
            self.games_played = 0
            self.state = GameState.ACCEPT_REWARD
            return True

        self.marked_detector.set_baseline(frame)
        self.draw_detector.set_board(board)
        self.draw_detector.reset()
        self._active = GameRecord(
            board=board,
            placement_mode=self.placement_mode.value,
        )
        self.state = GameState.WAIT_DRAW
        return True

    def _press_start(self) -> bool:
        self.logger.log_event("press_start")
        self.controller.press_start()
        self.controller.wait(self.cal.post_auto_wait_s)
        self.state = GameState.PLACE_JEWELS
        return True

    def _place_jewels(self) -> bool:
        if self.placement_mode == PlacementMode.AUTO:
            self.logger.log_event("press_auto")
            print("Placing jewels: AUTO-PLACE")
            self.controller.press_auto()
            # Auto-place animation needs longer settle on GRD before read
            wait_s = max(2.8, float(self.cal.post_auto_wait_s) + 1.2)
            print(f"  Esperando tablero auto ({wait_s:.1f}s)...")
            self.controller.wait(wait_s)
            self.controller.park_mouse()
            self.controller.wait(0.4)
        else:
            self.logger.log_event("place_template", pattern="active")
            print("Placing jewels: TEMPLATE (active pattern) — slow/GRD-safe")
            # Start UI still settling — especially critical before first jewel (Bless)
            self.controller.wait(1.2)
            self._place_template()
            print("Esperando a que aparezcan los cofres...")
            self.controller.wait(1.8)
        self.state = GameState.READ_BOARD
        return True

    def _place_template(self) -> None:
        """Select each jewel from the right panel, then click its cells (slow + re-select)."""
        for jewel, cells in placement_plan(self.template):
            if self.controller.stopped:
                return
            name = JEWEL_NAMES.get(jewel, jewel)
            print(f"  select {jewel} ({name}) → {len(cells)} cells")
            # Double-select with settle (fixes Bless miss on GRD)
            self.controller.select_jewel(jewel)
            for i, (r, c) in enumerate(cells):
                if self.controller.stopped:
                    return
                # Mid-group re-select so GRD doesn't lose the active jewel
                if i == 2:
                    print(f"    re-select {jewel} mid-group")
                    self.controller.select_jewel(jewel)
                self.controller.click_cell(r, c)
                self.controller.wait(max(0.35, self.cal.place_delay_s))
            # Pause between jewel types so UI registers the group
            self.controller.wait(0.7)

    def _read_board_and_pick_box(self) -> bool:
        frame = self.frame()
        if self.placement_mode == PlacementMode.TEMPLATE:
            board = board_from_template(self.template)
            try:
                seen = self.board_reader.read(frame)
                mismatches = 0
                for r in range(5):
                    for c in range(5):
                        if (r, c) == (2, 2):
                            continue
                        if seen.cells[r][c] and seen.cells[r][c] != board.cells[r][c]:
                            mismatches += 1
                self.logger.log_event("board_verify", mismatches=mismatches)
                if mismatches > 4:
                    self.logger.log_event("board_verify_warn", using="template_anyway")
            except Exception:
                pass
        else:
            board, soft_known = self._read_auto_board_robust()
            if soft_known < 10:
                print(
                    f"  ERROR: lectura AUTO muy incierta (solo ~{soft_known}/24 "
                    "celdas claras).\n"
                    "  SAFETY STOP — usa TEMPLATE o recalibra templates/grid."
                )
                self.logger.log_event("auto_board_uncertain", soft_known=soft_known)
                self.state = GameState.ERROR
                return False

        self.marked_detector.set_baseline(frame)
        self.draw_detector.reset()
        # Don't dump full board into jsonl every game (log file + RAM on long runs)
        self.logger.log_event(
            "board_read",
            placement_mode=self.placement_mode.value,
            labeled=self.board_reader.labeled_count(board)
            if self.placement_mode == PlacementMode.AUTO
            else 24,
        )
        print("Board locked:")
        for row in board.cells:
            print(" ", row)

        # Only click the BLUE chest (vision leftmost blue blob)
        print("Buscando cofre AZUL (no rojo)...")
        self.controller.wait(0.8)
        frame = self.frame()
        blue = find_blue_chest_center(frame, self.vcal)
        if blue is not None:
            abs_xy = (blue[0] + self._grab_ox, blue[1] + self._grab_oy)
            print(f"  Cofre azul @ {abs_xy} (vision {blue})")
            self.controller.click_xy_box(*abs_xy)
        else:
            print("  Vision falló — usando calibración boxes")
            self.controller.click_top_left_box()
        print("Caja azul seleccionada — esperando primer sorteo...")
        self.controller.wait(2.5)
        self.controller.focus_panel()
        self.controller.park_mouse()
        self.controller.wait(0.8)
        self._active = GameRecord(
            board=board,
            placement_mode=self.placement_mode.value,
        )
        self.draw_detector.set_board(board)
        self.draw_detector.reset()
        self.state = GameState.WAIT_DRAW
        return True

    def _read_auto_board_robust(self) -> tuple:
        """Multi-frame score + force 4-of-each assignment (AUTO boards)."""
        print("Leyendo tablero AUTO (multi-frame + 4 de cada)...")
        frames: list = []
        for _ in range(6):
            if self.controller.stopped:
                break
            self.controller.park_mouse()
            frames.append(self.frame())
            self.controller.wait(0.22)
        board, soft_known = self.board_reader.read_auto(frames)
        frames.clear()
        del frames
        gc.collect(0)
        labeled = self.board_reader.labeled_count(board)
        print(f"  soft-known≈{soft_known}/24 → assigned {labeled}/24 (4× cada joya)")
        flat = [
            board.cells[r][c]
            for r in range(5)
            for c in range(5)
            if (r, c) != (2, 2)
        ]
        print(f"  conteo: {dict(Counter(flat))}")
        return board, soft_known

    def _draw_loop(self) -> bool:
        record: GameRecord = self._active  # type: ignore
        start_i = getattr(self, "_draws_done_offset", 0) or 0
        start_i = int(max(0, min(start_i, DRAWS_PER_GAME)))
        left = DRAWS_PER_GAME - start_i
        print(
            f"\n=== PLAYING: quedan {left} sorteos "
            f"(movimiento {start_i + 1} de {DRAWS_PER_GAME}) ==="
        )
        if left <= 0:
            print("Nada que marcar — Get Reward.")
            self.state = GameState.ACCEPT_REWARD
            return True
        print("Detección por parpadeo del TABLERO. Verify estricto.")
        completed = start_i
        last_jewel: Optional[str] = None
        for draw_i in range(start_i, DRAWS_PER_GAME):
            print(
                f"\n--- Sorteo {draw_i + 1}/{DRAWS_PER_GAME} "
                f"(quedan {DRAWS_PER_GAME - draw_i}) ---"
            )
            if self.controller.stopped:
                return False
            # After several games, first-draw wait is shorter so "no cards"
            # fails fast instead of chewing RAM for 28s+ of grabs.
            if draw_i == start_i:
                timeout = 14.0 if self.games_played > 0 else 28.0
            else:
                timeout = 18.0
            self._say("Esperando joya del sorteo...")
            self.controller.park_mouse()
            jewel = self._wait_for_jewel(
                timeout=timeout,
                board=record.board,
                avoid=last_jewel,
            )
            if jewel is None:
                self.logger.log_event("draw_timeout", draw_index=draw_i, completed=completed)
                self._say("  TIMEOUT detectando joya sorteada.")
                self._vprint(
                    f"  debug: {self.draw_detector.debug_snapshot(record.board)}"
                )
                # No draw at all this game → almost always out of cards / wrong screen.
                # Do NOT loop Start forever (that was the post-cards RAM spike).
                if completed <= start_i:
                    self._no_draw_streak += 1
                    self._say(
                        f"  Ningún sorteo tras Start "
                        f"(racha sin draw={self._no_draw_streak})."
                    )
                    if self._no_draw_streak >= 1:
                        self.state = GameState.NO_CARDS
                        return False
                    self.state = GameState.ERROR
                    return False
                if completed < 10:
                    self._say(
                        "  SAFETY STOP: pocos sorteos completados "
                        f"({completed}). NO reinicio automático."
                    )
                    self.state = GameState.ERROR
                    return False
                break

            # Previous mark didn't advance: undo false mark and try another cell
            stuck_retry = self.draw_detector.last_source == "board_stuck_retry"
            if stuck_retry and last_jewel == jewel and record.decisions:
                prev = record.decisions[-1]
                if prev.jewel == jewel:
                    pr, pc = prev.chosen
                    record.board.marked[pr][pc] = False
                    print(
                        f"  undo false mark R{pr+1}C{pc+1}; reintentando {jewel}"
                    )
                    completed = max(0, completed - 1)
                    record.draws.pop() if record.draws else None
                    record.decisions.pop()
                    self.draw_detector.set_board(record.board)

            record.draws.append(jewel)
            # Only sync marks that are clearly solid blue — NOT flashing candidates
            # (draw highlight looks blue and was wiping H/L candidates)
            self._sync_marks_from_vision(record.board, min_ratio=0.35)
            cands = record.board.candidates(jewel)
            print(
                f"  Detectado: {jewel} ({JEWEL_NAMES.get(jewel, jewel)}) "
                f"via {self.draw_detector.last_source} "
                f"— {len(cands)} candidatas"
            )
            if not cands:
                self.logger.log_event("no_candidate", jewel=jewel, draw_index=draw_i)
                print("  Sin candidatas — SAFETY STOP")
                self.state = GameState.ERROR
                return False

            blink_cell = self.draw_detector.most_blinking_cell(record.board, jewel)
            print("  Calculando mejor celda...")
            cell, e_score, p1000, method = choose_cell(
                record.board,
                jewel,
                draw_index=draw_i,
                priors=self.priors,
                use_mc=self.use_mc,
                n_sims=min(self.n_sims, 400),
            )
            # Blink only detects WHICH jewel — never override strategy.
            # (board_blink_cell was picking the loudest flash, not the best line.)
            if cell is None and blink_cell is not None and blink_cell in cands:
                cell = blink_cell
                method = "blink_fallback"
            elif cell is None and blink_cell is not None:
                cell = blink_cell
                method = "blink_fallback"

            if cell is None:
                self.logger.log_event("no_candidate", jewel=jewel, draw_index=draw_i)
                self.state = GameState.ERROR
                return False

            record.decisions.append(
                DecisionRecord(
                    draw_index=draw_i,
                    jewel=jewel,
                    chosen=cell,
                    candidates=cands,
                    expected_score=e_score,
                    p_ge_1000=p1000,
                    method=method,
                )
            )
            print(
                f"  DRAW {draw_i+1}: {jewel} → R{cell[0]+1}C{cell[1]+1} "
                f"[{method}] E≈{e_score:.0f} P1000≈{p1000:.0%}"
            )

            ok = self._click_and_verify_mark(record, jewel, cell)
            if not ok:
                # Prefer other blinking cells of same jewel first
                alternates = [c for c in cands if c != cell]
                alternates = self._order_by_blink(record.board, jewel, alternates)
                recovered = False
                for alt in alternates[:4]:
                    print(f"  reintento con celda alternativa R{alt[0]+1}C{alt[1]+1}...")
                    if self._click_and_verify_mark(record, jewel, alt):
                        cell = alt
                        method = method + "+alt"
                        record.decisions[-1] = DecisionRecord(
                            draw_index=draw_i,
                            jewel=jewel,
                            chosen=cell,
                            candidates=cands,
                            expected_score=e_score,
                            p_ge_1000=p1000,
                            method=method,
                        )
                        recovered = True
                        break
                if not recovered:
                    print("  SAFETY STOP: clic no verificado (el juego no avanzó).")
                    self.logger.log_event("click_unverified", jewel=jewel, cell=cell)
                    self.state = GameState.ERROR
                    return False

            record.board.mark(*cell)
            self.draw_detector.set_board(record.board)
            self.draw_detector.reset()
            last_jewel = jewel
            completed += 1
            # Longer settle so next-draw blink isn't residual animation
            self.controller.wait(0.85)

        frame = self.frame()
        ocr = read_total_score(frame, self.vcal.score_roi)
        computed = score_board(record.board)
        record.final_score = ocr if ocr is not None else computed
        record.target_met = record.final_score >= TARGET_SCORE
        self.logger.log_game(record)
        self.games_played += 1
        self.logger.log_event(
            "game_done",
            score=record.final_score,
            target_met=record.target_met,
            games=self.games_played,
            draws=completed,
            placement_mode=self.placement_mode.value,
        )
        self._say(
            f"Game done: draws={completed} score={record.final_score} "
            f"target={'YES' if record.target_met else 'no'}"
        )
        self._no_draw_streak = 0  # real game completed
        try:
            self.priors = JewelPriors.from_logs(str(self.logger.log_dir))
        except Exception:
            pass
        self.draw_detector.reset()
        gc.collect(0)
        self.state = GameState.ACCEPT_REWARD
        return True

    def _sync_marks_from_vision(
        self, board: BoardState, min_ratio: float = 0.20
    ) -> None:
        """Mark as used any cell that already looks clearly blue on screen."""
        import cv2

        frame = self.frame()
        for r in range(5):
            for c in range(5):
                if (r, c) == (2, 2):
                    board.marked[r][c] = True
                    continue
                if board.marked[r][c]:
                    continue
                patch = crop(frame, self.marked_detector._cells[r][c])
                if patch.size == 0:
                    continue
                hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
                blue = cv2.inRange(
                    hsv,
                    np.array([95, 70, 100], dtype=np.uint8),
                    np.array([135, 255, 255], dtype=np.uint8),
                )
                ratio = cv2.countNonZero(blue) / float(
                    patch.shape[0] * patch.shape[1] or 1
                )
                if ratio >= min_ratio:
                    board.marked[r][c] = True

    def _order_by_blink(
        self,
        board: BoardState,
        jewel: str,
        cells: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        """Sort candidate cells by recent blink activity (highest first)."""
        act = self.draw_detector._activity_map()
        if act is None:
            return cells

        def score(rc: tuple[int, int]) -> float:
            return float(act[rc[0], rc[1]])

        return sorted(cells, key=score, reverse=True)

    def _click_and_verify_mark(
        self,
        record: GameRecord,
        jewel: str,
        cell: tuple[int, int],
    ) -> bool:
        """
        Click cell and verify the GAME advanced.
        Do NOT trust classify() flipping (B↔CR noise) or blue_glow alone.
        Do NOT skip on blue-before-click: draw flash looks blue and blocked all H.
        """
        if record.board.marked[cell[0]][cell[1]]:
            print(f"    skip R{cell[0]+1}C{cell[1]+1}: ya marcada en board state")
            return False

        self.controller.focus_panel()
        self.controller.wait(0.25)

        # Fresh baselines AFTER focus (focus click can change UI slightly)
        frame_before = self.frame()
        before_score = crop(frame_before, self.vcal.score_roi)
        before_draw = crop(frame_before, self.vcal.draw_jewel_roi)
        before_cell = crop(
            frame_before,
            self.marked_detector._cells[cell[0]][cell[1]],
        )
        del frame_before

        self.controller.click_cell_mark(*cell)
        # Let GRD register click before parking cursor off the board
        self.controller.wait(0.55)
        self.controller.park_mouse()
        self.controller.wait(0.75)

        counter_streak = 0
        draw_streak = 0
        cell_streak = 0
        for attempt in range(16):
            if self.controller.stopped:
                return False
            frame = self.frame()
            cd = patch_delta(before_score, crop(frame, self.vcal.score_roi))
            dd = patch_delta(before_draw, crop(frame, self.vcal.draw_jewel_roi))
            cell_d = patch_delta(
                before_cell,
                crop(frame, self.marked_detector._cells[cell[0]][cell[1]]),
            )
            self._gc_tick()
            blue = self.marked_detector.cell_marked_blue(frame, *cell)

            if cd >= 1.0:
                counter_streak += 1
            else:
                counter_streak = 0
            if dd >= 2.0:
                draw_streak += 1
            else:
                draw_streak = 0
            if cell_d >= 2.5 or blue:
                cell_streak += 1
            else:
                cell_streak = 0

            if self.verbose and (attempt == 0 or attempt % 4 == 0):
                self._vprint(
                    f"    verify {attempt+1}: counterΔ={cd:.1f} drawΔ={dd:.1f} "
                    f"cellΔ={cell_d:.1f} blue={blue} "
                    f"cStreak={counter_streak} dStreak={draw_streak} cellStreak={cell_streak}"
                )
            # MUST see counter or draw icon advance — cell glow alone lied (Soul false OK)
            if counter_streak >= 2 or draw_streak >= 2:
                try:
                    self.marked_detector.update_cell_baseline(frame, *cell)
                except Exception:
                    pass
                return True
            # Strong cell change only if score/draw also clearly moved (not residual flash)
            if (
                cell_streak >= 3
                and cell_d >= 10.0
                and blue
                and cd >= 1.5
                and dd >= 2.0
            ):
                try:
                    self.marked_detector.update_cell_baseline(frame, *cell)
                except Exception:
                    pass
                return True
            # Do not accept blue+cell alone — caused false Soul mark then stuck retry
            time.sleep(0.2)

        self._vprint("    reintento de clic...")
        self.controller.click_cell_mark(*cell)
        self.controller.wait(0.55)
        self.controller.park_mouse()
        self.controller.wait(1.0)
        frame = self.frame()
        dd = patch_delta(before_draw, crop(frame, self.vcal.draw_jewel_roi))
        cd = patch_delta(before_score, crop(frame, self.vcal.score_roi))
        cell_d = patch_delta(
            before_cell,
            crop(frame, self.marked_detector._cells[cell[0]][cell[1]]),
        )
        blue = self.marked_detector.cell_marked_blue(frame, *cell)
        self._vprint(
            f"    retry check: counterΔ={cd:.1f} drawΔ={dd:.1f} cellΔ={cell_d:.1f} blue={blue}"
        )
        if (dd >= 2.0 or cd >= 1.2) and (cell_d >= 2.0 or blue):
            return True
        if blue and (cd >= 0.8 or dd >= 1.0 or cell_d >= 4.0):
            return True
        return False

    def _wait_for_jewel(
        self,
        timeout: float | None = None,
        board: Optional[BoardState] = None,
        avoid: Optional[str] = None,
    ) -> Optional[str]:
        """Vote over board_blink. If stuck on `avoid` >4s, return it for re-click."""
        timeout = timeout if timeout is not None else self.cal.draw_timeout_s
        deadline = time.time() + timeout
        votes: list[str] = []
        last_log = 0.0
        stuck_since: Optional[float] = None
        while time.time() < deadline and not self.controller.stopped:
            frame = self.frame()
            # Board-blink only — skip ROI template classify every 100ms (RAM/CPU)
            self.draw_detector.push(frame, classify_roi=False)
            del frame
            self._gc_tick()
            jewel = self.draw_detector.detect_from_board_blink(board)
            now = time.time()
            if self.verbose and now - last_log >= 3.0:
                self._vprint(f"  ... {self.draw_detector.debug_snapshot(board)}")
                last_log = now
            if jewel and avoid and jewel == avoid:
                if stuck_since is None:
                    stuck_since = now
                if now - stuck_since >= 4.0:
                    self._say(
                        f"  same draw still {avoid} after 4s — "
                        "re-click (el mark anterior no avanzó el juego)"
                    )
                    self.draw_detector._last_source = "board_stuck_retry"
                    return avoid
                time.sleep(0.1)
                continue
            stuck_since = None
            if jewel:
                votes.append(jewel)
                votes = votes[-12:]
                if len(votes) >= 5:
                    from collections import Counter

                    counts = Counter(votes[-8:])
                    top, n = counts.most_common(1)[0]
                    second_n = counts.most_common(2)[1][1] if len(counts) > 1 else 0
                    scores = self.draw_detector._last_scores or {}
                    if n >= 3 and n > second_n:
                        self.draw_detector._last_source = "board_vote"
                        self._say(f"  vote → {top}")
                        self._vprint(f"  vote detail ({n}/8) scores={scores}")
                        return top
                    if n >= 3 and n == second_n:
                        contenders = [j for j, c in counts.items() if c == n]
                        top = max(contenders, key=lambda j: scores.get(j, 0.0))
                        self.draw_detector._last_source = "board_vote_tiebreak"
                        self._say(f"  vote-tie → {top}")
                        return top
            time.sleep(0.1)
        if board is not None and self.draw_detector._last_scores:
            ranked = sorted(
                self.draw_detector._last_scores.items(),
                key=lambda kv: kv[1],
                reverse=True,
            )
            best_j, best_v = ranked[0]
            second_v = ranked[1][1] if len(ranked) > 1 else 0.0
            if best_v >= 8.0 and best_v >= second_v:
                self._say(f"  soft-pick → {best_j}")
                return best_j
        return None

    def _accept_reward(self) -> bool:
        self.logger.log_event("accept_reward")
        self._say("Get Reward...")
        self.controller.accept_reward()
        self.controller.wait(2.0)
        # Resume only applied to the first in-progress game; then keep playing
        # until max_games / no cards (do NOT force-stop here).
        self.resume = False
        self.resume_left = None
        self._draws_done_offset = 0
        self._cleanup_vision()
        if self.max_games is not None and self.games_played >= self.max_games:
            self._say(f"Max cards alcanzado ({self.games_played}).")
            return False
        if self._no_draw_streak >= 1:
            self.state = GameState.NO_CARDS
            return False
        self._say("Siguiente card → Start...")
        self.state = GameState.PRESS_START
        return True
