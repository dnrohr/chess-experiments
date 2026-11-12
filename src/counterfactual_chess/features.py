"""Immutable geometric reports. No engine, Qt, or hypothetical turn changes."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

import chess


@dataclass(frozen=True)
class PieceFact:
    square: int
    color: bool
    piece_type: int

    @property
    def label(self) -> str:
        return f"{'White' if self.color else 'Black'} {chess.piece_name(self.piece_type)} on {chess.square_name(self.square)}"


@dataclass(frozen=True)
class MoveFact:
    uci: str
    san: str
    from_square: int
    to_square: int
    promotion: int | None


@dataclass(frozen=True)
class SquareReport:
    square: int
    occupant: PieceFact | None
    white_attackers: tuple[PieceFact, ...]
    black_attackers: tuple[PieceFact, ...]
    contested: bool
    legal_moves_to: tuple[MoveFact, ...]
    defenders: tuple[PieceFact, ...]
    opposing_attackers: tuple[PieceFact, ...]


@dataclass(frozen=True)
class PieceReport:
    piece: PieceFact
    attacked_squares: tuple[int, ...]
    defended_pieces: tuple[PieceFact, ...]
    attacked_pieces: tuple[PieceFact, ...]
    attackers: tuple[PieceFact, ...]
    defenders: tuple[PieceFact, ...]
    absolute_pin: bool
    king_square: int | None
    pin_line: tuple[int, ...]
    legal_moves: tuple[MoveFact, ...] | None
    legal_destinations: tuple[int, ...] | None


@dataclass(frozen=True)
class InspectionReport:
    fen: str
    turn: bool
    square: SquareReport
    piece: PieceReport | None


def inspect_position(position: chess.Board, square: int) -> InspectionReport:
    """Inspect the displayed board without changing it or discarding its history."""
    if square not in chess.SQUARES:
        raise ValueError("Square must be between 0 and 63.")
    board = position.copy(stack=True)

    def pieces(squares: Iterable[int]) -> tuple[PieceFact, ...]:
        return tuple(PieceFact(s, p.color, p.piece_type) for s in sorted(squares)
                     if (p := board.piece_at(s)) is not None)

    legal = tuple(MoveFact(m.uci(), board.san(m), m.from_square, m.to_square, m.promotion)
                  for m in sorted(board.legal_moves, key=lambda m: m.uci()))
    occupant = next(iter(pieces([square])), None)
    white = pieces(board.attackers(chess.WHITE, square))
    black = pieces(board.attackers(chess.BLACK, square))
    defenders = (white if occupant.color else black) if occupant else ()
    opponents = (black if occupant.color else white) if occupant else ()
    square_report = SquareReport(square, occupant, white, black, bool(white and black),
                                 tuple(m for m in legal if m.to_square == square), defenders, opponents)
    piece_report = None
    if occupant:
        attacks = tuple(board.attacks(square))
        targets = pieces(attacks)
        moves = tuple(m for m in legal if m.from_square == square) if occupant.color == board.turn else None
        pinned = board.is_pinned(occupant.color, square)
        piece_report = PieceReport(
            occupant, attacks,
            tuple(p for p in targets if p.color == occupant.color),
            tuple(p for p in targets if p.color != occupant.color),
            opponents, defenders, pinned, board.king(occupant.color),
            tuple(board.pin(occupant.color, square)) if pinned else (),
            moves, tuple(sorted({m.to_square for m in moves})) if moves is not None else None,
        )
    return InspectionReport(board.fen(), board.turn, square_report, piece_report)
