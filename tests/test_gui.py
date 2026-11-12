import chess
from PySide6.QtCore import Qt, QTimer
import pytest

from counterfactual_chess.analysis import AnalysisEvent, AnalysisRequest, result_from_info
from counterfactual_chess.gui import MainWindow
from counterfactual_chess.settings import Settings
import chess.engine


@pytest.fixture
def window(qtbot):
    window = MainWindow(Settings(), persist_settings=False)
    qtbot.addWidget(window)
    window.show()
    yield window
    window.close()


def test_click_moves_fen_and_flip(window, qtbot):
    for square in (chess.E2, chess.E4):
        qtbot.mouseClick(window.board, Qt.MouseButton.LeftButton, pos=window.board.square_center(square).toPoint())
    assert window.position.board.peek().uci() == "e2e4"
    original = window.position.board.fen()
    window.fen_input.setText("invalid")
    window.apply_fen()
    assert window.position.board.fen() == original
    assert "rejected" in window.status.text()
    window.flip()
    for square in (chess.E7, chess.E5):
        qtbot.mouseClick(window.board, Qt.MouseButton.LeftButton, pos=window.board.square_center(square).toPoint())
    assert window.position.board.peek().uci() == "e7e5"
    window.fen_input.setText(chess.STARTING_FEN)
    window.apply_fen()
    assert window.position.board.fen() == chess.STARTING_FEN


