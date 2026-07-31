"""Page 1: print size selection and image import.

Presents the supported print sizes, shows the resulting per-print slot
count, and lets the user choose any number of source images via the native
Windows file picker before continuing to the batched editor.
"""

from __future__ import annotations

import math
import os
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from app.constants import PrintSizeId, PRINT_SIZE_LABELS, print_size_mm, SUPPORTED_IMAGE_EXTENSIONS
from app.image_renderer import is_supported_image_file
from app.layout_engine import compute_canvas_layout


class SelectionPage(QWidget):
    """First page of the wizard: print-size choice and image import.

    Signals:
        continue_requested: emitted with ``(print_size_id, file_paths)``
            when the user clicks Continue with a valid selection.
    """

    continue_requested = Signal(object, list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._selected_files: list[str] = []
        self._build_ui()
        self._refresh_file_list()
        self._on_print_size_changed()

    # -- UI construction ---------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(16)

        title = QLabel("Collage Maker")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        layout.addWidget(title)

        subtitle = QLabel("Choose a print size, then import your photos.")
        subtitle.setStyleSheet("color: #444;")
        layout.addWidget(subtitle)

        size_row = QHBoxLayout()
        self._radio_4x6 = QRadioButton(PRINT_SIZE_LABELS[PrintSizeId.FOUR_BY_SIX])
        self._radio_5x7 = QRadioButton(PRINT_SIZE_LABELS[PrintSizeId.FIVE_BY_SEVEN])
        self._radio_8x10 = QRadioButton(PRINT_SIZE_LABELS[PrintSizeId.EIGHT_BY_TEN])
        self._radio_5x7.setChecked(True)
        self._radio_4x6.setToolTip("Standard 4 x 6 inch print")
        self._radio_5x7.setToolTip("Standard 5 x 7 inch print")
        self._radio_8x10.setToolTip("Standard 8 x 10 inch print")
        self._size_group = QButtonGroup(self)
        self._size_group.addButton(self._radio_4x6)
        self._size_group.addButton(self._radio_5x7)
        self._size_group.addButton(self._radio_8x10)
        self._radio_4x6.toggled.connect(self._on_print_size_changed)
        self._radio_5x7.toggled.connect(self._on_print_size_changed)
        self._radio_8x10.toggled.connect(self._on_print_size_changed)
        size_row.addWidget(self._radio_4x6)
        size_row.addWidget(self._radio_5x7)
        size_row.addWidget(self._radio_8x10)
        size_row.addStretch(1)
        layout.addLayout(size_row)

        self._dimensions_label = QLabel()
        layout.addWidget(self._dimensions_label)

        self._capacity_label = QLabel()
        self._capacity_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self._capacity_label)

        browse_row = QHBoxLayout()
        self._browse_button = QPushButton("Browse for Photos...")
        self._browse_button.setToolTip("Open the Windows file picker to choose one or more photos")
        self._browse_button.clicked.connect(self._on_browse_clicked)
        browse_row.addWidget(self._browse_button)
        browse_row.addStretch(1)
        layout.addLayout(browse_row)

        self._file_list_widget = QListWidget()
        self._file_list_widget.setToolTip("Photos selected for this collage, in the order they will fill slots")
        self._file_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._file_list_widget.itemSelectionChanged.connect(self._update_remove_buttons)
        layout.addWidget(self._file_list_widget, stretch=1)

        selection_actions = QHBoxLayout()
        self._count_label = QLabel()
        selection_actions.addWidget(self._count_label)
        selection_actions.addStretch(1)

        self._remove_selected_button = QPushButton("Remove Selected")
        self._remove_selected_button.setToolTip("Remove the highlighted photos from this collage")
        self._remove_selected_button.clicked.connect(self._on_remove_selected)
        selection_actions.addWidget(self._remove_selected_button)

        self._clear_all_button = QPushButton("Clear All")
        self._clear_all_button.setToolTip("Remove all selected photos")
        self._clear_all_button.clicked.connect(self._on_clear_all)
        selection_actions.addWidget(self._clear_all_button)
        layout.addLayout(selection_actions)

        self._validation_label = QLabel()
        self._validation_label.setStyleSheet("color: #B00020; font-weight: 600;")
        self._validation_label.setWordWrap(True)
        layout.addWidget(self._validation_label)

        continue_row = QHBoxLayout()
        continue_row.addStretch(1)
        self._continue_button = QPushButton("Continue")
        self._continue_button.setDefault(True)
        self._continue_button.setToolTip("Proceed to arrange your photos in the collage editor")
        self._continue_button.clicked.connect(self._on_continue_clicked)
        continue_row.addWidget(self._continue_button)
        layout.addLayout(continue_row)

    # -- helpers -------------------------------------------------------

    def _current_print_size_id(self) -> PrintSizeId:
        if self._radio_4x6.isChecked():
            return PrintSizeId.FOUR_BY_SIX
        if self._radio_8x10.isChecked():
            return PrintSizeId.EIGHT_BY_TEN
        return PrintSizeId.FIVE_BY_SEVEN

    def _max_slot_count(self) -> int:
        return compute_canvas_layout(self._current_print_size_id()).slot_count

    def _on_print_size_changed(self) -> None:
        size_id = self._current_print_size_id()
        width_mm, height_mm = print_size_mm(size_id)
        self._dimensions_label.setText(
            f"Selected print: {PRINT_SIZE_LABELS[size_id]} "
            f"({width_mm:.1f} mm x {height_mm:.1f} mm)"
        )
        max_slots = self._max_slot_count()
        count = len(self._selected_files)
        if count:
            output_count = math.ceil(count / max_slots)
            self._capacity_label.setText(
                f"Each print holds {max_slots} image(s). "
                f"Your selection will create {output_count} print(s)."
            )
        else:
            self._capacity_label.setText(
                f"Each print holds up to {max_slots} image(s). "
                "Select any number of photos to create a batch."
            )
        self._revalidate()

    def _on_browse_clicked(self) -> None:
        extensions = " ".join(f"*{ext}" for ext in SUPPORTED_IMAGE_EXTENSIONS)
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select photos for your collage",
            "",
            f"Image files ({extensions});;All files (*.*)",
        )
        if not file_paths:
            return

        supported: list[str] = []
        unsupported: list[str] = []
        for path in file_paths:
            if is_supported_image_file(path):
                supported.append(path)
            else:
                unsupported.append(os.path.basename(path))

        self._selected_files.extend(supported)
        self._refresh_file_list()

        if unsupported:
            self._validation_label.setText(
                "Ignored unsupported file(s): " + ", ".join(unsupported)
            )
        self._revalidate()

    def _refresh_file_list(self) -> None:
        self._file_list_widget.clear()
        for path in self._selected_files:
            self._file_list_widget.addItem(os.path.basename(path))
        self._count_label.setText(f"{len(self._selected_files)} photo(s) selected")
        self._update_remove_buttons()
        if hasattr(self, "_capacity_label"):
            self._on_print_size_changed()

    def _update_remove_buttons(self) -> None:
        self._remove_selected_button.setEnabled(bool(self._file_list_widget.selectedItems()))
        self._clear_all_button.setEnabled(bool(self._selected_files))

    def _on_remove_selected(self) -> None:
        selected_rows = sorted(
            {index.row() for index in self._file_list_widget.selectedIndexes()},
            reverse=True,
        )
        if not selected_rows:
            return
        for row in selected_rows:
            del self._selected_files[row]
        self._validation_label.setText("")
        self._refresh_file_list()
        self._revalidate()

    def _on_clear_all(self) -> None:
        self._selected_files.clear()
        self._validation_label.setText("")
        self._refresh_file_list()
        self._revalidate()

    def _revalidate(self) -> None:
        count = len(self._selected_files)

        if count == 0:
            if not self._validation_label.text().startswith("Ignored"):
                self._validation_label.setText("")
            self._continue_button.setEnabled(False)
        else:
            if not self._validation_label.text().startswith("Ignored"):
                self._validation_label.setText("")
            self._continue_button.setEnabled(True)

    def _on_continue_clicked(self) -> None:
        if not self._selected_files:
            self._revalidate()
            return
        self.continue_requested.emit(self._current_print_size_id(), list(self._selected_files))

    # -- public API used by MainWindow for Back navigation --------------

    def restore_selection(self, print_size_id: PrintSizeId, file_paths: list[str]) -> None:
        """Restore a previous print-size choice and file selection, used
        when the user navigates Back from the editor without having
        changed their photos."""

        if print_size_id == PrintSizeId.FOUR_BY_SIX:
            self._radio_4x6.setChecked(True)
        elif print_size_id == PrintSizeId.EIGHT_BY_TEN:
            self._radio_8x10.setChecked(True)
        else:
            self._radio_5x7.setChecked(True)
        self._selected_files = list(file_paths)
        self._refresh_file_list()
        self._validation_label.setText("")
        self._revalidate()

    def reset_selection(self) -> None:
        """Return the page to its initial state with no imported photos."""

        self._radio_5x7.setChecked(True)
        self._selected_files.clear()
        self._validation_label.setText("")
        self._refresh_file_list()
        self._revalidate()
