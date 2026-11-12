# Milestone 1 validation

Development machine: Windows x86-64, Python 3.12.10. Measurements taken
November 12, 2026. Sizes below are logical file sizes, not compressed download
sizes or filesystem allocation. No frozen application has been produced.

## Installed versions

- PySide6 Essentials 6.12.0 / Shiboken 6.12.0
- python-chess 1.999 / chess 1.11.2
- pytest 9.2.0 / pytest-qt 4.5.0
- Separately downloaded Stockfish 19, official Windows x86-64 universal build

## Measured development footprint

| Component | Bytes | MiB |
| --- | ---: | ---: |
| Development virtual environment, including tests and pip | 252,621,180 | 240.92 |
| Separately installed base Python directory, including its existing packages | 413,609,292 | 394.45 |
| Separate Stockfish executable | 103,046,300 | 98.27 |
| Entire extracted engine distribution, including source and notices | 104,581,630 | 99.74 |

The base Python installation is shared with the machine and is not contained
in the virtual environment. Its full size is reported for transparency, not
as an estimate of a future bundled interpreter. The development environment
plus the extracted engine occupies approximately 341 MiB, excluding base Python,
source, Git, download archives, and pip caches. The initial full PySide6 install
was replaced with Essentials to exclude unused browser/PDF/add-on components.

The preferred **packaged** footprint under 500 MB remains unverified. No claim
is made that these development measurements satisfy a packaged storage target.
No analysis cache exists yet; later cache defaults must enforce the specified
250 MB limit. Binary dependency redistribution is deferred to packaging.

## Verification performed

- Automated core, fake-UCI lifecycle, real-engine, and Qt smoke tests:
  **23 passed** with `STOCKFISH_PATH` configured, in 4.36 seconds.
- Real Stockfish analysis from the standard starting position, with legal PV
  conversion and actual depth/score metadata.
- Visually inspected the native desktop board and analysis panel. Clicked
  Analyze, observed Stockfish 19 return a White-perspective score and PV,
  replayed the first PV move, and returned to the preserved position.
- Example observed search: 3 seconds, 1 thread, 64 MiB, depth 26,
  +0.27 **lower bound**, PV `e2e4 e7e5`. This is one observed engine result,
  not an expected test score or an asserted exact evaluation.
- Qt timer tests confirm the GUI event loop continues during worker analysis;
  deterministic tests exercise cancellation, stale events, process reuse,
  shutdown, crashes, and engines ignoring stop/handshake commands.
- The real-engine integration test and desktop review blocked external Python
  socket connects and DNS while permitting asyncio's local loopback wakeup pair.

The host network adapters were **not** disabled, and the downloaded engine was
not enclosed in an OS-level network sandbox. To complete the separate physical
disconnect check, disconnect Wi-Fi/Ethernet, launch with dependencies and engine
already installed, load a FEN/PGN, analyze, and replay the PV. There are no network
clients, cloud calls, telemetry, or automatic downloads in application code.

## Repeating measurements

From PowerShell, sum logical file lengths for the desired directory:

```powershell
(Get-ChildItem -LiteralPath .venv -Recurse -File | Measure-Object -Property Length -Sum).Sum
(Get-Item -LiteralPath 'C:\path\to\stockfish.exe').Length
```

Run the documented tests with `STOCKFISH_PATH` set to validate against your engine.

## Milestone 2: geometric inspection

Implemented and validated on the same Windows/Python environment without adding
dependencies or installing new engines. The footprint table above remains the
Milestone 1 development baseline; it is not a packaged-install measurement.

- **44 tests passed** in 4.91 seconds, with `QT_QPA_PLATFORM=offscreen` and the
  existing Stockfish executable configured through `STOCKFISH_PATH`.
- Curated rules tests cover empty/occupied contested squares, defenders, blocked
  sliding rays, pawn pushes versus attacks, king geometry, absolute pins,
  check evasions, castling, en passant, and promotion destination counting.
