"""Finite-state machine driving Jewel Bingo (Auto or Template placement)."""

from __future__ import annotations

import time
from typing import Optional

import numpy as np

from .capture import ScreenCapture
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
from .vision.draw import DrawDetector, MarkedCellDetector
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
            print("Placing jewels: TEMPLATE (ChatGPT pattern)")
            self._place_template()
            self.controller.wait(1.0)
        self.state = GameState.READ_BOARD
        return True

    def _place_template(self) -> None:
        """Select each jewel from the right panel, then click its cells."""
        for jewel, cells in placement_plan(TEMPLATE_CHATGPT):
            if self.controller.stopped:
                return
            name = JEWEL_NAMES.get(jewel, jewel)
            print(f"  select {jewel} ({name}) → {len(cells)} cells")
            self.controller.click_jewel_btn(jewel)
            self.controller.wait(0.35)
            for r, c in cells:
                if self.controller.stopped:
                    return
                self.controller.click_cell(r, c)
                self.controller.wait(self.cal.place_delay_s)

    def _read_board_and_pick_box(self) -> bool:
        frame = self.frame()
        if self.placement_mode == PlacementMode.TEMPLATE:
            # Prefer known template; optionally verify with vision
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
                if mismatches <= 4:
                    # vision roughly agrees — keep template
                    pass
                else:
                    self.logger.log_event("board_verify_warn", using="vision_fallback")
                    # still use template for solver (placement was intentional)
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

        self.controller.click_top_left_box()
        print("Caja seleccionada — esperando animación del primer sorteo...")
        self.controller.wait(2.0)
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
            f"Fase de juego: {DRAWS_PER_GAME} sorteos — "
            "elige la celda con mayor chance de llegar a 1000+"
        )
        for draw_i in range(DRAWS_PER_GAME):
            if self.controller.stopped:
                return False
            # First draw can take longer (chest open animation)
            timeout = max(self.cal.draw_timeout_s, 18.0 if draw_i == 0 else 12.0)
            print(f"\nEsperando sorteo {draw_i+1}/{DRAWS_PER_GAME}...")
            jewel = self._wait_for_jewel(timeout=timeout, board=record.board)
            if jewel is None:
                self.logger.log_event("draw_timeout", draw_index=draw_i)
                print(
                    "  TIMEOUT: no detecté joya parpadeando. "
                    "Revisa calibración del grid / draw ROI."
                )
                print(f"  debug: {self.draw_detector.debug_snapshot(record.board)}")
                break
            record.draws.append(jewel)
            cands = record.board.candidates(jewel)
            print(
                f"  Detectado: {jewel} ({JEWEL_NAMES.get(jewel, jewel)}) "
                f"— {len(cands)} celdas candidatas"
            )
            if not cands:
                self.logger.log_event("no_candidate", jewel=jewel, draw_index=draw_i)
                print("  Sin candidatas libres — salto este sorteo")
                self.draw_detector.reset()
                continue

            print("  Calculando mejor celda (score / P>=1000)...")
            cell, e_score, p1000, method = choose_cell(
                record.board,
                jewel,
                draw_index=draw_i,
                priors=self.priors,
                use_mc=self.use_mc,
                n_sims=self.n_sims,
            )
            if cell is None:
                self.logger.log_event("no_candidate", jewel=jewel, draw_index=draw_i)
                continue
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
            self.controller.click_cell(*cell)
            record.board.mark(*cell)
            self.draw_detector.set_board(record.board)
            self.controller.wait(0.55)
            try:
                self.marked_detector.update_cell_baseline(self.frame(), *cell)
            except Exception:
                pass
            self.draw_detector.reset()
            # brief settle so next blink is distinct
            self.controller.wait(0.35)

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
            placement_mode=self.placement_mode.value,
        )
        print(
            f"Game done: score={record.final_score} "
            f"target={'YES' if record.target_met else 'no'}"
        )
        self.priors = JewelPriors.from_logs(str(self.logger.log_dir))
        self.state = GameState.ACCEPT_REWARD
        return True

    def _wait_for_jewel(
        self,
        timeout: float | None = None,
        board: Optional[BoardState] = None,
    ) -> Optional[str]:
        timeout = timeout if timeout is not None else self.cal.draw_timeout_s
        deadline = time.time() + timeout
        last: Optional[str] = None
        stable = 0
        last_log = 0.0
        while time.time() < deadline and not self.controller.stopped:
            frame = self.frame()
            jewel = self.draw_detector.detect(frame, board=board)
            now = time.time()
            if now - last_log >= 1.5:
                print(f"  ... {self.draw_detector.debug_snapshot(board)}")
                last_log = now
            if jewel and jewel == last:
                stable += 1
                # need a few stable frames to avoid flicker false positives
                if stable >= 3:
                    return jewel
            else:
                stable = 1 if jewel else 0
                last = jewel
            time.sleep(0.08)
        return last if stable >= 2 else None

    def _accept_reward(self) -> bool:
        self.logger.log_event("accept_reward")
        self.controller.accept_reward()
        self.controller.wait(1.0)
        self.state = GameState.PRESS_START
        return True
