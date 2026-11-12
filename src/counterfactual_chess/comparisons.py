"""Legal candidate generation and immutable comparison evidence, independent of Qt."""
from __future__ import annotations

from dataclasses import dataclass, field

import chess

from .analysis import AnalysisResult
from .features import InspectionReport, PieceFact, inspect_position
from .settings import Settings


@dataclass(frozen=True)
class ComparisonLimits:
    discovery_seconds: float = 1.0
    branch_seconds: float = 1.0
    max_candidates: int = 4

    def validate(self) -> None:
        if not 0.01 <= self.discovery_seconds <= 10 or not 0.01 <= self.branch_seconds <= 10:
            raise ValueError("Comparison searches must be between 0.01 and 10 seconds.")
        if not 1 <= self.max_candidates <= 4:
            raise ValueError("Comparisons support at most four branches.")


@dataclass(frozen=True)
class ComparisonRequest:
    request_id: int
    board: chess.Board
    selected_square: int
    settings: Settings
    limits: ComparisonLimits = field(default_factory=ComparisonLimits)

    def __post_init__(self) -> None:
        object.__setattr__(self, "board", self.board.copy(stack=True))
        if self.selected_square not in chess.SQUARES:
            raise ValueError("Select a valid square.")
        self.limits.validate()


@dataclass(frozen=True)
class Candidate:
    uci: str
    san: str
    reasons: tuple[str, ...]
    discovery_rank: int | None
    reference: bool = False


@dataclass(frozen=True)
class FeatureSnapshot:
    prefix: tuple[str, ...]
    fen: str
    square_report: InspectionReport
    tracked_piece: PieceFact | None
    piece_report: InspectionReport | None
    selected_piece_captured: bool
    terminal: str | None


@dataclass(frozen=True)
class FeatureDifference:
    before: FeatureSnapshot
    after: FeatureSnapshot
    white_control_change: int
    black_control_change: int
    piece_attack_change: int | None
    piece_attacker_change: int | None
    piece_defender_change: int | None
    mobility_change: int | None


@dataclass(frozen=True)
class BranchResult:
    candidate: Candidate
    analysis: AnalysisResult
    differences: tuple[FeatureDifference, ...]
    status: str


@dataclass(frozen=True)
class ComparisonResult:
    request_id: int
    starting_fen: str
    root_fen: str
    history: tuple[str, ...]
    selected_square: int
    selected_piece: PieceFact | None
    settings: Settings
    limits: ComparisonLimits
    candidates: tuple[Candidate, ...] = ()
    branches: tuple[BranchResult, ...] = ()
    engine_name: str = ""
    status: str = "running"
    message: str = "Discovering engine alternatives…"


@dataclass(frozen=True)
class ComparisonEvent:
    request_id: int
    kind: str
    batch: ComparisonResult


CATEGORIES = (
    "Selection-related capture", "Decreased friendly control", "Increased friendly control",
    "Selected-piece relocation", "Possible pawn-break candidate — requires evaluation",
    "Discovery alternative",
)


def captured_square(board: chess.Board, move: chess.Move) -> int | None:
    if not board.is_capture(move):
        return None
    if board.is_en_passant(move):
        return move.to_square - 8 if board.turn else move.to_square + 8
    return move.to_square


def generate_candidates(board: chess.Board, selected: int, discovery: tuple[str, ...],
                        maximum: int = 4) -> tuple[Candidate, ...]:
    """One candidate per priority category, then fill unused slots in category order."""
    if not 1 <= maximum <= 4:
        raise ValueError("At most four candidates are allowed.")
    legal = {m.uci(): m for m in board.legal_moves}
    ranked = tuple(dict.fromkeys(uci for uci in discovery if uci in legal))
    if not ranked:
        raise ValueError("Discovery returned no legal preferred move.")
    piece = board.piece_at(selected)
    friendly = piece.color if piece else board.turn
    control = len(board.attackers(friendly, selected))
    rank = {uci: index + 1 for index, uci in enumerate(ranked)}
    candidates = []
    for uci, move in sorted(legal.items()):
        after = board.copy(stack=True)
        is_capture = board.is_capture(move)
        related_capture = is_capture and (move.from_square == selected or captured_square(board, move) == selected)
        is_push = board.piece_type_at(move.from_square) == chess.PAWN and not is_capture
        before_contacts = set(board.attacks(move.from_square)) & set(board.pieces(chess.PAWN, not board.turn)) if is_push else set()
        after.push(move)
        difference = len(after.attackers(friendly, selected)) - control
        after_contacts = set(after.attacks(move.to_square)) & set(after.pieces(chess.PAWN, not board.turn)) if is_push else set()
        flags = (related_capture, difference < 0, difference > 0,
                 piece is not None and move.from_square == selected,
                 is_push and (difference != 0 or bool(after_contacts - before_contacts)), uci in rank)
        reasons = tuple(category for category, included in zip(CATEGORIES, flags) if included)
        if uci == ranked[0]:
            reasons = ("Discovery-preferred reference", *(reason for reason in reasons if reason != CATEGORIES[-1]))
        if reasons:
            candidates.append(Candidate(uci, board.san(move), reasons, rank.get(uci), uci == ranked[0]))
    ordered = sorted(candidates, key=lambda c: (c.discovery_rank or 10_000, c.uci))
    chosen = [next(c for c in ordered if c.reference)]
    # Visit every category once before revisiting it: preserve diversity within the cap.
    for category in CATEGORIES:
        if len(chosen) >= maximum:
            break
        match = next((c for c in ordered if category in c.reasons and c not in chosen), None)
        if match:
            chosen.append(match)
    for category in CATEGORIES:
        for candidate in ordered:
            if len(chosen) >= maximum:
                return tuple(chosen)
            if category in candidate.reasons and candidate not in chosen:
                chosen.append(candidate)
    return tuple(chosen)


