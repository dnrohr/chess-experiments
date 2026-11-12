"""Desktop controller and views. Worker callbacks cross a Qt signal bridge."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path

import chess
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QSplitter, QTextEdit,
    QTabWidget, QVBoxLayout, QWidget,
)

from .analysis import AnalysisEvent, AnalysisRequest, AnalysisResult, AnalysisService
from .board import BoardWidget
from .comparison_view import ComparisonPanel
from .comparisons import ComparisonEvent, ComparisonRequest, ComparisonResult
from .explanations import explain
from .features import inspect_position
from .inspection import InspectionPanel
from .position import PositionManager
from .settings import Settings, load_settings, save_settings


class EventBridge(QObject):
    event = Signal(object)


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Local engine settings")
        layout = QFormLayout(self)
        row = QHBoxLayout()
        self.path = QLineEdit(settings.engine_path)
        self.path.setMinimumWidth(350)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        row.addWidget(self.path)
        row.addWidget(browse)
        layout.addRow("Stockfish executable", row)
        self.threads = QSpinBox()
        self.threads.setRange(1, 256)
        self.threads.setValue(settings.threads)
        self.hash = QSpinBox()
        self.hash.setRange(1, 4096)
        self.hash.setSuffix(" MiB")
        self.hash.setValue(settings.hash_mb)
        self.seconds = QDoubleSpinBox()
        self.seconds.setRange(.1, 120)
        self.seconds.setSingleStep(.5)
        self.seconds.setSuffix(" seconds")
        self.seconds.setValue(settings.seconds)
        layout.addRow("Threads", self.threads)
        layout.addRow("Hash memory", self.hash)
        layout.addRow("Analysis time", self.seconds)
        layout.addRow(QLabel("Low-resource defaults: 1 thread · 64 MiB · 1 second.\nEngine capability limits are checked before searching."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select local Stockfish executable", "", "Executables (*.exe);;All files (*)")
        if path:
            self.path.setText(path)

    def value(self) -> Settings:
        return Settings(self.path.text().strip(), self.threads.value(), self.hash.value(), self.seconds.value())


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None, persist_settings: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("Counterfactual Chess · Local analysis")
        self.resize(1150, 760)
        self.position = PositionManager()
        self.settings = settings or load_settings()
        self.persist_settings = persist_settings
        self.request_id = 0
        self.result: AnalysisResult | None = None
        self.replay_ply: int | None = None
        self.replay_result: AnalysisResult | None = None
        self.comparison: ComparisonResult | None = None
        self.comparison_id: int | None = None
        self.active_job: str | None = None
        self.bridge = EventBridge(self)
        self.bridge.event.connect(self.on_analysis_event)
        self.service = AnalysisService(self.bridge.event.emit)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        toolbar = QHBoxLayout()
        self.button(toolbar, "New position", self.new_position)
        self.button(toolbar, "Open PGN…", self.open_pgn)
        self.button(toolbar, "Flip board", self.flip)
        self.button(toolbar, "Engine settings…", self.engine_settings)
        toolbar.addWidget(QLabel("Board mode"))
        self.mode_selector = QComboBox()
        self.mode_selector.addItems(["Move", "Inspect"])
        self.mode_selector.currentIndexChanged.connect(self.change_mode)
        toolbar.addWidget(self.mode_selector)
        layout.addLayout(toolbar)
        fen_row = QHBoxLayout()
        self.fen_input = QLineEdit()
        self.fen_input.setObjectName("fenInput")
        self.fen_input.returnPressed.connect(self.apply_fen)
        fen_row.addWidget(QLabel("FEN"))
        fen_row.addWidget(self.fen_input)
        self.button(fen_row, "Load FEN", self.apply_fen)
        self.button(fen_row, "Copy FEN", lambda: QApplication.clipboard().setText(self.board.board.fen()))
        layout.addLayout(fen_row)

        split = QSplitter()
        self.board = BoardWidget()
        self.board.square_clicked.connect(self.on_square)
        split.addWidget(self.board)
        panel = QWidget()
        right = QVBoxLayout(panel)
        heading = QLabel("Position analysis")
        heading.setStyleSheet("font-size: 22px; font-weight: 600")
        right.addWidget(heading)
        self.turn_label = QLabel()
        right.addWidget(self.turn_label)
        self.game_selector = QComboBox()
        self.game_selector.currentIndexChanged.connect(self.select_game)
        right.addWidget(self.game_selector)
        navigation = QHBoxLayout()
        for text, target in (("|◀", 0), ("◀", -1), ("▶", 1), ("▶|", 999999)):
            self.button(navigation, text, lambda checked=False, t=target: self.navigate(t))
        right.addLayout(navigation)
        self.position_label = QLabel()
        right.addWidget(self.position_label)
        self.tabs = QTabWidget()
        right.addWidget(self.tabs, 1)
        engine_panel = QWidget()
        self.engine_panel = engine_panel
        engine = QVBoxLayout(engine_panel)
        self.tabs.addTab(engine_panel, "Engine")
        self.inspector = InspectionPanel()
        self.inspector.overlays_toggled.connect(self.toggle_overlays)
        self.inspector.hover_squares.connect(self.highlight_evidence)
        self.tabs.addTab(self.inspector, "Inspect")
        self.comparison_panel = ComparisonPanel()
        self.comparison_panel.cancel_requested.connect(self.cancel_comparison)
        self.comparison_panel.replay_requested.connect(self.replay_comparison)
        self.comparison_panel.return_requested.connect(self.return_to_position)
        self.inspector.compare_button.clicked.connect(self.compare_continuations)
        self.tabs.addTab(self.comparison_panel, "Compare")
        self.tabs.currentChanged.connect(lambda: self.highlight_evidence(()))
        analysis_row = QHBoxLayout()
        self.analyze_button = self.button(analysis_row, "Analyze", self.analyze)
        self.cancel_button = self.button(analysis_row, "Cancel", self.cancel)
        self.cancel_button.setEnabled(False)
        engine.addLayout(analysis_row)
        self.score_label = QLabel("No analysis yet")
        self.score_label.setStyleSheet("font-size: 24px; font-weight: 600")
        engine.addWidget(self.score_label)
        engine.addWidget(QLabel("Evaluation perspective: White"))
        self.pv_text = QTextEdit()
        self.pv_text.setReadOnly(True)
        self.pv_text.setPlaceholderText("The engine's principal variation will appear here.")
        engine.addWidget(self.pv_text)
        replay_row = QHBoxLayout()
        self.button(replay_row, "PV ◀", lambda: self.replay(-1))
        self.button(replay_row, "PV ▶", lambda: self.replay(1))
        self.button(replay_row, "Return to position", self.return_to_position)
        engine.addLayout(replay_row)
        self.metadata = QTextEdit()
        self.metadata.setReadOnly(True)
        self.metadata.setMaximumHeight(160)
        self.metadata.setPlaceholderText("Engine identity, search settings and starting FEN.")
        engine.addWidget(self.metadata)
        right.addWidget(QLabel("Offline · CPU only · No accounts or cloud services"))
        split.addWidget(panel)
        split.setSizes([640, 460])
        layout.addWidget(split, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()
        self.status.setText("Ready. Choose a local Stockfish executable in Engine settings." if not self.settings.engine_path else "Ready for local analysis.")

    @staticmethod
    def button(layout, text: str, callback) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def invalidate(self) -> None:
        self.invalidate_comparison()
        self.request_id += 1
        self.service.cancel()
        self.active_job = None
        self.result = None
        self.replay_result = None
        if self.replay_ply is not None:
            self.clear_inspection()
            self.replay_ply = None
        self.board.selected = None
        self.board.destinations.clear()
        self.score_label.setText("No analysis yet")
        self.pv_text.clear()
        self.metadata.clear()
        self.cancel_button.setEnabled(False)
        self.analyze_button.setEnabled(True)
        self.update_compare_button()

    def refresh(self) -> None:
        self.board.board = self.position.board.copy(stack=True)
        self.board.update()
        self.fen_input.setText(self.position.board.fen())
        color = "White" if self.position.board.turn else "Black"
        self.turn_label.setText(f"{color} to move" + (" · Check" if self.position.board.is_check() else ""))
        self.position_label.setText(
            f"Mainline: {self.position.ply}/{self.position.length}" + (" · Local continuation" if self.position.continuation else "")
            if self.position.games else "Free position"
        )

    def changed(self) -> None:
        self.clear_inspection()
        self.invalidate()
        self.refresh()
        self.status.setText("Position changed. Select Analyze to search this position.")

    def new_position(self) -> None:
        self.position.load_fen(chess.STARTING_FEN)
        self.populate_games()
        self.changed()

    def apply_fen(self) -> None:
        try:
            self.position.load_fen(self.fen_input.text().strip())
        except ValueError as exc:
            self.status.setText(f"FEN rejected: {exc}")
            return
        self.populate_games()
        self.changed()

    def open_pgn(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Open PGN", "", "Chess games (*.pgn);;All files (*)")
        if filename:
            try:
                self.load_pgn_text(Path(filename).read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                self.status.setText(f"PGN rejected: {exc}")

    def load_pgn_text(self, text: str) -> None:
        self.position.load_pgn(text)
        self.populate_games()
        self.changed()

    def populate_games(self) -> None:
        self.game_selector.blockSignals(True)
        self.game_selector.clear()
        for index, game in enumerate(self.position.games):
            self.game_selector.addItem(f"{index + 1}. {game.headers.get('White', '?')} — {game.headers.get('Black', '?')}")
        self.game_selector.blockSignals(False)

    def select_game(self, index: int) -> None:
        if index >= 0:
            self.position.select_game(index)
            self.changed()

    def navigate(self, target: int) -> None:
        if self.position.games:
            self.position.navigate(self.position.ply + target if target in (-1, 1) else target)
            self.changed()

    def flip(self) -> None:
        self.board.flipped = not self.board.flipped
        self.board.update()

    def on_square(self, square: int) -> None:
        if self.mode_selector.currentText() == "Inspect":
            if self.replay_ply is None and self.comparison is not None and square != self.comparison.selected_square:
                self.invalidate_comparison()
            elif self.replay_ply is None and self.comparison_id is not None and self.board.inspection_report and square != self.board.inspection_report.square.square:
                self.invalidate_comparison()
            report = inspect_position(self.board.board, square)
            self.board.inspection_report = report
            self.inspector.set_report(report, explain(report), self.replay_ply is not None)
            self.tabs.setCurrentWidget(self.inspector)
            self.board.update()
            self.update_compare_button()
            return
        if self.replay_ply is not None:
            self.status.setText("Return to position before entering a move.")
            return
        selected = self.board.selected
        if selected is not None:
            moves = [m for m in self.position.board.legal_moves if m.from_square == selected and m.to_square == square]
            if moves:
                move = moves[0]
                if move.promotion:
                    choices = ["Queen", "Rook", "Bishop", "Knight"]
                    choice, ok = QInputDialog.getItem(self, "Promotion", "Promote to", choices, 0, False)
                    if not ok:
                        return
                    move = next(m for m in moves if m.promotion == {"Queen": chess.QUEEN, "Rook": chess.ROOK, "Bishop": chess.BISHOP, "Knight": chess.KNIGHT}[choice])
                self.position.play(move)
                self.changed()
                return
        piece = self.position.board.piece_at(square)
        self.board.selected = square if piece and piece.color == self.position.board.turn else None
        self.board.destinations = {m.to_square for m in self.position.board.legal_moves if m.from_square == self.board.selected}
        self.board.update()

    def engine_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                settings = dialog.value()
                settings.validate()
                if self.persist_settings:
                    save_settings(settings)
                self.settings = settings
                self.invalidate()
                self.refresh()
                self.status.setText("Engine settings updated.")
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Settings could not be saved", str(exc))

    def analyze(self) -> None:
        self.invalidate()
        self.refresh()
        self.status.setText("Analyzing locally…")
        self.analyze_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.active_job = "analysis"
        self.service.submit(AnalysisRequest(self.request_id, self.position.board, self.settings))

    def cancel(self) -> None:
        self.invalidate()
        self.refresh()
        self.status.setText("Analysis cancelled.")

    def on_analysis_event(self, event: AnalysisEvent | ComparisonEvent) -> None:
        if isinstance(event, ComparisonEvent):
            self.on_comparison_event(event)
            return
        if event.request_id != self.request_id:
            return
        if event.result:
            self.result = event.result
            self.score_label.setText(event.result.score_text)
            self.pv_text.setPlainText(event.result.san())
            self.metadata.setPlainText(json.dumps(asdict(event.result), indent=2))
        if event.kind in ("complete", "error", "cancelled"):
            self.active_job = None
            self.analyze_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.status.setText({"complete": "Analysis complete. Replay the PV to inspect the engine's line.", "error": f"Analysis failed: {event.message}", "cancelled": "Analysis cancelled."}[event.kind])
            self.update_compare_button()

    def replay(self, step: int) -> None:
        source = self.replay_result or self.result
        if not source or not source.pv or self.cancel_button.isEnabled():
            return
        ply = max(0, min((self.replay_ply or 0) + step, len(source.pv)))
        if self.replay_ply != ply:
            self.clear_inspection()
        self.replay_ply = ply
        board = self.position.board.copy(stack=True)
        for move in source.pv[:self.replay_ply]:
            board.push_uci(move)
        self.board.board = board
        self.board.selected = None
        self.board.destinations.clear()
        self.board.update()
        self.turn_label.setText(f"{'White' if board.turn else 'Black'} to move · PV preview")
        self.status.setText(f"PV preview {self.replay_ply}/{len(source.pv)}. Your position is preserved.")
        self.update_compare_button()

    def return_to_position(self) -> None:
        self.clear_inspection()
        self.replay_ply = None
        self.refresh()
        self.update_compare_button()
        self.status.setText("Returned to analyzed position.")

    def change_mode(self, index: int) -> None:
        if self.replay_ply is None and self.board.inspection_report:
            self.invalidate_comparison()
        self.board.selected = None
        self.board.destinations.clear()
        self.clear_inspection()
        self.tabs.setCurrentWidget(self.inspector if index == 1 else self.engine_panel)

    def clear_inspection(self) -> None:
        self.board.inspection_report = None
        self.board.hovered_squares = ()
        self.inspector.clear_report()
        self.board.update()
        self.update_compare_button()

    def update_compare_button(self) -> None:
        self.inspector.compare_button.setEnabled(self.board.inspection_report is not None and self.replay_ply is None and self.active_job != "comparison")
        self.inspector.compare_button.setToolTip("Return to the original position before comparing." if self.replay_ply is not None else "Compare up to four legal continuations with equal search limits.")

    def invalidate_comparison(self) -> None:
        if self.active_job == "comparison":
            self.service.cancel()
            self.active_job = None
        self.comparison_id = None
        self.comparison = None
        self.replay_result = None
        self.comparison_panel.clear()
        self.update_compare_button()

    def compare_continuations(self) -> None:
        report = self.board.inspection_report
        if report is None or self.replay_ply is not None:
            self.status.setText("Inspect a square in the original position before comparing.")
            return
        selected = report.square.square
        self.invalidate()
        self.refresh()
        self.active_job = "comparison"
        self.comparison_id = self.request_id
        self.tabs.setCurrentWidget(self.comparison_panel)
        self.comparison_panel.progress.setText("Discovering alternatives… Up to five seconds of search work plus engine overhead.")
        self.comparison_panel.cancel_button.setEnabled(True)
        self.update_compare_button()
        self.service.submit_comparison(ComparisonRequest(self.request_id, self.position.board, selected, self.settings))

    def on_comparison_event(self, event: ComparisonEvent) -> None:
        if event.request_id != self.comparison_id:
            return
        self.comparison = event.batch
        self.comparison_panel.set_batch(event.batch)
        if event.kind in ("complete", "cancelled", "error"):
            self.active_job = None
        self.status.setText(event.batch.message)
        self.update_compare_button()

    def cancel_comparison(self) -> None:
        if self.active_job != "comparison":
            return
        self.service.cancel()
        self.comparison_id = None
        self.active_job = None
        if self.comparison:
            self.comparison = replace(self.comparison, status="incomplete", message="Comparison cancelled. Completed branches are preserved.")
            self.comparison_panel.set_batch(self.comparison)
        else:
            self.comparison_panel.progress.setText("Incomplete: comparison cancelled before discovery finished.")
            self.comparison_panel.cancel_button.setEnabled(False)
        self.status.setText("Comparison cancelled. Completed evidence is preserved.")
        self.update_compare_button()

    def replay_comparison(self, step: int) -> None:
        branch = self.comparison_panel.selected_branch()
        if branch is None:
            return
        if self.replay_result is not branch.analysis:
            self.return_to_position()
            self.replay_result = branch.analysis
        self.replay(step)

    def toggle_overlays(self, checked: bool) -> None:
        self.board.show_inspection_overlays = checked
        self.board.update()

    def highlight_evidence(self, squares: tuple[int, ...]) -> None:
        self.board.hovered_squares = squares
        self.board.update()

    def closeEvent(self, event) -> None:
        self.request_id += 1
        self.service.close()
        super().closeEvent(event)
