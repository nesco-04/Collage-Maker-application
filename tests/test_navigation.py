"""GUI-level tests for first-page removal and editor restart behavior."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from app.constants import PrintSizeId
from app.main_window import MainWindow
from app.selection_page import SelectionPage


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    return app


def test_selection_page_removes_highlighted_photos(qt_app: QApplication) -> None:
    page = SelectionPage()
    page.restore_selection(
        PrintSizeId.FIVE_BY_SEVEN,
        [r"C:\photos\first.jpg", r"C:\photos\second.jpg"],
    )

    page._file_list_widget.item(0).setSelected(True)
    page._on_remove_selected()

    assert page._selected_files == [r"C:\photos\second.jpg"]
    assert page._count_label.text() == "1 photo(s) selected"
    assert page._continue_button.isEnabled()


def test_selection_page_clear_all_disables_continue(qt_app: QApplication) -> None:
    page = SelectionPage()
    page.restore_selection(PrintSizeId.FIVE_BY_SEVEN, [r"C:\photos\first.jpg"])

    page._on_clear_all()

    assert page._selected_files == []
    assert page._count_label.text() == "0 photo(s) selected"
    assert not page._continue_button.isEnabled()


def test_restart_returns_to_empty_selection_page(
    qt_app: QApplication, tmp_path: Path
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (1200, 1600), (100, 120, 140)).save(source)
    window = MainWindow()
    window._on_continue(PrintSizeId.FIVE_BY_SEVEN, [str(source)])

    assert window.currentWidget() is window.editor_page
    assert window._state is not None

    window._on_restart()

    assert window.currentWidget() is window.selection_page
    assert window._state is None
    assert window._last_file_paths == []
    assert window.selection_page._selected_files == []
    assert not window.selection_page._continue_button.isEnabled()
    assert window.editor_page._state is None
