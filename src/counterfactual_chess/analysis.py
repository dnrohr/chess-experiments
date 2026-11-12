"""Qt-independent, cancellable UCI service on a dedicated asyncio thread."""
from __future__ import annotations

import asyncio
import os
import subprocess
from concurrent.futures import Future
from dataclasses import dataclass, replace
from threading import Thread
import time
from typing import TYPE_CHECKING, Callable

import chess
import chess.engine

from .settings import Settings

if TYPE_CHECKING:
    from .comparisons import ComparisonEvent, ComparisonRequest


@dataclass(frozen=True)
class AnalysisRequest:
    request_id: int
    board: chess.Board
    settings: Settings

    def __post_init__(self) -> None:
        object.__setattr__(self, "board", self.board.copy(stack=True))


@dataclass(frozen=True)
class AnalysisResult:
    request_id: int
    starting_fen: str
    centipawns: int | None
    mate: int | None
    pv: tuple[str, ...]
    engine_name: str
    elapsed: float
    depth: int | None
    settings: Settings
    perspective: str = "White"
    terminal: str | None = None
    bound: str | None = None

    @property
    def score_text(self) -> str:
        if self.terminal:
            return self.terminal
        if self.mate is not None:
            return f"{'White' if self.mate > 0 else 'Black'} mates in {abs(self.mate)}" + (f" ({self.bound} bound)" if self.bound else "")
        if self.centipawns is None:
            return "No score reported"
        return f"{self.centipawns / 100:+.2f}" + (f" ({self.bound} bound)" if self.bound else "")

    def san(self) -> str:
        board = chess.Board(self.starting_fen)
        return board.variation_san([chess.Move.from_uci(move) for move in self.pv])


@dataclass(frozen=True)
class AnalysisEvent:
    request_id: int
    kind: str
    result: AnalysisResult | None = None
    message: str = ""


def result_from_info(request: AnalysisRequest, info: chess.engine.InfoDict,
                     name: str, elapsed: float) -> AnalysisResult:
    score = info.get("score")
    white = score.white() if score is not None else None
    pv = tuple(move.uci() for move in info.get("pv", []))
    bound = "lower" if info.get("lowerbound") else "upper" if info.get("upperbound") else None
    if bound and request.board.turn == chess.BLACK:
        bound = "upper" if bound == "lower" else "lower"
    result = AnalysisResult(
        request.request_id, request.board.fen(),
        white.score() if white is not None and not white.is_mate() else None,
        white.mate() if white is not None and white.is_mate() else None,
        pv, name, elapsed, info.get("depth"), request.settings,
        bound=bound,
    )
    # Validate every PV against its starting position before publishing it.
    result.san()
    return result


