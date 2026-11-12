"""Legal position editing and non-destructive PGN navigation."""
from __future__ import annotations

import io
import chess
import chess.pgn


class PositionManager:
    def __init__(self) -> None:
        self.board = chess.Board()
        self.games: list[chess.pgn.Game] = []
        self.game_index = 0
        self.ply = 0
        self.continuation = False

    def load_fen(self, fen: str) -> None:
        board = chess.Board(fen)
        if not board.is_valid():
            raise ValueError("Invalid chess position (kings, pawns, checks or castling rights).")
        self.board = board
        self.games = []
        self.ply = 0
        self.continuation = False

    def load_pgn(self, text: str) -> None:
        stream = io.StringIO(text)
        games = []
        while (game := chess.pgn.read_game(stream)) is not None:
            if game.errors:
                raise ValueError(f"Malformed PGN: {game.errors[0]}")
            if game.headers.get("Variant", "Standard").lower() not in ("standard", "chess", "normal"):
                raise ValueError("Only standard chess PGNs are supported.")
            board = game.board()
            if not board.is_valid():
                raise ValueError("PGN has an invalid starting position.")
            for move in game.mainline_moves():
                if move not in board.legal_moves:
                    raise ValueError("PGN contains an illegal move.")
                board.push(move)
            games.append(game)
        if not games:
            raise ValueError("No PGN games found.")
        self.games = games
        self.select_game(0)

    def select_game(self, index: int) -> None:
        if not 0 <= index < len(self.games):
            raise ValueError("Unknown game.")
        self.game_index = index
        self.navigate(0)

    @property
    def length(self) -> int:
        return len(list(self.games[self.game_index].mainline_moves())) if self.games else 0

    def navigate(self, ply: int) -> None:
        if not self.games:
            return
        self.ply = max(0, min(ply, self.length))
        board = self.games[self.game_index].board()
        for move in list(self.games[self.game_index].mainline_moves())[:self.ply]:
            board.push(move)
        self.board = board
        self.continuation = False

    def play(self, move: chess.Move) -> None:
        if move not in self.board.legal_moves:
            raise ValueError("Illegal move.")
        self.board.push(move)
        self.continuation = bool(self.games)