def snapshot(board: chess.Board, selected: int, prefix: tuple[str, ...]) -> FeatureSnapshot:
    work = board.copy(stack=True)
    original_piece = board.piece_at(selected)
    location = selected if original_piece else None
    for uci in prefix:
        move = chess.Move.from_uci(uci)
        if move not in work.legal_moves:
            raise ValueError(f"Illegal evidence move: {uci}")
        if location is not None:
            if captured_square(work, move) == location:
                location = None
            elif move.from_square == location:
                location = move.to_square
            elif work.is_castling(move) and original_piece.piece_type == chess.ROOK:
                # A selected rook also moves when its own king castles.
                rank = 0 if work.turn else 7
                rook_from = chess.square(7 if work.is_kingside_castling(move) else 0, rank)
                if location == rook_from:
                    location = chess.square(5 if work.is_kingside_castling(move) else 3, rank)
        work.push(move)
    tracked = work.piece_at(location) if location is not None else None
    piece = PieceFact(location, tracked.color, tracked.piece_type) if tracked else None
    outcome = work.outcome()
    return FeatureSnapshot(prefix, work.fen(), inspect_position(work, selected), piece,
                           inspect_position(work, location) if tracked else None,
                           original_piece is not None and location is None,
                           f"{outcome.result()} — {outcome.termination.name.lower()}" if outcome else None)


def exchange_prefix(board: chess.Board, selected: int, pv: tuple[str, ...]) -> tuple[str, ...] | None:
    """Find a consecutive capture/recapture involving the selected piece or square."""
    work = board.copy(stack=True)
    original_piece = work.piece_at(selected)
    location = selected if work.piece_at(selected) else None
    last_capture: tuple[int, bool] | None = None
    for index, uci in enumerate(pv[:4]):
        move = chess.Move.from_uci(uci)
        if move not in work.legal_moves:
            raise ValueError("Illegal PV in exchange evidence.")
        victim = captured_square(work, move)
        related = move.from_square == location or victim == location or move.to_square == selected
        if victim is not None and last_capture and victim == last_capture[0] and (related or last_capture[1]):
            return pv[:index + 1]
        last_capture = (move.to_square, related) if victim is not None else None
        if victim == location:
            location = None
        elif location == move.from_square:
            location = move.to_square
        elif location is not None and work.is_castling(move) and original_piece.piece_type == chess.ROOK:
            rank = 0 if work.turn else 7
            if location == chess.square(7 if work.is_kingside_castling(move) else 0, rank):
                location = chess.square(5 if work.is_kingside_castling(move) else 3, rank)
        work.push(move)
    return None


def feature_differences(board: chess.Board, selected: int, pv: tuple[str, ...]) -> tuple[FeatureDifference, ...]:
    if not pv:
        return ()
    before = snapshot(board, selected, ())
    prefixes = [pv[:1]]
    exchange = exchange_prefix(board, selected, pv)
    if exchange and exchange not in prefixes:
        prefixes.append(exchange)
    differences = []
    for prefix in prefixes:
        after = snapshot(board, selected, prefix)
        old_piece = before.piece_report.piece if before.piece_report else None
        new_piece = after.piece_report.piece if after.piece_report else None
        comparable = old_piece is not None and new_piece is not None
        mobility = (len(new_piece.legal_destinations) - len(old_piece.legal_destinations)
                    if comparable and old_piece.legal_destinations is not None and new_piece.legal_destinations is not None else None)
        differences.append(FeatureDifference(
            before, after,
            len(after.square_report.square.white_attackers) - len(before.square_report.square.white_attackers),
            len(after.square_report.square.black_attackers) - len(before.square_report.square.black_attackers),
            len(new_piece.attacked_squares) - len(old_piece.attacked_squares) if comparable else None,
            len(new_piece.attackers) - len(old_piece.attackers) if comparable else None,
            len(new_piece.defenders) - len(old_piece.defenders) if comparable else None,
            mobility,
        ))
    return tuple(differences)


def score_difference(branch: BranchResult, reference: BranchResult | None) -> int | None:
    if reference is None:
        return None
    a, b = branch.analysis, reference.analysis
    if a.bound or b.bound or a.mate is not None or b.mate is not None or a.terminal or b.terminal:
        return None
    return a.centipawns - b.centipawns if a.centipawns is not None and b.centipawns is not None else None
