"""Comparison table, factual changes and expandable search evidence."""
from __future__ import annotations

from dataclasses import asdict
import json

import chess
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QHBoxLayout, QLabel,
                              QPushButton, QTableWidget, QTableWidgetItem, QTreeWidget,
                              QTreeWidgetItem, QVBoxLayout, QWidget)

from .comparisons import BranchResult, ComparisonResult, FeatureDifference, score_difference


def change_summary(difference: FeatureDifference) -> str:
    text = f"Square attacks: White {difference.white_control_change:+d}, Black {difference.black_control_change:+d}."
    if difference.after.selected_piece_captured:
        return text + " Selected piece captured."
    if difference.after.tracked_piece:
        text += f" Tracked piece: {difference.after.tracked_piece.label}."
    if difference.piece_attack_change is not None:
        text += f" Piece attack squares {difference.piece_attack_change:+d}."
    return text


class ComparisonPanel(QWidget):
    cancel_requested = Signal()
    replay_requested = Signal(int)
    return_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.batch: ComparisonResult | None = None
        layout = QVBoxLayout(self)
        self.progress = QLabel("Inspect a square or piece, then choose Compare continuations.")
        self.progress.setWordWrap(True)
        layout.addWidget(self.progress)
        self.cancel_button = QPushButton("Cancel comparison")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        layout.addWidget(self.cancel_button)
        note = QLabel("White-perspective continuation scores from a common starting position. Δ = branch minus reference; it is not a causal explanation.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Move", "White eval", "Δ vs ref"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(150)
        self.table.itemSelectionChanged.connect(self.show_selected)
        layout.addWidget(self.table)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.evidence = QTreeWidget()
        self.evidence.setHeaderLabel("Branch evidence — expand to inspect")
        layout.addWidget(self.evidence, 1)
        replay = QHBoxLayout()
        self.back = QPushButton("PV ◀")
        self.forward = QPushButton("PV ▶")
        self.return_button = QPushButton("Return to position")
        self.back.clicked.connect(lambda: self.replay_requested.emit(-1))
        self.forward.clicked.connect(lambda: self.replay_requested.emit(1))
        self.return_button.clicked.connect(self.return_requested.emit)
        for button in (self.back, self.forward, self.return_button):
            replay.addWidget(button)
        layout.addLayout(replay)
        self.clear()

    def selected_branch(self) -> BranchResult | None:
        row = self.table.currentRow()
        return self.batch.branches[row] if self.batch and 0 <= row < len(self.batch.branches) else None

    def clear(self) -> None:
        self.batch = None
        self.table.setRowCount(0)
        self.evidence.clear()
        self.summary.clear()
        self.progress.setText("Inspect a square or piece, then choose Compare continuations.")
        self.cancel_button.setEnabled(False)
        self.back.setEnabled(False)
        self.forward.setEnabled(False)

    def set_batch(self, batch: ComparisonResult) -> None:
        selected = self.table.currentRow()
        self.batch = batch
        self.progress.setText(f"{chess.square_name(batch.selected_square)} · {batch.status.capitalize()}: {batch.message}")
        self.cancel_button.setEnabled(batch.status == "running")
        reference = next((b for b in batch.branches if b.candidate.reference), None)
        self.table.blockSignals(True)
        self.table.setRowCount(len(batch.branches))
        for row, branch in enumerate(batch.branches):
            delta = score_difference(branch, reference)
            values = (branch.candidate.san + (" (ref)" if branch.candidate.reference else ""),
                      branch.analysis.score_text, f"{delta / 100:+.2f}" if delta is not None else "—")
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip("; ".join(branch.candidate.reasons) + "\n" + branch.status)
                self.table.setItem(row, column, item)
        if batch.branches:
            self.table.selectRow(max(0, min(selected, len(batch.branches) - 1)))
        self.table.blockSignals(False)
        self.show_selected()

    def show_selected(self) -> None:
        branch = self.selected_branch()
        self.back.setEnabled(branch is not None)
        self.forward.setEnabled(branch is not None)
        self.evidence.clear()
        if not branch or not self.batch:
            self.summary.clear()
            return
        self.summary.setText("; ".join(branch.candidate.reasons) + "\n" +
                             (change_summary(branch.differences[0]) if branch.differences else ""))

        def group(title: str, lines: list[str]) -> None:
            parent = QTreeWidgetItem([title])
            parent.setToolTip(0, title)
            self.evidence.addTopLevelItem(parent)
            for text in lines:
                child = QTreeWidgetItem([text])
                child.setToolTip(0, text)
                parent.addChild(child)

        group("Search and score evidence", [f"Evidence status: {branch.status}",
              f"Engine: {branch.analysis.engine_name}", f"Starting FEN: {self.batch.starting_fen}",
              f"History root FEN: {self.batch.root_fen}", "History: " + " ".join(self.batch.history),
              f"Root move: {branch.candidate.san} ({branch.candidate.uci})", "PV: " + branch.analysis.san(),
              "UCI PV: " + " ".join(branch.analysis.pv), f"Depth: {branch.analysis.depth}",
              f"Search time: {branch.analysis.settings.seconds}s requested, {branch.analysis.elapsed:.3f}s elapsed",
              f"Resources: {branch.analysis.settings.threads} thread(s), {branch.analysis.settings.hash_mb} MiB hash",
              "Scores evaluate continuations from the starting position, not the snapshot endpoint."])
        for diff in branch.differences:
            prefix = chess.Board(self.batch.starting_fen).variation_san([chess.Move.from_uci(m) for m in diff.after.prefix])
            lines = [change_summary(diff), f"Before FEN: {diff.before.fen}", f"After FEN: {diff.after.fen}",
                     "UCI prefix: " + " ".join(diff.after.prefix),
                     f"Piece attackers change: {diff.piece_attacker_change}",
                     f"Piece defenders change: {diff.piece_defender_change}",
                     "Legal mobility change: " + (str(diff.mobility_change) if diff.mobility_change is not None else "unavailable across opposing turns or after capture")]
            if diff.after.terminal:
                lines.append("Endpoint outcome: " + diff.after.terminal)
            group("Feature snapshot after " + prefix, lines)
        group("Structured evidence record", [json.dumps(asdict(branch)), json.dumps(asdict(self.batch.limits))])
