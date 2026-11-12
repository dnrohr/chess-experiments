"""Painted Qt board; chess rules remain in the position manager."""
from importlib.resources import files
import math

import chess
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from .features import InspectionReport


class BoardWidget(QWidget):
    square_clicked = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("chessBoard")
        self.setMinimumSize(360, 360)
        self.board = chess.Board()
        self.flipped = False
        self.selected: int | None = None
        self.destinations: set[int] = set()
        self.inspection_report: InspectionReport | None = None
        self.show_inspection_overlays = True
        self.hovered_squares: tuple[int, ...] = ()
        self.renderers = {
            symbol: QSvgRenderer(str(files("counterfactual_chess").joinpath("assets", f"{symbol}.svg")))
            for symbol in ("wp", "wn", "wb", "wr", "wq", "wk", "bp", "bn", "bb", "br", "bq", "bk")
        }

    def geometry_values(self) -> tuple[float, float, float]:
        size = min(self.width(), self.height())
        return (self.width() - size) / 2, (self.height() - size) / 2, size / 8

    def square_center(self, square: int) -> QPointF:
        x, y, cell = self.geometry_values()
        file, rank = chess.square_file(square), chess.square_rank(square)
        col, row = (7 - file, rank) if self.flipped else (file, 7 - rank)
        return QPointF(x + (col + .5) * cell, y + (row + .5) * cell)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _, _, cell = self.geometry_values()
        for square in chess.SQUARES:
            center = self.square_center(square)
            rect = QRectF(center.x() - cell / 2, center.y() - cell / 2, cell, cell)
            color = "#eadfc9" if (chess.square_file(square) + chess.square_rank(square)) % 2 else "#779184"
            painter.fillRect(rect, QColor("#d9bd62" if square == self.selected else color))
            piece = self.board.piece_at(square)
            if piece:
                key = ("w" if piece.color else "b") + piece.symbol().lower()
                self.renderers[key].render(painter, rect.adjusted(cell * .08, cell * .08, -cell * .08, -cell * .08))
            if square in self.destinations:
                painter.setBrush(QColor(30, 60, 50, 135))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(center, cell * .12, cell * .12)
            painter.setPen(QColor("#253c32"))
            if (not self.flipped and chess.square_rank(square) == 0) or (self.flipped and chess.square_rank(square) == 7):
                painter.drawText(rect.adjusted(3, 0, -3, -1), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, chess.FILE_NAMES[chess.square_file(square)])
            if (not self.flipped and chess.square_file(square) == 0) or (self.flipped and chess.square_file(square) == 7):
                painter.drawText(rect.adjusted(3, 1, 0, 0), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, str(chess.square_rank(square) + 1))
        if self.show_inspection_overlays and self.inspection_report:
            self.paint_inspection(painter, cell)

    def paint_inspection(self, painter: QPainter, cell: float) -> None:
        report = self.inspection_report
        assert report is not None
        target = self.square_center(report.square.square)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for color, attackers in ((True, report.square.white_attackers), (False, report.square.black_attackers)):
            ink = QColor("#145cbe" if color else "#852cab")
            ink.setAlpha(210)
            pen = QPen(ink, max(2., cell * .035), Qt.PenStyle.SolidLine if color else Qt.PenStyle.DashLine)
            painter.setPen(pen)
            for piece in attackers:
                start = self.square_center(piece.square)
                delta = target - start
                distance = math.hypot(delta.x(), delta.y())
                unit = delta / distance
                a, b = start + unit * cell * .32, target - unit * cell * .32
                painter.drawEllipse(start, cell * .36, cell * .36)
                painter.drawLine(a, b)
                side = type(unit)(-unit.y(), unit.x())
                painter.drawLine(b, b - unit * cell * .12 + side * cell * .07)
                painter.drawLine(b, b - unit * cell * .12 - side * cell * .07)
        if report.piece:
            color = report.piece.piece.color
            painter.setPen(QPen(QColor("#145cbe" if color else "#852cab"), max(2., cell * .03),
                                Qt.PenStyle.SolidLine if color else Qt.PenStyle.DashLine))
            for square in report.piece.attacked_squares:
                c = self.square_center(square)
                left, top = c.x() - cell * .4, c.y() - cell * .4
                right, bottom = c.x() + cell * .4, c.y() + cell * .4
                painter.drawLine(QPointF(left, top + cell * .18), QPointF(left, top))
                painter.drawLine(QPointF(left, top), QPointF(left + cell * .18, top))
                painter.drawLine(QPointF(right, bottom - cell * .18), QPointF(right, bottom))
                painter.drawLine(QPointF(right, bottom), QPointF(right - cell * .18, bottom))
        destinations = {m.to_square for m in report.square.legal_moves_to}
        if report.piece:
            destinations.update(report.piece.legal_destinations or ())
        painter.setPen(QPen(QColor("#006a47"), 2))
        painter.setBrush(QColor("#34cf8b"))
        for square in destinations:
            center = self.square_center(square) + QPointF(cell * .26, cell * .26)
            painter.drawEllipse(center, cell * .065, cell * .065)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#b57900"), max(3., cell * .055)))
        painter.drawRect(QRectF(target.x() - cell * .46, target.y() - cell * .46, cell * .92, cell * .92))
        painter.setPen(QPen(QColor("#e97213"), max(3., cell * .05), Qt.PenStyle.DotLine))
        for square in self.hovered_squares:
            center = self.square_center(square)
            painter.drawRect(QRectF(center.x() - cell * .41, center.y() - cell * .41, cell * .82, cell * .82))

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y, cell = self.geometry_values()
        col = int((event.position().x() - x) // cell)
        row = int((event.position().y() - y) // cell)
        if 0 <= col < 8 and 0 <= row < 8:
            self.square_clicked.emit(chess.square(7 - col if self.flipped else col, row if self.flipped else 7 - row))
