"""Inspection view: short claims followed by expandable structured evidence."""
from __future__ import annotations

import chess
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .explanations import Explanation
from .features import InspectionReport


class InspectionPanel(QWidget):
    hover_squares = Signal(object)
    overlays_toggled = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.heading = QLabel("Inspect a square or piece")
        self.heading.setStyleSheet("font-size: 18px; font-weight: 600")
        layout.addWidget(self.heading)
        self.summary = QLabel("Choose Inspect mode, then click any square.")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        self.compare_button = QPushButton("Compare continuations")
        self.compare_button.setEnabled(False)
        layout.addWidget(self.compare_button)
        self.show_overlays = QCheckBox("Show overlays")
        self.show_overlays.setChecked(True)
        self.show_overlays.toggled.connect(self.overlays_toggled.emit)
        layout.addWidget(self.show_overlays)
        self.legend = QLabel("Gold outline: selected · Blue solid: White attacks\nPurple dashed: Black attacks · Green dots: legal destinations\nAttacker-to-square lines; piece attacks have corner marks.\nEvidence hover: orange outlines.")
        self.legend.setWordWrap(True)
        layout.addWidget(self.legend)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Facts and evidence — expand to inspect")
        self.tree.setWordWrap(True)
        self.tree.setMouseTracking(True)
        self.tree.itemEntered.connect(self.on_item_hover)
        self.tree.viewport().installEventFilter(self)
        layout.addWidget(self.tree, 1)
        caveat = QLabel("Geometric facts describe attacks and legality. They do not establish strategic importance.")
        caveat.setWordWrap(True)
        layout.addWidget(caveat)

    def clear_report(self) -> None:
        self.heading.setText("Inspect a square or piece")
        self.summary.setText("Choose Inspect mode, then click any square.")
        self.tree.clear()
        self.hover_squares.emit(())

    def set_report(self, report: InspectionReport, explanation: Explanation, preview: bool) -> None:
        self.tree.clear()
        self.hover_squares.emit(())
        self.heading.setText(f"{chess.square_name(report.square.square)} · {'PV preview' if preview else 'Current position'}")
        numbers = {claim.evidence_id: index for index, claim in enumerate(explanation.statements, 1)}
        self.summary.setText("\n".join(f"{claim.text} [{numbers[claim.evidence_id]}]" for claim in explanation.summary))
        by_id = {e.identifier: e for e in explanation.evidence}
        for claim in explanation.statements:
            evidence = by_id[claim.evidence_id]
            item = QTreeWidgetItem([f"[{numbers[claim.evidence_id]}] {claim.text}"])
            item.setToolTip(0, claim.text)
            item.setData(0, Qt.ItemDataRole.UserRole, evidence.squares)
            self.tree.addTopLevelItem(item)
            details: list[tuple[str, tuple[int, ...]]] = [
                ("Basis: " + evidence.basis, evidence.squares),
                ("Squares: " + ", ".join(chess.square_name(s) for s in evidence.squares), evidence.squares),
            ]
            details.extend((p.label, (p.square,)) for p in evidence.pieces)
            details.extend((f"Legal move: {m.san} ({m.uci})", (m.from_square, m.to_square)) for m in evidence.moves)
            details.append(("Displayed FEN: " + evidence.fen, evidence.squares))
            for text, squares in details:
                child = QTreeWidgetItem([text])
                child.setToolTip(0, text)
                child.setData(0, Qt.ItemDataRole.UserRole, squares)
                item.addChild(child)

    def on_item_hover(self, item: QTreeWidgetItem, column: int) -> None:
        self.hover_squares.emit(tuple(item.data(0, Qt.ItemDataRole.UserRole) or ()))

    def eventFilter(self, watched, event) -> bool:
        if watched is self.tree.viewport() and event.type() == QEvent.Type.Leave:
            self.hover_squares.emit(())
        return super().eventFilter(watched, event)
