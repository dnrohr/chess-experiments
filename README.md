# Counterfactual Chess

An offline desktop chess analysis application. Milestone 1 provides a legal
board, FEN/PGN loading, local Stockfish analysis, and replayable principal
variations. Milestone 2 adds square and piece inspection with factual geometric
explanations and board overlays. Milestone 3 compares bounded legal continuations
with engine scores and feature snapshots. Strategic explanation synthesis is a
later milestone.

## Windows setup

Requires Python 3.11 or later (tested with Python 3.12.10) and a local Stockfish
executable. No GPU, accounts, subscriptions, or runtime internet connection.
Installation downloads Python packages; after installation, execution is local.

From this repository in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m counterfactual_chess
```

For runtime-only installation, use `pip install -e .` instead. The application
uses **PySide6 Essentials**, which supplies the required Widgets and SVG modules
without Qt WebEngine or other unused add-ons.

Download and extract an appropriate Windows build from the
[official Stockfish download page](https://stockfishchess.org/download/).
Keep the executable and any required evaluation files together. In the app,
choose **Engine settings → Browse**, select the `.exe`, then save. The application
does not download engines. Only select an engine executable you intend to run.

## Using the application

- Click a piece, then a highlighted legal destination. Promotions open a piece
  chooser. **Flip board** changes orientation; **New position** resets the board.
- Paste a FEN and press Enter or **Load FEN**. Invalid input leaves the current
  position intact. **Copy FEN** copies the displayed board, including PV previews.
- **Open PGN** loads UTF-8 PGNs. Select a game from the dropdown and navigate its
  mainline with the four navigation buttons. Starting-position headers are honored.
- Entering a move during PGN review creates a temporary local continuation.
  Mainline navigation restores the original game. Export and variation-tree
  editing are not included.
- Choose **Analyze** to run the local engine. Defaults: 1 thread, 64 MiB hash,
  1 second. Set up to 256 threads, 4096 MiB, and 120 seconds; the engine's own
  capability ranges are also checked. Default settings are the low-resource mode.
- Scores always use **White's perspective**: positive favors White. Mate scores
  are displayed separately. Terminal positions are resolved from chess rules.
- **PV ▶ / PV ◀** replay the engine line on a temporary board. **Return to
  position** restores the analyzed position. Move entry is disabled in PV preview.
- **Cancel**, changing positions, or changing settings invalidates current
  analysis. Late worker responses cannot overwrite a newer position.
- The evidence panel contains the starting FEN, engine identity/version string,
  achieved depth, elapsed time, resource settings, and UCI move sequence.
  Time-bounded search results can vary across runs and hardware; these records
  support inspection, not guaranteed bit-identical reproduction.

Settings are saved under `%LOCALAPPDATA%\CounterfactualChess\settings.json`.
No analysis cache or network client is included in this milestone.

## Inspecting squares and pieces

Choose **Board mode → Inspect**, then click any empty square or either color's
piece. Inspect mode never enters moves or starts an engine search. **Move** mode
retains normal legal move entry and is the default each session. Switching modes
clears the current selection, while preserving positions and engine results.
The Engine and Inspect tabs share the same position and PGN navigation controls.

The Inspect tab shows a short factual summary, then expandable facts with
evidence identifiers. Expand a fact to inspect its basis, board squares, pieces,
legal SAN/UCI moves, and displayed FEN. Hover over an evidence row to highlight
its board locations. No Stockfish installation is needed for inspection.

- A square report shows occupancy, White/Black geometric attackers, whether both
  colors attack it, and current-turn legal moves reaching it. Occupied squares
  additionally identify friendly defenders and opposing attackers.
- A piece report shows attacked squares, friendly pieces defended, opposing
  pieces attacked, attackers/defenders, and an absolute pin to its own king.
- Mobility counts distinct legal destination squares, with actual legal moves
  in the evidence. Promotion choices count as one destination and are also
  listed explicitly. Opposing pieces display **Legal mobility unavailable: this
  side is not to move**; inspection never changes turns to invent moves.
- Geometric attacks include pinned pieces and friendly occupied squares on
  attack rays. Pawn attacks are diagonal; pawn pushes are separate legal moves.
  A geometric defense does not guarantee a safe recapture. These facts alone
  do not establish strategic importance or justify a piece-strength ranking.

**Show overlays** is on by default: a gold outline marks the selected square;
blue solid and purple dashed relationships distinguish White and Black attacks.
Lines point from attackers to the selected square. Corner marks show the
selected piece's attacked squares; green dots show legal destinations. Orange
outlines identify evidence locations on hover. Turning overlays off preserves
the report. Flipping the board preserves the selection and report.

Inspection remains available during engine analysis and cancellation. Moves,
successful FEN/PGN loads, game changes, and PGN navigation clear it. In PV replay,
reports describe the **displayed preview position**, labeled **PV preview**;
changing replay ply or returning to the original position clears the selection.
These reports never replace the engine's evaluation or PV.

## Comparing legal continuations

In Inspect mode select a square or either color's piece, then choose **Compare
continuations**. The Compare tab shows progress, a branch table, factual changes,
and expandable evidence. This requires your configured local Stockfish executable
with MultiPV support. Normal analysis and comparisons share one engine worker;
starting either stops the previous job.

The default budget is **one second of discovery plus one second for each of up
to four branches**. Expect around six seconds including normal overhead, with
hardware-dependent startup/search overhead. Engine timeouts have an additional
grace period; five seconds is a search-work limit, not a hard wall-clock promise.
Comparison timing is separate from the ordinary analysis-time setting. Threads
and hash memory come from Engine settings. No downloads or new dependencies are
required.

The discovery search requests up to three MultiPV alternatives. Its preferred
move is always the reference. Other slots visit these categories in order, taking
one unused move per category before filling remaining slots in the same order:
selection-related capture, decreased friendly control, increased friendly control,
selected-piece relocation, relevant pawn contact push, and remaining discovery
alternatives. Discovery rank breaks ties before UCI ordering. Identical moves
are deduplicated. There can be fewer than four relevant alternatives. Friendly
control refers to the selected piece's color, or the current side to move for
an empty square. Generated alternatives may be weak; their selection is not an
engine recommendation. A pawn contact push is only a **possible pawn-break
candidate requiring evaluation**.

Every chosen move, including the reference, is searched again from the same
original position with that root move forced and equal time/resource limits.
Each search starts a new engine game and clears hash when supported. These are
continuation scores from a common starting position, **not** independently
evaluated endpoint diagrams. Discovery scores never become branch scores.
Independent re-search can change their ranking, so the discovery reference is
not guaranteed to have the highest score in the finished table.

- All scores use White's perspective. **Δ vs ref** means branch score minus the
  re-searched reference score; positive favors White relative to the reference,
  including when Black is to move. It does not imply causation or significance.
- Numeric differences appear only for two unbounded centipawn scores. Mate scores,
  endpoint outcomes, and bounds remain separate. The deepest complete unbounded
  scored PV is retained; if none exists, the latest valid bounded result is labeled.
- Select a completed table row to see its generation reasons, evidence status,
  and observed changes. Use the Compare tab's **PV ▶ / PV ◀** buttons to replay
  its line, and **Return to position** to restore the unchanged original board.
- Feature snapshots identify the exact prefix and before/after FENs. The first
  snapshot follows the candidate move. A second snapshot appears only when the
  engine PV contains a relevant consecutive capture/recapture in its first four
  plies. No exchange is invented or forced into the PV.
- Square reports always refer to the originally selected square. Piece reports
  follow the original piece through relocation, castling and promotion. Once
  captured it stays marked captured, even if another piece occupies its square.
  Legal-mobility differences are unavailable across opposing turns or after capture.
- Expand search evidence for engine identity, root FEN and full move history,
  resources, requested/elapsed time, depth, root move, and actual SAN/UCI PV.
  Evidence is session-local. Search results can vary by hardware and run.
- **Cancel comparison** preserves only finished branches, marks the batch
  **incomplete**, and leaves completed evidence replayable. A failure does the same.
  Unfinished searches do not produce comparison rows or score differences.
- Changing the position, root inspection selection, engine settings, or starting
  another engine job clears the comparison and cancels pending work. Flipping,
  overlay toggles, and tab changes preserve it. Mode switching clears inspection
  selection and therefore invalidates its comparison in the original position.
- Preview inspection describes the displayed PV position and preserves the
  comparison. Return to the original position and inspect again before requesting
  another comparison. Terminal positions need no search; one-legal-move positions
  report that there is no alternative.

Completed searches are labeled **completed, time-limited** or **bounded score**.
These are evidence statuses, not statistical confidence estimates. Scores and
geometric counts do not prove why a position is strategically good or bad.

## Tests

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q
```

