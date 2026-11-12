import chess
import pytest
from counterfactual_chess.position import PositionManager


def test_fen_atomic_and_move_history():
    manager = PositionManager()
    manager.play(chess.Move.from_uci("e2e4"))
    original = manager.board.fen()
    for fen in ("bad", "8/8/8/8/8/8/8/8 w - - 0 1"):
        with pytest.raises(ValueError):
            manager.load_fen(fen)
        assert manager.board.fen() == original
    assert len(manager.board.move_stack) == 1
    with pytest.raises(ValueError):
        manager.play(chess.Move.from_uci("e7e4"))


@pytest.mark.parametrize("fen,move", [
    ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1"),
    ("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6"),
    ("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a7a8n"),
])
def test_special_moves(fen, move):
    manager = PositionManager()
    manager.load_fen(fen)
    manager.play(chess.Move.from_uci(move))
    assert manager.board.peek().uci() == move


def test_pgn_games_navigation_and_continuation():
    manager = PositionManager()
    manager.load_pgn('[White "A"]\n\n1. e4 e5 2. Nf3 *\n\n[White "B"]\n\n1. d4 *')
    assert len(manager.games) == 2
    manager.navigate(2)
    manager.play(chess.Move.from_uci("b1c3"))
    assert manager.continuation
    manager.navigate(3)
    assert manager.board.peek().uci() == "g1f3"
    manager.select_game(1)
    manager.navigate(1)
    assert manager.board.peek().uci() == "d2d4"


def test_custom_pgn_and_malformed_atomic():
    manager = PositionManager()
    manager.load_pgn('[SetUp "1"]\n[FEN "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"]\n\n1. a8=Q+ *')
    manager.navigate(1)
    original = manager.board.fen()
    assert manager.board.piece_at(chess.A8).piece_type == chess.QUEEN
    with pytest.raises(ValueError):
        manager.load_pgn('1. e4 e5 2. Bh6 *')
    assert manager.board.fen() == original
