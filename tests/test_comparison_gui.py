from dataclasses import replace
import sys

import chess
import pytest
from PySide6.QtCore import QTimer

from counterfactual_chess.comparisons import ComparisonEvent, ComparisonLimits
from test_analysis import FAKE
from test_gui import window


def configure_fake(window, mode="comparison"):
    submit = window.service.submit_comparison
    window.service.submit_comparison = lambda request: submit(
        replace(request, limits=ComparisonLimits(.1, .1)), [sys.executable, FAKE, mode])
    window.mode_selector.setCurrentText("Inspect")
    window.on_square(chess.E2)


def test_comparison_table_progress_replay_and_inspection(window, qtbot):
    configure_fake(window)
    original = window.position.board.fen()
    ticks = []
    timer = QTimer(window)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(5)
    window.compare_continuations()
    assert window.tabs.currentWidget() is window.comparison_panel
    qtbot.waitUntil(lambda: window.comparison is not None and window.comparison.status == "complete", timeout=8000)
    batch = window.comparison
    assert ticks and len(batch.branches) == window.comparison_panel.table.rowCount()
    assert "(ref)" in window.comparison_panel.table.item(0, 0).text()
    assert window.comparison_panel.table.item(0, 2).text() == "+0.00"
    window.comparison_panel.table.selectRow(1)
    assert window.comparison_panel.evidence.topLevelItemCount() >= 2
    assert window.comparison_panel.summary.text()
    window.replay_comparison(1)
    assert window.replay_ply == 1 and window.board.board.fen() != original
    window.on_square(chess.E4)
    assert window.board.inspection_report.fen == window.board.board.fen()
    assert not window.inspector.compare_button.isEnabled()
    assert window.comparison == batch
    window.return_to_position()
    assert window.position.board.fen() == original and window.board.board.fen() == original
    assert window.comparison == batch


def test_cancel_keeps_completed_evidence_and_rejects_late_events(window, qtbot):
    configure_fake(window, "partial_slow")
    window.compare_continuations()
    qtbot.waitUntil(lambda: window.comparison is not None and len(window.comparison.branches) == 1, timeout=6000)
    batch = window.comparison
    window.cancel_comparison()
    assert window.comparison.status == "incomplete"
    assert window.comparison.branches == batch.branches
    window.on_comparison_event(ComparisonEvent(batch.request_id, "complete", replace(batch, status="complete")))
    assert window.comparison.status == "incomplete"
    assert window.comparison_panel.forward.isEnabled()
    window.replay_comparison(1)
    assert window.replay_ply == 1


@pytest.mark.parametrize("change", ["selection", "position", "mode", "analysis", "settings"])
def test_changes_invalidate_comparisons(window, qtbot, change, monkeypatch):
    configure_fake(window, "partial_slow")
    window.compare_continuations()
    qtbot.waitUntil(lambda: window.comparison is not None and len(window.comparison.branches) == 1, timeout=6000)
    stale = window.comparison
    if change == "selection":
        window.on_square(chess.D4)
    elif change == "position":
        window.new_position()
    elif change == "mode":
        window.mode_selector.setCurrentText("Move")
        assert window.tabs.currentWidget() is window.engine_panel
    elif change == "analysis":
        # Missing configured engine fails cleanly after invalidating the old batch.
        window.analyze()
    else:
        from counterfactual_chess.gui import SettingsDialog
        from PySide6.QtWidgets import QDialog
        monkeypatch.setattr(SettingsDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
        window.engine_settings()
    assert window.comparison is None
    assert window.comparison_panel.table.rowCount() == 0
    window.on_comparison_event(ComparisonEvent(stale.request_id, "complete", replace(stale, status="complete")))
    assert window.comparison is None


def test_flip_overlay_and_tab_changes_preserve_running_comparison(window, qtbot):
    configure_fake(window, "partial_slow")
    window.compare_continuations()
    qtbot.waitUntil(lambda: window.comparison is not None and len(window.comparison.branches) == 1, timeout=6000)
    identifier = window.comparison_id
    window.flip()
    window.inspector.show_overlays.setChecked(False)
    window.tabs.setCurrentWidget(window.inspector)
    assert window.active_job == "comparison" and window.comparison_id == identifier
    window.tabs.setCurrentWidget(window.comparison_panel)
    window.cancel_comparison()


def test_error_after_partial_batch_preserves_table(window, qtbot):
    configure_fake(window, "partial_crash")
    window.compare_continuations()
    qtbot.waitUntil(lambda: window.comparison is not None and window.comparison.status == "incomplete", timeout=6000)
    assert len(window.comparison.branches) == 1
    assert window.comparison_panel.table.rowCount() == 1
    assert not window.comparison_panel.cancel_button.isEnabled()