The real-engine integration test is skipped unless explicitly configured:

```powershell
$env:STOCKFISH_PATH = 'C:\path\to\stockfish.exe'
.\.venv\Scripts\python.exe -m pytest -q
```

Tests exercise special moves, FEN/PGN validity, history retention, White score
normalization, mate scores, legal PV conversion, terminal positions, settings,
engine reuse, cancellation/restart, crashes, handshake/search timeouts, stale UI
events, and GUI responsiveness. The fake UCI engine is exclusively a test fixture;
real engine integration runs the configured executable. The offline integration
test denies external Python socket connections and DNS, permitting only loopback
for Windows asyncio's wakeup socket. It does not disable the host's network adapters
or constrain arbitrary engine executables at the OS level.

Inspection tests cover contested squares, blocked attack rays, pawn/king
geometry, absolute pins, legal mobility in check, castling, en passant,
promotion destination counting, evidence validity, board/history preservation,
mode switching, overlays and evidence hover, and displayed-position PV reports.
Comparison tests additionally verify candidate priority/legality, root restrictions,
equal search budgets, move history, piece tracking, actual capture/recapture
prefixes, bounds/mates, partial failure/cancellation, and comparison replay.

## Architecture and next milestones

`position.py` owns legal board state and PGN navigation. `analysis.py` owns typed
requests/results and a persistent UCI process on an asyncio worker thread.
`settings.py` stores local preferences. Qt drawing and presentation live in
`board.py` and `gui.py`; worker events reach widgets through queued Qt signals.
`features.py` extracts immutable square/piece reports from a copied board,
`explanations.py` produces deterministic claims with structured evidence, and
`inspection.py` presents them. Feature extraction and explanation generation
import neither Qt nor engine services.
`comparisons.py` defines comparison data, legal candidates and feature differences;
`comparison_view.py` presents the table and evidence. The engine worker streams
comparison progress and completed branches through the existing Qt signal bridge.