class AnalysisService:
    def __init__(self, callback: Callable[[AnalysisEvent | ComparisonEvent], None], timeout_grace: float = 5) -> None:
        self.callback = callback
        self.timeout_grace = timeout_grace
        self.loop = asyncio.new_event_loop()
        self.thread = Thread(target=self._run_loop, name="chess-engine", daemon=True)
        self.engine: chess.engine.UciProtocol | None = None
        self.transport: asyncio.SubprocessTransport | None = None
        self.command: str | tuple[str, ...] | None = None
        self.future: Future | None = None
        self.closed = False
        self.thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.lock = asyncio.Lock()
        self.loop.run_forever()
        self.loop.close()

    def submit(self, request: AnalysisRequest, command: str | list[str] | None = None) -> None:
        if self.closed:
            raise RuntimeError("Analysis service is closed.")
        self.cancel()
        # Another copy protects the submitted snapshot from caller mutation.
        snapshot = AnalysisRequest(request.request_id, request.board, request.settings)
        self.future = asyncio.run_coroutine_threadsafe(self._analyze(snapshot, command), self.loop)

    def cancel(self) -> None:
        if self.future and not self.future.done():
            self.future.cancel()

    def submit_comparison(self, request: ComparisonRequest, command: str | list[str] | None = None) -> None:
        from .comparisons import ComparisonRequest
        if self.closed:
            raise RuntimeError("Analysis service is closed.")
        self.cancel()
        copied = ComparisonRequest(request.request_id, request.board, request.selected_square, request.settings, request.limits)
        self.future = asyncio.run_coroutine_threadsafe(self._compare(copied, command), self.loop)

    async def _collect(self, request: AnalysisRequest, seconds: float, *,
                       root_move: str | None = None, multipv: int = 1) -> tuple[AnalysisResult, ...]:
        """Keep the deepest complete exact PV per rank, or its latest bounded PV."""
        assert self.engine is not None
        started = time.monotonic()
        exact: dict[int, AnalysisResult] = {}
        bounded: dict[int, AnalysisResult] = {}
        settings = replace(request.settings, seconds=seconds)
        scored_request = AnalysisRequest(request.request_id, request.board, settings)
        analysis = await self.engine.analysis(
            request.board, chess.engine.Limit(time=seconds), multipv=multipv,
            root_moves=[chess.Move.from_uci(root_move)] if root_move else None,
            game=object(),
        )
        with analysis:
            async for info in analysis:
                if "score" not in info or not info.get("pv"):
                    continue
                rank = info.get("multipv", 1)
                if not 1 <= rank <= multipv:
                    continue
                result = result_from_info(scored_request, info, self.engine.id.get("name", "Unknown UCI engine"), time.monotonic() - started)
                if root_move and result.pv[0] != root_move:
                    raise ValueError("Engine ignored the restricted root move; comparison aborted.")
                if result.bound:
                    bounded[rank] = result
                elif rank not in exact or (result.depth or 0) >= (exact[rank].depth or 0):
                    exact[rank] = result
        elapsed = time.monotonic() - started
        results = tuple(replace(exact.get(rank, bounded.get(rank)), elapsed=elapsed)
                        for rank in sorted(exact.keys() | bounded.keys()))
        if not results:
            raise ValueError("Engine finished without a scored principal variation.")
        return results

    async def _compare(self, request: ComparisonRequest, command: str | list[str] | None) -> None:
        from .comparisons import (BranchResult, ComparisonEvent, ComparisonResult,
                                  feature_differences, generate_candidates)
        from .features import PieceFact

        root = request.board.root()
        selected_piece = request.board.piece_at(request.selected_square)
        batch = ComparisonResult(request.request_id, request.board.fen(), root.fen(),
                                 tuple(m.uci() for m in request.board.move_stack), request.selected_square,
                                 PieceFact(request.selected_square, selected_piece.color, selected_piece.piece_type) if selected_piece else None,
                                 request.settings, request.limits)

        def emit(kind: str) -> None:
            self.callback(ComparisonEvent(request.request_id, kind, batch))

        try:
            async with self.lock:
                try:
                    request.settings.validate()
                    if not request.board.is_valid():
                        raise ValueError("Cannot compare an invalid position.")
                    outcome = request.board.outcome()
                    if outcome:
                        batch = replace(batch, status="complete", message=f"Terminal position: {outcome.result()} — {outcome.termination.name.lower()}. No search needed.")
                        emit("complete")
                        return
                    emit("progress")
                    selected = command or request.settings.engine_path
                    if not selected:
                        raise ValueError("Choose a local Stockfish executable in Engine settings.")
                    await asyncio.wait_for(self._connect(selected), self.timeout_grace)
                    assert self.engine is not None
                    await asyncio.wait_for(self._configure_resources(request.settings), self.timeout_grace)
                    count = request.board.legal_moves.count()
                    option = self.engine.options.get("MultiPV")
                    if option is None or (count > 1 and (option.max or 1) < 2):
                        raise ValueError("Engine does not support MultiPV comparisons. Select a Stockfish build with MultiPV support.")
                    multipv = min(3, count, option.max or 3)
                    analysis_request = AnalysisRequest(request.request_id, request.board, request.settings)
                    # Use separate game tokens to clear search state for equal branch treatment.
                    if "Clear Hash" in self.engine.options:
                        await asyncio.wait_for(self.engine.configure({"Clear Hash": None}), self.timeout_grace)
                    discovery = await asyncio.wait_for(self._collect(analysis_request, request.limits.discovery_seconds, multipv=multipv),
                                                       request.limits.discovery_seconds + self.timeout_grace)
                    candidates = generate_candidates(request.board, request.selected_square,
                                                     tuple(result.pv[0] for result in discovery), request.limits.max_candidates)
                    batch = replace(batch, candidates=candidates, engine_name=self.engine.id.get("name", "Unknown UCI engine"))
                    for index, candidate in enumerate(candidates):
                        batch = replace(batch, message=f"Analyzing branch {index + 1}/{len(candidates)}: {candidate.san}")
                        emit("progress")
                        if "Clear Hash" in self.engine.options:
                            await asyncio.wait_for(self.engine.configure({"Clear Hash": None}), self.timeout_grace)
                        results = await asyncio.wait_for(self._collect(analysis_request, request.limits.branch_seconds, root_move=candidate.uci),
                                                         request.limits.branch_seconds + self.timeout_grace)
                        result = results[0]
                        branch = BranchResult(candidate, result, feature_differences(request.board, request.selected_square, result.pv),
                                              "bounded score" if result.bound else "completed, time-limited")
                        batch = replace(batch, branches=(*batch.branches, branch))
                        emit("branch")
                    batch = replace(batch, status="complete", message=("Only one legal move; no alternative to compare." if count == 1 else
                                    f"Completed {len(batch.branches)} time-limited branches. Differences are not causal explanations."))
                    emit("complete")
                except BaseException:
                    await self._dispose()
                    raise
        except asyncio.CancelledError:
            batch = replace(batch, status="incomplete", message="Comparison cancelled. Completed branches are preserved.")
            emit("cancelled")
        except Exception as exc:
            message = "Engine timed out." if isinstance(exc, TimeoutError) else str(exc) or type(exc).__name__
            batch = replace(batch, status="incomplete", message=f"Comparison failed: {message}")
            emit("error")

    async def _configure_resources(self, settings: Settings) -> None:
        assert self.engine is not None
        options = {"Threads": settings.threads, "Hash": settings.hash_mb}
        for name, value in options.items():
            option = self.engine.options.get(name)
            if option is None:
                raise ValueError(f"Engine does not support {name}.")
            option.parse(value)
        await self.engine.configure(options)

    async def _dispose(self) -> None:
        engine, transport = self.engine, self.transport
        self.engine = self.transport = self.command = None
        if engine:
            try:
                await asyncio.wait_for(engine.quit(), 1.0)
            except Exception:
                pass
        if transport:
            transport.close()
            try:
                await asyncio.wait_for(engine.returncode, 1.0)
            except Exception:
                pass

    async def _connect(self, command: str | list[str]) -> None:
        key = tuple(command) if isinstance(command, list) else command
        if self.engine and self.command == key and not self.engine.returncode.done():
            return
        await self._dispose()
        # Own the transport before initialization so a handshake timeout cannot leak it.
        self.transport, self.engine = await self.loop.subprocess_exec(chess.engine.UciProtocol, *(
            command if isinstance(command, list) else [command]
        ), **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        await asyncio.wait_for(self.engine.initialize(), self.timeout_grace)
        self.command = key

    async def _analyze(self, request: AnalysisRequest, command: str | list[str] | None) -> None:
        try:
            async with self.lock:
                try:
                    await asyncio.wait_for(self._search(request, command), request.settings.seconds + self.timeout_grace)
                except BaseException:
                    # Reset after interruption, including engines ignoring UCI stop.
                    await self._dispose()
                    raise
        except asyncio.CancelledError:
            self.callback(AnalysisEvent(request.request_id, "cancelled"))
        except Exception as exc:
            message = "Engine timed out." if isinstance(exc, TimeoutError) else str(exc)
            self.callback(AnalysisEvent(request.request_id, "error", message=message or type(exc).__name__))

    async def _search(self, request: AnalysisRequest, command: str | list[str] | None) -> None:
        request.settings.validate()
        if not request.board.is_valid():
            raise ValueError("Cannot analyze an invalid position.")
        outcome = request.board.outcome()
        if outcome:
            result = AnalysisResult(request.request_id, request.board.fen(), None, None, (),
                                    "Rules", 0, None, request.settings,
                                    terminal=f"{outcome.result()} — {outcome.termination.name.replace('_', ' ').lower()}")
            self.callback(AnalysisEvent(request.request_id, "complete", result))
            return
        selected = command or request.settings.engine_path
        if not selected:
            raise ValueError("Choose a local Stockfish executable in Engine settings.")
        await self._connect(selected)
        assert self.engine is not None
        await self._configure_resources(request.settings)
        started = time.monotonic()
        analysis = await self.engine.analysis(request.board, chess.engine.Limit(time=request.settings.seconds))
        latest = None
        with analysis:
            async for info in analysis:
                if "score" in info and "pv" in info:
                    latest = result_from_info(request, info, self.engine.id.get("name", "Unknown UCI engine"), time.monotonic() - started)
                    self.callback(AnalysisEvent(request.request_id, "update", latest))
        if latest is None:
            raise ValueError("Engine finished without a scored principal variation.")
        self.callback(AnalysisEvent(request.request_id, "complete", latest))

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.cancel()

        async def shutdown() -> None:
            async with self.lock:
                await self._dispose()

        future = asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
        try:
            future.result(timeout=5)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=3)
