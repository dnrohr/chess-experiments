"""Curated rules positions, with expectations independent of the renderer."""
import chess
import pytest

from counterfactual_chess.explanations import explain
from counterfactual_chess.features import inspect_position


def test_empty_contested_square_and_legal_arrivals():
    board = chess.Board("4k3/8/3p4/8/3P4/2N5/8/4K3 w - - 0 1")
    report = inspect_position(board, chess.E5)
    assert report.square.occupant is None and report.piece is None
    assert report.square.contested
    assert [p.square for p in report.square.white_attackers] == [chess.D4]
    assert [p.square for p in report.square.black_attackers] == [chess.D6]
    assert report.square.legal_moves_to == ()  # Empty pawn diagonal is not a push.


def test_occupied_square_attackers_defenders_and_opposing_mobility():
    board = chess.Board("4k3/8/3p4/4n3/3P4/2N5/8/4K3 w - - 0 1")
    report = inspect_position(board, chess.E5)
    assert report.square.occupant.color == chess.BLACK
    assert [p.square for p in report.square.defenders] == [chess.D6]
    assert [p.square for p in report.square.opposing_attackers] == [chess.D4]
    assert [m.uci for m in report.square.legal_moves_to] == ["d4e5"]
    assert report.piece.legal_moves is None and report.piece.legal_destinations is None
    assert "Legal mobility unavailable: this side is not to move" in [s.text for s in explain(report).summary]


def test_blocked_sliding_attacks_and_piece_targets():
    board = chess.Board("4k3/8/8/3p4/8/1P6/8/1R2K3 w - - 0 1")
    rook = inspect_position(board, chess.B1).piece
    assert chess.B3 in rook.attacked_squares and chess.B4 not in rook.attacked_squares
    assert {p.square for p in rook.defended_pieces} == {chess.B3, chess.E1}
    assert rook.attacked_pieces == ()
    bishop_board = chess.Board("4k3/8/8/5n2/8/3B4/8/4K3 w - - 0 1")
    bishop = inspect_position(bishop_board, chess.D3).piece
    assert [p.square for p in bishop.attacked_pieces] == [chess.F5]
    assert chess.G6 not in bishop.attacked_squares


def test_absolute_pin_keeps_geometry_but_limits_legality():
    board = chess.Board("k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1")
    report = inspect_position(board, chess.E2)
    rook = report.piece
    assert rook.absolute_pin and rook.king_square == chess.E1
    assert chess.E8 in rook.pin_line
    assert chess.D2 in rook.attacked_squares
    assert chess.D2 not in rook.legal_destinations
    assert chess.E8 in rook.legal_destinations  # A pinned piece may move on its pin line.
    d2 = inspect_position(board, chess.D2)
    assert chess.E2 in [p.square for p in d2.square.white_attackers]
    assert not any(m.from_square == chess.E2 for m in d2.square.legal_moves_to)


def test_pawn_pushes_attacks_and_king_geometry():
    board = chess.Board()
    pawn = inspect_position(board, chess.E2).piece
    assert set(pawn.attacked_squares) == {chess.D3, chess.F3}
    assert set(pawn.legal_destinations) == {chess.E3, chess.E4}
    king = inspect_position(board, chess.E1).piece
    assert chess.E2 in king.attacked_squares
    assert king.legal_destinations == ()
    assert not king.absolute_pin


@pytest.mark.parametrize("fen,square,moves", [
    ("4r1k1/8/8/8/8/8/8/4K2R w K - 0 1", chess.H1, set()),
    ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", chess.E1, {"e1g1", "e1c1"}),
    ("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", chess.E5, {"e5d6", "e5e6"}),
])
def test_legal_mobility_special_cases(fen, square, moves):
    board = chess.Board(fen)
    report = inspect_position(board, square)
    actual = {m.uci for m in report.piece.legal_moves}
    if not moves:
        assert not actual  # Rook cannot ignore check or castle out of check.
    else:
        assert moves <= actual
    if board.is_check():
        assert report.piece.legal_destinations == ()


def test_promotion_destinations_count_once_and_choices_are_explicit():
    board = chess.Board("1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    report = inspect_position(board, chess.A7)
    assert set(report.piece.legal_destinations) == {chess.A8, chess.B8}
    assert len(report.piece.legal_moves) == 8
    explanation = explain(report)
    promotion = next(s for s in explanation.statements if s.evidence_id == "promotions")
    assert all(choice in promotion.text for choice in ("a8", "b8", "knight", "bishop", "rook", "queen"))


def test_reports_and_evidence_match_without_mutating_history():
    board = chess.Board()
    board.push_uci("e2e4")
    fen, history = board.fen(), list(board.move_stack)
    for square in chess.SQUARES:
        report = inspect_position(board, square)
        explanation = explain(report)
        evidence = {e.identifier: e for e in explanation.evidence}
        assert len(evidence) == len(explanation.evidence)
        for statement in (*explanation.summary, *explanation.statements):
            item = evidence[statement.evidence_id]
            assert item.fen == fen and square in item.squares
            for piece in item.pieces:
                assert board.piece_at(piece.square) == chess.Piece(piece.piece_type, piece.color)
            for move in item.moves:
                chess_move = chess.Move.from_uci(move.uci)
                assert chess_move in board.legal_moves
                assert board.san(chess_move) == move.san
        assert report == inspect_position(board, square)
        assert explanation == explain(report)
    assert board.fen() == fen and board.move_stack == history


def test_terminal_and_invalid_square():
    board = chess.Board("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1")
    assert inspect_position(board, chess.H8).piece.legal_moves == ()
    with pytest.raises(ValueError):
        inspect_position(board, 64)