Analysis requests copy the complete move stack. Engine streams are bounded by
search time plus a timeout grace period. Cancellation resets the engine process
to recover even when an engine ignores `stop`; normal searches reuse one process.
The UI offers explicit analysis rather than automatic searches on every click.

Next: strategic explanation templates grounded in comparative evidence;
SQLite caching and eviction;
then packaging, footprint checks, and redistribution compliance.

## Troubleshooting and storage

- Missing engine or invalid executable: configure the extracted `.exe`, not the
  ZIP or a shortcut. The board works without it.
- Engine startup crashes: use a build appropriate for your CPU. Check whether
  external neural evaluation files are required by that distribution.
- Capability errors: lower threads/hash to the engine's reported supported range.
- Qt DLL errors after changing Qt packages: reinstall PySide6 Essentials in a
  clean virtual environment. Avoid mixing Qt installations.
- PGN errors: use standard chess and a UTF-8 text file with legal mainline moves.
- A cancelled or failed engine restarts on the next analysis request.

See [docs/VALIDATION.md](docs/VALIDATION.md) for measured development sizes and
verification results. No frozen installer has been built, and the packaged
under-500-MB target has **not** been verified.

Application license: GPL-3.0-or-later. See [LICENSE](LICENSE),
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and bundled asset attribution.
