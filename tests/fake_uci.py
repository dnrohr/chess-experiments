"""Deterministic test-only engine. Never used to demonstrate chess strength."""
import sys
import threading
import time
import chess

mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
board = chess.Board()
stop = threading.Event()
worker = None
multipv = 1
search_count = 0
log_path = sys.argv[2] if len(sys.argv) > 2 else None


def say(text):
    print(text, flush=True)


def search(snapshot, roots, variations, ordinal):
    if mode == "crash" or (mode == "partial_crash" and ordinal == 3):
        import os
        os._exit(2)
    if mode == "hang":
        while True:
            time.sleep(.05)
    legal = list(snapshot.legal_moves)
    choices = [chess.Move.from_uci(uci) for uci in roots] if roots else legal
    if mode == "ignore_root":
        choices = legal
    best = None
    for index, root in enumerate(choices[:variations]):
        work = snapshot.copy(stack=True)
        pv = [root.uci()]
        work.push(root)
        for _ in range(2):
            moves = list(work.legal_moves)
            if not moves:
                break
            move = moves[0]
            pv.append(move.uci())
            work.push(move)
        best = best or root.uci()
        score = "mate 3" if mode == "mate" else f"cp {42 - (legal.index(root) if mode == 'comparison' else 0)}"
        bound = " lowerbound" if mode == "bounded" else ""
        say(f"info depth 8 multipv {index + 1} score {score}{bound} pv {' '.join(pv)}")
        if mode == "deep_exact":
            say(f"info depth 6 multipv {index + 1} score cp 99 pv {' '.join(pv)}")
            say(f"info depth 9 multipv {index + 1} score cp 100 lowerbound pv {' '.join(pv)}")
    stop.wait(10 if mode == "slow" or (mode == "partial_slow" and ordinal >= 3) else .05)
    say(f"bestmove {best or '0000'}")


for raw in sys.stdin:
    line = raw.strip()
    if log_path:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(line + "\n")
    if line == "uci":
        if mode == "handshake":
            continue
        say("id name Fake UCI test engine")
        say("option name Threads type spin default 1 min 1 max 4")
        say("option name Hash type spin default 64 min 1 max 128")
        if mode != "no_multipv":
            say("option name MultiPV type spin default 1 min 1 max 3")
        say("uciok")
    elif line == "isready":
        say("readyok")
    elif line.startswith("setoption name MultiPV value "):
        multipv = int(line.split()[-1])
    elif line.startswith("position "):
        parts = line.split()
        split = parts.index("moves") if "moves" in parts else len(parts)
        board = chess.Board() if parts[1] == "startpos" else chess.Board(" ".join(parts[2:split]))
        for uci in parts[split + 1:]:
            board.push_uci(uci)
    elif line.startswith("go"):
        search_count += 1
        parts = line.split()
        roots = parts[parts.index("searchmoves") + 1:] if "searchmoves" in parts else []
        stop.clear()
        worker = threading.Thread(target=search, args=(board.copy(stack=True), roots, multipv, search_count), daemon=True)
        worker.start()
    elif line == "stop":
        if mode != "hang":
            stop.set()
    elif line == "quit":
        if mode == "hang":
            continue
        stop.set()
        if worker:
            worker.join(timeout=1)
        break
