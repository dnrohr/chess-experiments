from dataclasses import replace
import os
from pathlib import Path
import queue
import sys
import time

import chess
import chess.engine
import pytest

from counterfactual_chess.analysis import AnalysisRequest, AnalysisService
from counterfactual_chess.comparisons import (
    CATEGORIES, BranchResult, ComparisonEvent, ComparisonLimits, ComparisonRequest,
    exchange_prefix, feature_differences, generate_candidates, score_difference, snapshot,
)
from counterfactual_chess.settings import Settings
from test_analysis import FAKE, wait_event


QUICK = ComparisonLimits(.1, .1)


def comparison_event(events, kind, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = events.get(timeout=max(.01, deadline - time.monotonic()))
        if isinstance(event, ComparisonEvent) and event.kind == kind:
            return event
    raise AssertionError(f"No comparison {kind} event")


def test_candidate_priority_diversity_and_deduplication():
    board = chess.Board()
    original = board.fen()
    discovery = ("g1h3", "b1c3", "g1f3", "b1c3")
    candidates = generate_candidates(board, chess.E2, discovery)
    assert [c.uci for c in candidates] == ["g1h3", "g1f3", "b1c3", "e2e3"]
    assert CATEGORIES[2] in candidates[2].reasons
    assert candidates[0].reference
    assert len({c.uci for c in candidates}) == len(candidates) == 4
    assert candidates == generate_candidates(board, chess.E2, discovery)
    assert all(chess.Move.from_uci(c.uci) in board.legal_moves for c in candidates)
    assert board.fen() == original
    with pytest.raises(ValueError):
        generate_candidates(board, chess.E2, discovery, 5)
    with pytest.raises(ValueError):
        generate_candidates(board, chess.E2, ("e2e5",))


def test_capture_and_pawn_contact_categories_for_both_piece_colors():
    board = chess.Board("4k3/8/3p4/4n3/3P4/2N5/8/4K3 w - - 0 1")
    candidates = generate_candidates(board, chess.E5, ("c3b1",))
    assert candidates[1].uci == "d4e5" and CATEGORIES[0] in candidates[1].reasons
    white = generate_candidates(board, chess.D4, ("c3b1",))
    assert white[1].uci == "d4e5"
    pawn_board = chess.Board("4k3/8/3p4/8/4P3/8/8/4K3 w - - 0 1")
    candidates = generate_candidates(pawn_board, chess.A1, ("e1f1",))
    assert len(candidates) == 2
    assert candidates[1].uci == "e4e5" and CATEGORIES[4] in candidates[1].reasons


def test_control_gained_lost_and_friendly_color_definition():
    board = chess.Board("4k3/8/3p4/8/8/5N2/8/4K3 w - - 0 1")
    moves = tuple(m.uci() for m in board.legal_moves)
    for selected in (chess.E5, chess.D6, chess.F3):
        candidates = generate_candidates(board, selected, moves[:3])
        color = board.color_at(selected)
        color = board.turn if color is None else color
        for candidate in candidates:
            after = board.copy()
            after.push_uci(candidate.uci)
            delta = len(after.attackers(color, selected)) - len(board.attackers(color, selected))
            assert (CATEGORIES[1] in candidate.reasons) == (delta < 0)
            assert (CATEGORIES[2] in candidate.reasons) == (delta > 0)


def test_exchange_and_replacement_piece_are_not_confused():
    board = chess.Board("4k3/8/3p4/4n3/3P4/2N5/8/4K3 w - - 0 1")
    pv = ("d4e5", "d6e5")
    assert exchange_prefix(board, chess.D4, pv) == pv
    differences = feature_differences(board, chess.D4, pv)
    assert len(differences) == 2
    assert differences[0].after.tracked_piece.square == chess.E5
    assert differences[0].mobility_change is None
    assert differences[1].after.selected_piece_captured
    assert differences[1].after.tracked_piece is None
    assert differences[1].after.square_report.square.square == chess.D4
    black = snapshot(board, chess.E5, pv)
    assert black.selected_piece_captured and black.tracked_piece is None
    assert chess.Board(black.fen).piece_at(chess.E5) == chess.Piece(chess.PAWN, chess.BLACK)
    assert exchange_prefix(chess.Board(), chess.E2, ("g1f3", "g8f6")) is None
    with pytest.raises(ValueError):
        snapshot(board, chess.D4, ("d4d7",))


def test_en_passant_promotion_castling_and_request_history():
    ep = chess.Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
    assert snapshot(ep, chess.D5, ("e5d6",)).selected_piece_captured
    promotion = chess.Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    assert snapshot(promotion, chess.A7, ("a7a8q",)).tracked_piece.piece_type == chess.QUEEN
    castle = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    assert snapshot(castle, chess.H1, ("e1g1",)).tracked_piece.square == chess.F1
    board = chess.Board()
    board.push_uci("e2e4")
    request = ComparisonRequest(1, board, chess.E4, Settings())
    board.push_uci("e7e5")
    assert [m.uci() for m in request.board.move_stack] == ["e2e4"]
    assert ComparisonLimits().discovery_seconds + 4 * ComparisonLimits().branch_seconds == 5


def test_common_root_research_budgets_metadata_and_score_differences(tmp_path):
    events = queue.Queue()
    service = AnalysisService(events.put)
    trace = tmp_path / "uci.txt"
    board = chess.Board()
    board.push_uci("e2e4")
    try:
        service.submit_comparison(ComparisonRequest(7, board, chess.E4, Settings(), QUICK), [sys.executable, FAKE, "comparison", str(trace)])
        batch = comparison_event(events, "complete").batch
        assert 1 < len(batch.branches) <= 4
        assert batch.branches[0].candidate.reference
        assert batch.history == ("e2e4",) and batch.root_fen == chess.STARTING_FEN
        assert batch.starting_fen == board.fen()
        for branch in batch.branches:
            assert branch.analysis.pv[0] == branch.candidate.uci
            assert branch.analysis.starting_fen == board.fen()
            assert branch.analysis.settings.seconds == QUICK.branch_seconds
            assert branch.status == "completed, time-limited"
            assert score_difference(branch, batch.branches[0]) is not None
            for difference in branch.differences:
                work = board.copy(stack=True)
                for uci in difference.after.prefix:
                    assert chess.Move.from_uci(uci) in work.legal_moves
                    work.push_uci(uci)
                assert work.fen() == difference.after.fen
        lines = trace.read_text().splitlines()
        go = [line for line in lines if line.startswith("go ")]
        positions = [line for line in lines if line.startswith("position ")]
        assert len(go) == 1 + len(batch.branches) <= 5
        assert all("movetime 100" in line for line in go)
        assert all("searchmoves " + branch.candidate.uci in line for line, branch in zip(go[1:], batch.branches))
        assert set(positions) == {"position startpos moves e2e4"}
        assert "setoption name MultiPV value 3" in lines
        assert "setoption name MultiPV value 1" in lines
    finally:
        service.close()


@pytest.mark.parametrize("mode", ["bounded", "mate", "deep_exact"])
def test_score_quality_and_deepest_exact_selection(mode):
    events = queue.Queue()
    service = AnalysisService(events.put)
    try:
        service.submit_comparison(ComparisonRequest(1, chess.Board(), chess.E2, Settings(), QUICK), [sys.executable, FAKE, mode])
        batch = comparison_event(events, "complete").batch
        branch = batch.branches[0]
        if mode in ("bounded", "mate"):
            assert score_difference(branch, branch) is None
            assert branch.analysis.bound if mode == "bounded" else branch.analysis.mate is not None
        else:
            assert branch.analysis.depth == 8 and branch.analysis.centipawns == 42
            assert branch.analysis.bound is None
    finally:
        service.close()


@pytest.mark.parametrize("mode", ["no_multipv", "ignore_root", "partial_crash"])
def test_comparison_failures_preserve_completed_only_and_recover(mode):
    events = queue.Queue()
    service = AnalysisService(events.put)
    try:
        service.submit_comparison(ComparisonRequest(1, chess.Board(), chess.E2, Settings(), QUICK), [sys.executable, FAKE, mode])
        event = comparison_event(events, "error")
        assert event.batch.status == "incomplete"
        assert len(event.batch.branches) == (0 if mode == "no_multipv" else 1)
        if mode == "no_multipv":
            assert "MultiPV" in event.batch.message
        service.submit(AnalysisRequest(2, chess.Board(), Settings()), [sys.executable, FAKE])
        assert wait_event(events, "complete").request_id == 2
    finally:
        service.close()


def test_cancel_mid_batch_and_terminal_without_engine():
    events = queue.Queue()
    service = AnalysisService(events.put)
    try:
        service.submit_comparison(ComparisonRequest(1, chess.Board(), chess.E2, Settings(), QUICK), [sys.executable, FAKE, "partial_slow"])
        first = comparison_event(events, "branch")
        service.cancel()
        cancelled = comparison_event(events, "cancelled")
        assert cancelled.batch.status == "incomplete"
        assert cancelled.batch.branches == first.batch.branches
        board = chess.Board("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1")
        service.submit_comparison(ComparisonRequest(2, board, chess.H8, Settings(), QUICK))
        complete = comparison_event(events, "complete")
        assert not complete.batch.branches and "Terminal" in complete.batch.message
    finally:
        service.close()


def test_branch_timeout_preserves_only_completed_results():
    events = queue.Queue()
    service = AnalysisService(events.put, timeout_grace=.4)
    try:
        service.submit_comparison(ComparisonRequest(1, chess.Board(), chess.E2, Settings(), QUICK), [sys.executable, FAKE, "partial_slow"])
        event = comparison_event(events, "error")
        assert "timed out" in event.batch.message
        assert len(event.batch.branches) == 1
        assert event.batch.status == "incomplete"
    finally:
        service.close()


def test_missing_engine_comparison():
    events = queue.Queue()
    service = AnalysisService(events.put)
    try:
        service.submit_comparison(ComparisonRequest(1, chess.Board(), chess.E2, Settings(), QUICK))
        assert "Choose a local Stockfish" in comparison_event(events, "error").batch.message
    finally:
        service.close()


def test_single_legal_move():
    board = chess.Board("7k/8/6K1/8/8/8/8/R7 b - - 0 1")
    assert board.legal_moves.count() == 1
    events = queue.Queue()
    service = AnalysisService(events.put)
    try:
        service.submit_comparison(ComparisonRequest(1, board, chess.H8, Settings(), QUICK), [sys.executable, FAKE])
        batch = comparison_event(events, "complete").batch
        assert len(batch.branches) == 1 and "Only one legal move" in batch.message
    finally:
        service.close()


@pytest.mark.integration
def test_stockfish_comparison():
    path = os.environ.get("STOCKFISH_PATH")
    if not path:
        pytest.skip("Set STOCKFISH_PATH")
    events = queue.Queue()
    service = AnalysisService(events.put)
    board = chess.Board()
    board.push_uci("e2e4")
    try:
        service.submit_comparison(ComparisonRequest(1, board, chess.E4, Settings(engine_path=path), QUICK))
        batch = comparison_event(events, "complete").batch
        assert "Stockfish" in batch.engine_name and len(batch.branches) > 1
        for branch in batch.branches:
            assert branch.analysis.pv[0] == branch.candidate.uci
            assert branch.analysis.san() and branch.analysis.depth > 0
    finally:
        service.close()
