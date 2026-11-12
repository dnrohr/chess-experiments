"""Deterministic factual claims, each tied to inspectable board evidence."""
from __future__ import annotations

from dataclasses import dataclass

import chess

from .features import InspectionReport, MoveFact, PieceFact


@dataclass(frozen=True)
class Evidence:
    identifier: str
    fen: str
    squares: tuple[int, ...]
    pieces: tuple[PieceFact, ...]
    moves: tuple[MoveFact, ...]
    basis: str


@dataclass(frozen=True)
class Statement:
    text: str
    evidence_id: str


@dataclass(frozen=True)
class Explanation:
    summary: tuple[Statement, ...]
    statements: tuple[Statement, ...]
    evidence: tuple[Evidence, ...]


def explain(report: InspectionReport) -> Explanation:
    square = report.square
    name = chess.square_name(square.square)
    evidence: list[Evidence] = []
    statements: list[Statement] = []
    summary: list[Statement] = []

    def counted(number: int, noun: str) -> str:
        return f"{number} {noun}{'' if number == 1 else 's'}"

    def add(key: str, text: str, *, squares: tuple[int, ...] = (),
            pieces: tuple[PieceFact, ...] = (), moves: tuple[MoveFact, ...] = (),
            basis: str, brief: bool = False) -> None:
        locations = tuple(sorted({square.square, *squares, *(p.square for p in pieces),
                                  *(m.from_square for m in moves), *(m.to_square for m in moves)}))
        evidence.append(Evidence(key, report.fen, locations, pieces, moves, basis))
        claim = Statement(text, key)
        statements.append(claim)
        if brief:
            summary.append(claim)

    add("occupancy", f"{name} is empty." if square.occupant is None else f"{square.occupant.label}.",
        pieces=(square.occupant,) if square.occupant else (), basis="Piece placement in the displayed position.", brief=True)
    for color, attackers in (("White", square.white_attackers), ("Black", square.black_attackers)):
        add(f"{color.lower()}_attackers", f"{color} geometrically attacks {name} with {counted(len(attackers), 'piece')}.",
            pieces=attackers, basis="Geometric attackers of the selected square, including pinned pieces.", brief=True)
    add("contested", f"{name} is geometrically contested: both colors attack it." if square.contested else
        f"{name} is not geometrically contested: at most one color attacks it.",
        pieces=square.white_attackers + square.black_attackers,
        basis="Contested means at least one geometric attacker from each color; it is not a value judgment.")
    color = "White" if report.turn else "Black"
    add("legal_to", f"Legal moves by {color} reaching {name} on this turn: {len(square.legal_moves_to)}.",
        moves=square.legal_moves_to, basis="Current side-to-move legal moves filtered by destination, including promotions and castling.")
    piece = report.piece
    if piece:
        add("defenders", f"Friendly pieces geometrically defending the selected piece: {len(piece.defenders)}.",
            pieces=piece.defenders, basis="Same-color geometric attackers of the occupied square; defense does not guarantee a safe recapture.")
        add("opponents", f"Opposing pieces geometrically attacking the selected piece: {len(piece.attackers)}.",
            pieces=piece.attackers, basis="Opposite-color geometric attackers of the occupied square.")
        add("attacks", f"The selected piece geometrically attacks {counted(len(piece.attacked_squares), 'square')}.",
            squares=piece.attacked_squares, pieces=(piece.piece,), basis="Attacks from this piece, blocked by the first occupied square on sliding rays.")
        add("defended_pieces", f"The selected piece geometrically defends {counted(len(piece.defended_pieces), 'friendly piece')}.",
            pieces=piece.defended_pieces, basis="Friendly occupied squares within this piece's geometric attacks.")
        add("attacked_pieces", f"The selected piece geometrically attacks {counted(len(piece.attacked_pieces), 'opposing piece')}.",
            pieces=piece.attacked_pieces, basis="Enemy occupied squares within this piece's geometric attacks; these are not necessarily legal captures.")
        add("pin", "The selected piece is absolutely pinned to its king." if piece.absolute_pin else
            "The selected piece is not absolutely pinned to its king.",
            squares=tuple(sorted({*(piece.pin_line), *([piece.king_square] if piece.king_square is not None else [])})),
            pieces=(piece.piece,), basis="Absolute pin detection against this piece's own king; relative pins are not assessed.")
        if piece.legal_moves is None:
            add("mobility", "Legal mobility unavailable: this side is not to move", pieces=(piece.piece,),
                basis=f"{color} is the side to move in this FEN. No hypothetical turn change is made.", brief=True)
        else:
            add("mobility", f"Legal mobility: {counted(len(piece.legal_destinations), 'distinct destination square')}, {counted(len(piece.legal_moves), 'legal move')}.",
                moves=piece.legal_moves, basis="Legal moves of this piece on this turn. Promotion choices share one destination.", brief=True)
            promotions = tuple(m for m in piece.legal_moves if m.promotion is not None)
            if promotions:
                choices = "; ".join(f"{chess.square_name(destination)}: " + ", ".join(
                    chess.piece_name(kind) for kind in sorted({m.promotion for m in promotions if m.to_square == destination}))
                    for destination in sorted({m.to_square for m in promotions}))
                add("promotions", f"Legal promotion choices — {choices}.", moves=promotions,
                    basis="Every listed promotion is a legal move in the displayed position.")
        if piece.piece.piece_type == chess.PAWN:
            add("pawn_rule", "Pawn attacks run diagonally; pawn pushes are separate legal moves.",
                squares=piece.attacked_squares, pieces=(piece.piece,), moves=piece.legal_moves or (),
                basis="Standard pawn attack geometry and current-turn legal pawn moves.")
    add("limits", "Geometric attacks include pinned pieces. Attack counts alone do not establish strategic importance.",
        pieces=square.white_attackers + square.black_attackers,
        basis="These reports describe geometric relationships and current-turn legality, not strategic value or engine conclusions.")
    return Explanation(tuple(summary), tuple(statements), tuple(evidence))
