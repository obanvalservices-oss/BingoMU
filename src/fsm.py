"""Finite-state machine driving Jewel Bingo (Auto or Template placement)."""

from __future__ import annotations

import time
from typing import Optional

import numpy as np

from .capture import ScreenCapture, crop
from .control import Controller
from .logger import GameLogger
from .patterns import chatgpt_board, format_template, placement_plan
from .solver.montecarlo import JewelPriors, choose_cell
from .solver.scoring import score_board
from .types import (
    DRAWS_PER_GAME,
    JEWEL_NAMES,
    TARGET_SCORE,
    TEMPLATE_CHATGPT,
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
from .vision.score import read_total_score
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
    ) -> None:
        self.cal = calibration
        self.placement_mode = placement_mode
        self.dry_run = dry_run
        self.use_mc = use_mc
        self.n_sims = n_sims
        self.max_games = max_games
        self.capture = ScreenCapture()
        self.controller = Controller(calibration, dry_run=dry_run)
        self.classifier = JewelClassifier(template_dir=template_dir)
        if not self.classifier.has_templates():
            print(
                "WARNING: no hay plantillas B/S/CR/H/L/C.png en assets/templates.\n"
                "  Recalibra O corre: python tools/capture_jewel_templates.py --delay 8"
            )
        self.board_reader = BoardReader(calibration, self.classifier)
        self.draw_detector = DrawDetector(calibration, self.classifier)
        self.marked_detector = MarkedCellDetector(calibration)
        self.logger = GameLogger(log_dir)
        self.priors = JewelPriors.from_logs(log_dir)
        self.state = GameState.IDLE
        self.games_played = 0
        self._active: Optional[GameRecord] = None

    def frame(self) -> np.ndarray:
        return self.capture.grab()

    def stop(self) -> None:
        self.controller.request_stop()

    def run(self) -> None:
        self.logger.log_event(
            "bot_start",
            dry_run=self.dry_run,
            use_mc=self.use_mc,
            placement_mode=self.placement_mode.value,
        )
        print(f"Placement mode: {self.placement_mode.value.upper()}")
        if self.placement_mode == PlacementMode.TEMPLATE:
            print("ChatGPT template:\n" + format_template())
        self.state = GameState.PRESS_START
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
        self.capture.close()
        self.logger.log_event("bot_stop", games=self.games_played)

    def _step(self) -> bool:
        s = self.state
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
            self.logger.log_event("no_cards")
            return False
        if s == GameState.ERROR:
            return False
        if s == GameState.IDLE:
            self.state = GameState.PRESS_START
            return True
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
            self.controller.wait(self.cal.post_auto_wait_s)
        else:
            self.logger.log_event("place_template", pattern="chatgpt")
            print("Placing jewels: TEMPLATE (ChatGPT pattern) — slow/GRD-safe")
            # Start UI still settling — especially critical before first jewel (Bless)
            self.controller.wait(1.2)
            self._place_template()
            print("Esperando a que aparezcan los cofres...")
            self.controller.wait(1.8)
        self.state = GameState.READ_BOARD
        return True

    def _place_template(self) -> None:
        """Select each jewel from the right panel, then click its cells (slow + re-select)."""
        for jewel, cells in placement_plan(TEMPLATE_CHATGPT):
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
            board = chatgpt_board()
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
            board = self.board_reader.read(frame)

        self.marked_detector.set_baseline(frame)
        self.draw_detector.reset()
        self.logger.log_event(
            "board_read",
            board=board.to_dict(),
            placement_mode=self.placement_mode.value,
        )
        print("Board locked:")
        for row in board.cells:
            print(" ", row)

        # Only click the BLUE chest (vision leftmost blue blob)
        print("Buscando cofre AZUL (no rojo)...")
        self.controller.wait(0.8)
        frame = self.frame()
        blue = find_blue_chest_center(frame, self.cal)
        if blue is not None:
            print(f"  Cofre azul @ {blue}")
            self.controller.click_xy_box(*blue)
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

    def _draw_loop(self) -> bool:
        record: GameRecord = self._active  # type: ignore
        print(
            f"\n=== FASE PLAYING: {DRAWS_PER_GAME} sorteos ===\n"
            "Detección por parpadeo del TABLERO (ROI solo si anima).\n"
            "Verify estricto: NO acepta flip falso B↔CR."
        )
        completed = 0
        last_jewel: Optional[str] = None
        for draw_i in range(DRAWS_PER_GAME):
            if self.controller.stopped:
                return False
            timeout = 28.0 if draw_i == 0 else 18.0
            print(f"\nEsperando sorteo {draw_i+1}/{DRAWS_PER_GAME}...")
            self.controller.park_mouse()
            jewel = self._wait_for_jewel(
                timeout=timeout,
                board=record.board,
                avoid=last_jewel,
            )
            if jewel is None:
                self.logger.log_event("draw_timeout", draw_index=draw_i, completed=completed)
                print(
                    "  TIMEOUT detectando joya sorteada.\n"
                    f"  debug: {self.draw_detector.debug_snapshot(record.board)}\n"
                    "  Tip: recalibra el punto 'CURRENT DRAWN JEWEL' (icono del sorteo)."
                )
                if completed < 10:
                    print(
                        "  SAFETY STOP: pocos sorteos completados "
                        f"({completed}). NO reinicio automático."
                    )
                    self.state = GameState.ERROR
                    return False
                break

            record.draws.append(jewel)
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
            # Prefer blinking cell only when board-blink was the detection source
            if (
                blink_cell is not None
                and blink_cell in cands
                and "board" in (self.draw_detector.last_source or "")
            ):
                cell = blink_cell
                method = "board_blink_cell"
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
                print("  SAFETY STOP: clic no verificado (el juego no avanzó).")
                self.logger.log_event("click_unverified", jewel=jewel, cell=cell)
                self.state = GameState.ERROR
                return False

            record.board.mark(*cell)
            self.draw_detector.set_board(record.board)
            self.draw_detector.reset()
            last_jewel = jewel
            completed += 1
            self.controller.wait(0.55)

        frame = self.frame()
        ocr = read_total_score(frame, self.cal.score_roi)
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
        print(
            f"Game done: draws={completed} score={record.final_score} "
            f"target={'YES' if record.target_met else 'no'}"
        )
        self.priors = JewelPriors.from_logs(str(self.logger.log_dir))
        self.state = GameState.ACCEPT_REWARD
        return True

    def _click_and_verify_mark(
        self,
        record: GameRecord,
        jewel: str,
        cell: tuple[int, int],
    ) -> bool:
        """
        Click cell and verify the GAME advanced.
        Do NOT trust classify() flipping (B↔CR noise) or blue_glow alone.
        """
        frame_before = self.frame()
        before_score = crop(frame_before, self.cal.score_roi).copy()
        before_draw = crop(frame_before, self.cal.draw_jewel_roi).copy()
        before_cell = crop(
            frame_before,
            self.marked_detector._cells[cell[0]][cell[1]],
        ).copy()

        self.controller.focus_panel()
        self.controller.click_cell(*cell)
        self.controller.park_mouse()
        self.controller.wait(0.85)

        counter_streak = 0
        draw_streak = 0
        cell_streak = 0
        for attempt in range(14):
            if self.controller.stopped:
                return False
            frame = self.frame()
            cd = patch_delta(before_score, crop(frame, self.cal.score_roi))
            dd = patch_delta(before_draw, crop(frame, self.cal.draw_jewel_roi))
            cell_d = patch_delta(
                before_cell,
                crop(frame, self.marked_detector._cells[cell[0]][cell[1]]),
            )
            blue = self.marked_detector.cell_marked_blue(frame, *cell)

            if cd >= 1.2:
                counter_streak += 1
            else:
                counter_streak = 0
            if dd >= 2.5:
                draw_streak += 1
            else:
                draw_streak = 0
            if cell_d >= 3.0 or blue:
                cell_streak += 1
            else:
                cell_streak = 0

            print(
                f"    verify {attempt+1}: counterΔ={cd:.1f} drawΔ={dd:.1f} "
                f"cellΔ={cell_d:.1f} blue={blue} "
                f"cStreak={counter_streak} dStreak={draw_streak} cellStreak={cell_streak}"
            )
            # Require real pixel change on the cell — blue alone was false-positive
            if counter_streak >= 2 or draw_streak >= 2:
                try:
                    self.marked_detector.update_cell_baseline(frame, *cell)
                except Exception:
                    pass
                return True
            if cell_streak >= 3 and cell_d >= 2.5 and (blue or cell_d >= 5.0):
                try:
                    self.marked_detector.update_cell_baseline(frame, *cell)
                except Exception:
                    pass
                return True
            time.sleep(0.2)

        print("    reintento de clic...")
        self.controller.click_cell(*cell)
        self.controller.park_mouse()
        self.controller.wait(1.0)
        frame = self.frame()
        dd = patch_delta(before_draw, crop(frame, self.cal.draw_jewel_roi))
        cd = patch_delta(before_score, crop(frame, self.cal.score_roi))
        cell_d = patch_delta(
            before_cell,
            crop(frame, self.marked_detector._cells[cell[0]][cell[1]]),
        )
        blue = self.marked_detector.cell_marked_blue(frame, *cell)
        print(f"    retry check: counterΔ={cd:.1f} drawΔ={dd:.1f} cellΔ={cell_d:.1f} blue={blue}")
        return dd >= 2.5 or cd >= 1.5 or (cell_d >= 3.0 and blue)

    def _wait_for_jewel(
        self,
        timeout: float | None = None,
        board: Optional[BoardState] = None,
        avoid: Optional[str] = None,
    ) -> Optional[str]:
        """Vote over recent board_blink readings — C vs H often alternate frame-to-frame."""
        timeout = timeout if timeout is not None else self.cal.draw_timeout_s
        deadline = time.time() + timeout
        votes: list[str] = []
        last_log = 0.0
        while time.time() < deadline and not self.controller.stopped:
            frame = self.frame()
            # Always push metrics
            self.draw_detector.push(frame)
            jewel = self.draw_detector.detect_from_board_blink(board)
            now = time.time()
            if now - last_log >= 1.5:
                print(f"  ... {self.draw_detector.debug_snapshot(board)}")
                last_log = now
            if jewel and avoid and jewel == avoid:
                time.sleep(0.1)
                continue
            if jewel:
                votes.append(jewel)
                votes = votes[-12:]
                if len(votes) >= 5:
                    from collections import Counter

                    counts = Counter(votes[-8:])
                    top, n = counts.most_common(1)[0]
                    second_n = counts.most_common(2)[1][1] if len(counts) > 1 else 0
                    scores = self.draw_detector._last_scores or {}
                    # Tie-break C vs H using live board scores
                    if n >= 3 and n > second_n:
                        self.draw_detector._last_source = "board_vote"
                        print(f"  vote → {top} ({n}/8) scores={scores}")
                        return top
                    if n >= 3 and n == second_n:
                        contenders = [j for j, c in counts.items() if c == n]
                        top = max(contenders, key=lambda j: scores.get(j, 0.0))
                        self.draw_detector._last_source = "board_vote_tiebreak"
                        print(f"  vote-tie → {top} scores={scores}")
                        return top
            time.sleep(0.1)
        # Last chance: take current best score even with soft margin
        if board is not None and self.draw_detector._last_scores:
            ranked = sorted(
                self.draw_detector._last_scores.items(),
                key=lambda kv: kv[1],
                reverse=True,
            )
            best_j, best_v = ranked[0]
            second_v = ranked[1][1] if len(ranked) > 1 else 0.0
            if best_j != avoid and best_v >= 8.0 and best_v >= second_v:
                print(f"  soft-pick → {best_j} ({best_v:.1f} vs {second_v:.1f})")
                return best_j
        return None

    def _accept_reward(self) -> bool:
        self.logger.log_event("accept_reward")
        print("Get Reward...")
        self.controller.accept_reward()
        self.controller.wait(2.0)
        self.state = GameState.PRESS_START
        return True