- Reports and explanations are deterministic and contain typed immutable data.
  Every claim references evidence with the inspected FEN and applicable squares,
  pieces or legal moves. Tests check these references against the original board
  and verify its FEN and complete move history remain unchanged.
- Qt tests cover mode switching, both piece colors, real mouse-hover evidence
  highlighting, overlay toggling, flipped coordinates, and both-color overlay
  rendering. Position/game/navigation changes clear reports; analysis, completed
  results and cancellation preserve reports for an unchanged position.
- PV tests inspect the displayed preview FEN, verify the PV preview label and
  correct side-to-move mobility, and clear reports when preview positions change.
- Native desktop review at the default 1150 × 760 client size verified the
  Engine/Inspect layout, summary, expandable evidence, and hover highlights.
  Inspecting the starting e2 pawn showed diagonal attack marks on d3/f3 and legal
  destination dots on e3/e4. Selecting a Black knight on e5 in
  `4k3/8/3p4/4n3/3P4/2N5/8/4K3 w - - 0 1` showed a White solid-blue attack from
  d4, a Black dashed-purple defense from d6, the knight's attacked squares,
  and unavailable Black legal mobility on White's turn.

Milestone 2 inspection does not compute strategic importance or assess relative
pins or pawn structure. Engine variation comparison is added in Milestone 3.

## Milestone 3: legal counterfactual comparisons

Implemented on the same Windows/Python environment with the existing dependencies
and separately installed Stockfish 19. No new dependencies or downloads were
needed for this milestone. Packaged footprint and physical network-disconnect
verification remain unverified as described above.

- The full automated suite passes **70 tests**, including real Stockfish ordinary
  analysis and comparison integration tests, fake-UCI lifecycle tests, and Qt tests.
- UCI command tracing verifies that discovery requests MultiPV, each branch
  restricts `searchmoves` to its candidate, every search receives the same original
  root/history, and default search work is capped at one discovery plus four
  one-second branches. Branch searches reset the engine game and clear hash when
  supported. Comparison timing is separate from ordinary analysis timing.
- Tests cover deterministic priority and deduplication, either color's selected
  pieces, control changes, pawn contacts, captures/recaptures, en passant, promotion,
  rook movement during castling, history preservation, and legal snapshot prefixes.
- Score tests cover White perspective, mate/bound exclusion from numeric differences,
  and retaining a deeper unbounded PV when followed by shallower or bounded updates.
- Failure tests cover missing engines, unsupported MultiPV, engines ignoring root
  restrictions, partial crashes, branch timeouts, cancellation, engine recovery,
  terminal positions without an engine, and positions with only one legal move.
- Qt tests verify responsive progress, completed-branch tables, cancellation with
  partial evidence retained, stale event rejection, root-selection/position/settings
  invalidation, branch replay, and inspection of preview positions. Flips, tabs and
  overlay toggles preserve running comparisons.
- Native desktop review at the default client size verified a real comparison
  for the starting e2 pawn, a four-row table, expandable search evidence, replay of
  an alternative's first move, and return to the unchanged original position.
  One observed run returned d4 as the discovery reference (+0.17), Nf3 (+0.17),
  Nc3 (+0.04), and e4 (+0.24), all White-perspective continuation evaluations.
  The e4 line replayed legally with 22 reported plies. These values describe that
  run only; they are not fixed expectations or strategic claims. Re-search may
  rank alternatives differently from discovery.

Only completed branch searches contribute score rows. Cancelled/failed batches
are marked incomplete and retain completed branches for inspection. Snapshots
describe measured geometry after their labeled legal prefixes; their endpoint
positions are not assigned independently searched engine scores. Comparisons do
not provide causal strategic explanations, confidence probabilities, or guarantees
that generated alternatives are strong. Strategic synthesis remains Milestone 4;
caching, packaging and distribution remain later work.
