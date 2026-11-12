import os
from pathlib import Path
import queue
import sys
import time

import chess
import chess.engine
import pytest

from counterfactual_chess.analysis import AnalysisRequest, AnalysisService, result_from_info
from counterfactual_chess.settings import Settings


FAKE = str(Path(__file__).with_name("fake_uci.py"))


def wait_event(events, kind, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = events.get(timeout=max(.01, deadline - time.monotonic()))
        if event.kind == kind:
            return event
    raise AssertionError(f"No {kind} event")


def test_scores_snapshot_and_san():
    board = chess.Board()
    board.push_uci("e2e4")
    request = AnalysisRequest(1, board, Settings())
    board.push_uci("e7e5")
    assert len(request.board.move_stack) == 1
    info = {"score": chess.engine.PovScore(chess.engine.Cp(42), chess.BLACK), "pv": [chess.Move.from_uci("e7e5")]}
    result = result_from_info(request, info, "test", .1)
    assert result.centipawns == -42 and result.mate is None
    assert "e5" in result.san()
    info["score"] = chess.engine.PovScore(chess.engine.Mate(3), chess.BLACK)
    result = result_from_info(request, info, "test", .1)
    assert result.mate == -3 and result.centipawns is None
    assert result.score_text == "Black mates in 3"
    info["score"] = chess.engine.PovScore(chess.engine.Cp(42), chess.BLACK)
    info["lowerbound"] = True
    assert result_from_info(request, info, "test", .1).bound == "upper"
    info["pv"] = [chess.Move.from_uci("e7e4")]
    with pytest.raises((ValueError, AssertionError)):
        result_from_info(request, info, "test", .1)


@pytest.mark.parametrize("mode", ["normal", "mate"])
def test_real_uci_protocol_and_reuse(mode):
    events = queue.Queue()
    service = AnalysisService(events.put)
    try:
        for index in (1, 2):
            board = chess.Board()
            board.push_uci("e2e4")
            service.submit(AnalysisRequest(index, board, Settings()), [sys.executable, FAKE, mode])
            event = wait_event(events, "complete")
            assert event.result.request_id == index
            assert event.result.engine_name == "Fake UCI test engine"
            assert event.result.san()
            assert event.result.centipawns == -42 if mode == "normal" else event.result.mate == -3
            if index == 1:
                pid = service.transport.get_pid()
            else:
                assert service.transport.get_pid() == pid
    finally:
        service.close()
    assert not service.thread.is_alive()


def test_cancel_and_restart():
    events = queue.Queue()
    service = AnalysisService(events.put)
    try:
        service.submit(AnalysisRequest(1, chess.Board(), Settings(seconds=10)), [sys.executable, FAKE, "slow"])
        wait_event(events, "update")
        service.cancel()
        wait_event(events, "cancelled")
        service.submit(AnalysisRequest(2, chess.Board(), Settings()), [sys.executable, FAKE])
        assert wait_event(events, "complete").request_id == 2
    finally:
        service.close()


def test_shutdown_during_active_search():
    events = queue.Queue()
    service = AnalysisService(events.put)
    service.submit(AnalysisRequest(1, chess.Board(), Settings(seconds=10)), [sys.executable, FAKE, "slow"])
    wait_event(events, "update")
    engine = service.engine
    service.close()
    assert engine.returncode.done()
    assert not service.thread.is_alive()


@pytest.mark.parametrize("mode", ["crash", "hang", "handshake"])
def test_failure_timeout_cleanup(mode):
    events = queue.Queue()
    service = AnalysisService(events.put, timeout_grace=.5)
    try:
        service.submit(AnalysisRequest(1, chess.Board(), Settings(seconds=.1)), [sys.executable, FAKE, mode])
        event = wait_event(events, "error")
        assert event.message
        assert service.transport is None
    finally:
        service.close()


def test_invalid_capability_and_missing_engine():
    events = queue.Queue()
    service = AnalysisService(events.put)
    try:
        service.submit(AnalysisRequest(1, chess.Board(), Settings()))
        assert "Choose" in wait_event(events, "error").message
        service.submit(AnalysisRequest(2, chess.Board(), Settings(threads=5)), [sys.executable, FAKE])
        assert "Threads" in wait_event(events, "error").message
        service.submit(AnalysisRequest(3, chess.Board(), Settings(engine_path="does-not-exist.exe")))
        assert wait_event(events, "error").request_id == 3
    finally:
        service.close()


@pytest.mark.parametrize("fen", ["7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", "7k/5K2/6Q1/8/8/8/8/8 b - - 0 1"])
def test_terminal_without_engine(fen):
    events = queue.Queue()
    service = AnalysisService(events.put)
    try:
        service.submit(AnalysisRequest(1, chess.Board(fen), Settings()))
        result = wait_event(events, "complete").result
        assert result.terminal and not result.pv
        assert service.engine is None
    finally:
        service.close()


@pytest.mark.integration
def test_stockfish_offline(monkeypatch):
    path = os.environ.get("STOCKFISH_PATH")
    if not path:
        pytest.skip("Set STOCKFISH_PATH for real engine integration")
    # Deny Python networking while keeping local subprocess/pipe operations available.
    import socket
    original_connect = socket.socket.connect
    def guarded_connect(sock, address):
        # Windows asyncio builds its wakeup socket pair over loopback.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original_connect(sock, address)
        raise AssertionError("External network access is forbidden")
    def denied(*args, **kwargs):
        raise AssertionError("Network access is forbidden")
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    events = queue.Queue()
    service = AnalysisService(events.put)
    try:
        service.submit(AnalysisRequest(1, chess.Board(), Settings(engine_path=path, seconds=.2)))
        result = wait_event(events, "complete").result
        assert "Stockfish" in result.engine_name
        assert result.depth > 0 and result.pv and result.centipawns is not None
        result.san()
    finally:
        service.close()