def test_promotion_choice(window, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    window.fen_input.setText("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    window.apply_fen()
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: ("Knight", True))
    window.on_square(chess.A7)
    window.on_square(chess.A8)
    assert window.position.board.piece_at(chess.A8).piece_type == chess.KNIGHT


def test_pgn_and_result_replay_stale_events(window):
    window.load_pgn_text("1. e4 e5 *")
    window.navigate(1)
    result = result_from_info(AnalysisRequest(window.request_id, window.position.board, Settings()),
        {"score": chess.engine.PovScore(chess.engine.Cp(42), chess.BLACK), "pv": [chess.Move.from_uci("e7e5")]}, "test", .1)
    window.on_analysis_event(AnalysisEvent(window.request_id, "complete", result))
    assert window.score_label.text() == "-0.42"
    original = window.position.board.fen()
    window.replay(1)
    assert window.board.board.fen() != original
    assert window.position.board.fen() == original
    window.return_to_position()
    assert window.board.board.fen() == original
    window.navigate(1)
    window.on_analysis_event(AnalysisEvent(result.request_id, "complete", result))
    assert window.result is None
    assert window.score_label.text() == "No analysis yet"


def test_worker_signal_responsiveness_and_cancel(window, qtbot):
    import sys
    from test_analysis import FAKE
    original_submit = window.service.submit
    window.service.submit = lambda request: original_submit(request, [sys.executable, FAKE, "slow"])
    ticks = []
    timer = QTimer(window)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    window.analyze()
    qtbot.waitUntil(lambda: window.result is not None, timeout=5000)
    qtbot.waitUntil(lambda: len(ticks) >= 5)
    window.cancel()
    assert window.result is None
    assert window.analyze_button.isEnabled()
    assert "cancelled" in window.status.text()


def test_inspect_mode_never_moves_and_switching_preserves_results(window, qtbot):
    window.on_square(chess.E2)
    assert window.board.selected == chess.E2
    request_id = window.request_id
    window.mode_selector.setCurrentText("Inspect")
    assert window.board.selected is None and not window.board.destinations
    assert window.tabs.currentWidget() is window.inspector
    for square in (chess.E2, chess.E4, chess.E7):
        qtbot.mouseClick(window.board, Qt.MouseButton.LeftButton, pos=window.board.square_center(square).toPoint())
        assert window.board.inspection_report.square.square == square
    assert window.position.board.fen() == chess.STARTING_FEN
    assert window.board.inspection_report.piece.legal_moves is None
    assert window.request_id == request_id
    window.mode_selector.setCurrentText("Move")
    assert window.board.inspection_report is None
    for square in (chess.E2, chess.E4):
        window.on_square(square)
    assert window.position.board.peek().uci() == "e2e4"


def test_inspection_overlays_hover_and_flipped_selection(window, qtbot):
    window.mode_selector.setCurrentText("Inspect")
    window.flip()
    qtbot.mouseClick(window.board, Qt.MouseButton.LeftButton, pos=window.board.square_center(chess.B8).toPoint())
    report = window.board.inspection_report
    assert report.square.square == chess.B8
    window.inspector.show_overlays.setChecked(False)
    assert not window.board.show_inspection_overlays
    assert window.board.inspection_report == report
    window.inspector.show_overlays.setChecked(True)
    item = window.inspector.tree.topLevelItem(0)
    assert item.childCount() > 0 and not item.isExpanded()
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.processEvents()  # Apply tab/summary layout before locating a row.
    qtbot.mouseMove(window.inspector.tree.viewport(), pos=window.inspector.tree.visualItemRect(item).center())
    qtbot.waitUntil(lambda: chess.B8 in window.board.hovered_squares)
    assert chess.B8 in window.board.hovered_squares
    from PySide6.QtCore import QEvent
    window.inspector.eventFilter(window.inspector.tree.viewport(), QEvent(QEvent.Type.Leave))
    assert not window.board.hovered_squares
    window.flip()
    assert window.board.inspection_report == report
    # Exercise both colored relationship overlays and the complete paint path.
    assert not window.board.grab().isNull()


def test_contested_relationships_are_painted_in_both_colors(window):
    window.fen_input.setText("4k3/8/3p4/4n3/3P4/2N5/8/4K3 w - - 0 1")
    window.apply_fen()
    window.mode_selector.setCurrentText("Inspect")
    window.on_square(chess.E5)
    assert window.board.inspection_report.square.contested
    assert not window.board.grab().isNull()


@pytest.mark.parametrize("change", ["fen", "pgn", "navigate", "game", "reset"])
def test_position_changes_clear_inspection(window, change):
    window.load_pgn_text('[White "A"]\n\n1. e4 *\n\n[White "B"]\n\n1. d4 *')
    window.mode_selector.setCurrentText("Inspect")
    window.on_square(chess.E2)
    assert window.board.inspection_report is not None
    if change == "fen":
        window.fen_input.setText(chess.STARTING_FEN)
        window.apply_fen()
    elif change == "pgn":
        window.load_pgn_text("1. c4 *")
    elif change == "navigate":
        window.navigate(1)
    elif change == "game":
        window.game_selector.setCurrentIndex(1)
    else:
        window.new_position()
    assert window.board.inspection_report is None
    assert window.inspector.tree.topLevelItemCount() == 0


def test_inspection_during_analysis_completion_and_cancel(window, qtbot):
    import sys
    from test_analysis import FAKE
    original_submit = window.service.submit
    window.service.submit = lambda request: original_submit(request, [sys.executable, FAKE, "slow"])
    window.mode_selector.setCurrentText("Inspect")
    window.on_square(chess.E2)
    inspected = window.board.inspection_report
    window.analyze()
    assert window.board.inspection_report == inspected
    qtbot.waitUntil(lambda: window.result is not None, timeout=5000)
    result = window.result
    request_id = window.request_id
    window.on_square(chess.B8)
    assert window.result == result and window.request_id == request_id
    window.mode_selector.setCurrentText("Move")
    assert window.result == result and window.cancel_button.isEnabled()
    window.mode_selector.setCurrentText("Inspect")
    window.on_square(chess.D4)
    inspected = window.board.inspection_report
    window.cancel()
    assert window.board.inspection_report == inspected
    assert window.result is None
    result = result_from_info(AnalysisRequest(window.request_id, window.position.board, Settings()),
        {"score": chess.engine.PovScore(chess.engine.Cp(20), chess.WHITE), "pv": [chess.Move.from_uci("e2e4")]}, "test", .1)
    window.on_analysis_event(AnalysisEvent(window.request_id, "complete", result))
    assert window.board.inspection_report == inspected


def test_inspection_of_preview_follows_displayed_fen(window):
    result = result_from_info(AnalysisRequest(window.request_id, window.position.board, Settings()),
        {"score": chess.engine.PovScore(chess.engine.Cp(20), chess.WHITE),
         "pv": [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")]}, "test", .1)
    window.on_analysis_event(AnalysisEvent(window.request_id, "complete", result))
    window.mode_selector.setCurrentText("Inspect")
    window.on_square(chess.E2)
    window.replay(1)
    assert window.board.inspection_report is None
    window.on_square(chess.E4)
    report = window.board.inspection_report
    assert report.fen == window.board.board.fen()
    assert report.fen != window.position.board.fen()
    assert "PV preview" in window.inspector.heading.text()
    assert report.piece.legal_moves is None  # White pawn, Black's turn in preview.
    assert window.result == result
    window.replay(1)
    assert window.board.inspection_report is None
    window.on_square(chess.E5)
    window.return_to_position()
    assert window.board.inspection_report is None
    assert window.board.board.fen() == chess.STARTING_FEN
    assert window.result == result
