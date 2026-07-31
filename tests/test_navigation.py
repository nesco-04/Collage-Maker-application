"""GUI-level tests for first-page removal and editor restart behavior."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from app.constants import PrintSizeId
from app.editor_page import build_batch_export_paths
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


def test_selection_page_4x6_allows_one_photo(qt_app: QApplication) -> None:
    page = SelectionPage()
    page.restore_selection(PrintSizeId.FOUR_BY_SIX, [r"C:\photos\first.jpg"])

    assert page._current_print_size_id() == PrintSizeId.FOUR_BY_SIX
    assert page._max_slot_count() == 1
    assert "101.6 mm x 152.4 mm" in page._dimensions_label.text()
    assert page._continue_button.isEnabled()


def test_selection_page_allows_more_photos_than_one_print(
    qt_app: QApplication,
) -> None:
    page = SelectionPage()
    files = [rf"C:\photos\photo_{index}.jpg" for index in range(6)]
    page.restore_selection(PrintSizeId.FIVE_BY_SEVEN, files)

    assert page._continue_button.isEnabled()
    assert "3 print(s)" in page._capacity_label.text()


def _make_source_images(tmp_path: Path, count: int) -> list[str]:
    paths: list[str] = []
    for index in range(count):
        source = tmp_path / f"source_{index}.png"
        Image.new("RGB", (1200, 1600), (index * 20, 120, 140)).save(source)
        paths.append(str(source))
    return paths


def test_4x6_six_photos_builds_six_ordered_prints(tmp_path: Path) -> None:
    paths = _make_source_images(tmp_path, 6)

    states = MainWindow._build_states(PrintSizeId.FOUR_BY_SIX, paths)

    assert len(states) == 6
    assert all(state.layout.slot_count == 1 for state in states)
    assert [
        state.assignments[0].source_path for state in states
    ] == paths


def test_5x7_six_photos_builds_three_ordered_prints(tmp_path: Path) -> None:
    paths = _make_source_images(tmp_path, 6)

    states = MainWindow._build_states(PrintSizeId.FIVE_BY_SEVEN, paths)

    assert len(states) == 3
    grouped_paths = [
        [state.assignments[index].source_path for index in sorted(state.assignments)]
        for state in states
    ]
    assert grouped_paths == [paths[0:2], paths[2:4], paths[4:6]]


def test_editor_navigation_preserves_crop_positions(
    qt_app: QApplication, tmp_path: Path
) -> None:
    paths = _make_source_images(tmp_path, 2)
    states = MainWindow._build_states(PrintSizeId.FOUR_BY_SIX, paths)
    window = MainWindow()
    window.editor_page.load_batch(states)
    states[0].assignments[0].norm_y = 0.75

    window.editor_page._on_next()
    assert window.editor_page._state is states[1]
    assert window.editor_page._batch_label.text() == "Print 2 of 2"

    window.editor_page._on_previous()
    assert window.editor_page._state is states[0]
    assert states[0].assignments[0].norm_y == pytest.approx(0.75)


def test_batch_export_paths_are_numbered_without_overwriting_base_name() -> None:
    assert build_batch_export_paths(r"C:\exports\collage.png", 3) == [
        r"C:\exports\collage_01.png",
        r"C:\exports\collage_02.png",
        r"C:\exports\collage_03.png",
    ]
    assert build_batch_export_paths(r"C:\exports\collage.tif", 1) == [
        r"C:\exports\collage.tif"
    ]


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
    assert window._states == []
    assert window._last_file_paths == []
    assert window.selection_page._selected_files == []
    assert not window.selection_page._continue_button.isEnabled()
    assert window.editor_page._state is None
