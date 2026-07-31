"""Page 2: responsive collage editor.

Displays each full print canvas in an ordered batch (always fully visible,
scaled to fit the window while preserving aspect ratio), lets the user
select, reposition, replace, or remove images in each slot, and exports
the complete batch at full print resolution using
:mod:`app.image_renderer`.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.constants import CANVAS_BACKGROUND_RGB, SUPPORTED_IMAGE_EXTENSIONS
from app.image_renderer import (
    ImageLoadError,
    PreviewCache,
    image_needs_upscale_warning,
    read_image_metadata,
    render_collage,
    save_collage,
)
from app.image_slot_widget import ImageSlotWidget
from app.models import CollageState, ImageAssignment

logger = logging.getLogger(__name__)


def build_batch_export_paths(destination_path: str, count: int) -> list[str]:
    """Return exact output paths for one or more collage exports."""

    if count <= 0:
        raise ValueError("count must be positive")
    stem, extension = os.path.splitext(destination_path)
    if not extension:
        extension = ".png"
    if count == 1:
        return [stem + extension]
    number_width = max(2, len(str(count)))
    return [
        f"{stem}_{index:0{number_width}d}{extension}"
        for index in range(1, count + 1)
    ]


class _ExportWorker(QObject):
    """Runs the (potentially slow) final render + save on a background
    thread so the GUI thread never blocks. All Qt widget access happens
    only via the ``finished`` signal, delivered back on the GUI thread."""

    finished = Signal(bool, str)

    def __init__(self, jobs: list[tuple[CollageState, str]]) -> None:
        super().__init__()
        self._jobs = jobs

    def run(self) -> None:
        try:
            for state, destination_path in self._jobs:
                image = render_collage(state)
                try:
                    save_collage(image, destination_path)
                finally:
                    image.close()
        except ImageLoadError as exc:
            logger.exception("Export failed: source image error")
            self.finished.emit(False, str(exc))
        except OSError as exc:
            logger.exception("Export failed: file system error")
            self.finished.emit(False, f"Could not save file: {exc}")
        except MemoryError:
            logger.exception("Export failed: out of memory")
            self.finished.emit(False, "Ran out of memory while rendering the collage.")
        except Exception as exc:  # noqa: BLE001 - guard against any unexpected failure
            logger.exception("Export failed: unexpected error")
            self.finished.emit(False, f"Unexpected error: {exc}")
        else:
            paths = [path for _, path in self._jobs]
            if len(paths) == 1:
                message = paths[0]
            else:
                message = f"{len(paths)} collages saved in:\n{os.path.dirname(paths[0])}"
            self.finished.emit(True, message)


class CanvasWidget(QWidget):
    """The white print-canvas surface holding the slot grid.

    Maintains the exact print aspect ratio and positions the slot grid
    (with any centered outer margin) proportionally as the widget is
    resized, so the full canvas -- including margins -- is always what
    the user sees, matching the final export layout.
    """

    def __init__(self, state: CollageState, grid_widget: QWidget, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = state
        self._grid_widget = grid_widget
        self._grid_widget.setParent(self)
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            f"background-color: rgb({CANVAS_BACKGROUND_RGB[0]}, "
            f"{CANVAS_BACKGROUND_RGB[1]}, {CANVAS_BACKGROUND_RGB[2]});"
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        layout = self._state.layout
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0 or layout.canvas_width_mm <= 0:
            return

        grid_width_mm = layout.columns * layout.slots[0].width_mm if layout.slots else 0.0
        grid_height_mm = layout.rows * layout.slots[0].height_mm if layout.slots else 0.0
        margin_x_mm = layout.canvas_width_mm - grid_width_mm
        margin_y_mm = layout.canvas_height_mm - grid_height_mm

        grid_x = int(round((margin_x_mm / 2.0) / layout.canvas_width_mm * width))
        grid_y = int(round((margin_y_mm / 2.0) / layout.canvas_height_mm * height))
        grid_w = int(round(grid_width_mm / layout.canvas_width_mm * width))
        grid_h = int(round(grid_height_mm / layout.canvas_height_mm * height))
        self._grid_widget.setGeometry(grid_x, grid_y, grid_w, grid_h)


class AspectRatioContainer(QWidget):
    """Scales a single child widget to the largest size that fits within
    this container while preserving a fixed aspect ratio, centering it.
    Used so the full print canvas remains visible and undistorted at any
    application window size."""

    def __init__(self, child: QWidget, aspect_width: float, aspect_height: float, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._child = child
        self._child.setParent(self)
        self._aspect_width = aspect_width
        self._aspect_height = aspect_height
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_aspect(self, aspect_width: float, aspect_height: float) -> None:
        self._aspect_width = aspect_width
        self._aspect_height = aspect_height
        self._relayout()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        available_w, available_h = self.width(), self.height()
        if available_w <= 0 or available_h <= 0 or self._aspect_height <= 0:
            return
        target_ratio = self._aspect_width / self._aspect_height
        if available_w / available_h > target_ratio:
            height = available_h
            width = int(round(height * target_ratio))
        else:
            width = available_w
            height = int(round(width / target_ratio))
        x = (available_w - width) // 2
        y = (available_h - height) // 2
        self._child.setGeometry(x, y, width, height)


class EditorPage(QWidget):
    """Second page of the wizard: the responsive collage editor.

    Signals:
        back_requested: emitted when the user clicks Back.
        restart_requested: emitted when the user clicks Restart.
    """

    back_requested = Signal()
    restart_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state: Optional[CollageState] = None
        self._states: list[CollageState] = []
        self._state_index = 0
        self._preview_cache = PreviewCache()
        self._slot_widgets: list[ImageSlotWidget] = []
        self._selected_slot_index: Optional[int] = None
        self._export_thread: Optional[QThread] = None
        self._export_worker: Optional[_ExportWorker] = None
        self._build_ui()

    # -- UI construction ---------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        header_row = QHBoxLayout()
        header = QLabel("Arrange Your Collage")
        header.setStyleSheet("font-size: 18px; font-weight: 600;")
        header_row.addWidget(header)
        header_row.addStretch(1)
        self._previous_button = QPushButton("Previous Print")
        self._previous_button.clicked.connect(self._on_previous)
        header_row.addWidget(self._previous_button)
        self._batch_label = QLabel("Print 0 of 0")
        self._batch_label.setStyleSheet("font-weight: 600;")
        header_row.addWidget(self._batch_label)
        self._next_button = QPushButton("Next Print")
        self._next_button.clicked.connect(self._on_next)
        header_row.addWidget(self._next_button)
        root.addLayout(header_row)

        self._grid_widget = QWidget()
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(0)

        # Placeholder canvas/aspect container; rebuilt in load_state() once
        # the real layout (and its aspect ratio) is known.
        self._canvas_widget = CanvasWidget(_EMPTY_STATE_PLACEHOLDER, self._grid_widget)
        self._aspect_container = AspectRatioContainer(self._canvas_widget, 5.0, 7.0)
        root.addWidget(self._aspect_container, stretch=1)

        self._status_label = QLabel("No slot selected.")
        root.addWidget(self._status_label)

        button_row = QHBoxLayout()
        self._center_button = QPushButton("Center Selected Image")
        self._center_button.setToolTip("Recenter the selected slot's image")
        self._center_button.clicked.connect(self._on_center_selected)

        self._reset_all_button = QPushButton("Reset All Positions")
        self._reset_all_button.setToolTip("Recenter every image in every print in this batch")
        self._reset_all_button.clicked.connect(self._on_reset_all)

        self._replace_button = QPushButton("Replace Image...")
        self._replace_button.setToolTip("Choose a different photo for the selected slot")
        self._replace_button.clicked.connect(self._on_replace_image)

        self._remove_button = QPushButton("Remove Image")
        self._remove_button.setToolTip("Empty the selected slot")
        self._remove_button.clicked.connect(self._on_remove_image)

        self._back_button = QPushButton("Back")
        self._back_button.setToolTip("Return to print size and photo selection")
        self._back_button.clicked.connect(self.back_requested.emit)

        self._restart_button = QPushButton("Restart")
        self._restart_button.setToolTip("Discard this collage and start again with no selected photos")
        self._restart_button.clicked.connect(self.restart_requested.emit)

        self._export_button = QPushButton("Export All...")
        self._export_button.setToolTip("Save every print in this batch at full print resolution")
        self._export_button.clicked.connect(self._on_export)

        for button in (
            self._center_button,
            self._reset_all_button,
            self._replace_button,
            self._remove_button,
        ):
            button_row.addWidget(button)
        button_row.addStretch(1)
        button_row.addWidget(self._back_button)
        button_row.addWidget(self._restart_button)
        button_row.addWidget(self._export_button)
        root.addLayout(button_row)

        self._update_slot_action_buttons()

    # -- state loading ---------------------------------------------------

    def load_batch(
        self, states: list[CollageState], initial_index: int = 0
    ) -> None:
        """Load an ordered batch and display one print at a time."""

        if not states:
            raise ValueError("A batch must contain at least one collage state")
        if not 0 <= initial_index < len(states):
            raise IndexError("initial_index is outside the batch")
        self._states = states
        self._state_index = initial_index
        self.load_state(states[initial_index])

    def load_state(self, state: CollageState) -> None:
        """Populate the editor for a (possibly new) CollageState.

        Fills slots with the state's existing assignments in reading
        order and rebuilds the slot-widget grid to match the layout's
        row/column count.
        """

        self._state = state
        self._preview_cache.clear()
        self._selected_slot_index = None

        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._slot_widgets = []

        layout = state.layout
        for index, slot in enumerate(layout.slots):
            slot_widget = ImageSlotWidget(index, slot, self._preview_cache, self._grid_widget)
            slot_widget.clicked.connect(self._on_slot_clicked)
            slot_widget.position_changed.connect(self._on_slot_position_changed)
            slot_widget.set_assignment(state.assignments.get(index))
            self._grid_layout.addWidget(slot_widget, slot.row, slot.column)
            self._slot_widgets.append(slot_widget)

        self._canvas_widget._state = state  # widget already constructed; swap in the real state
        self._aspect_container.set_aspect(layout.canvas_width_mm, layout.canvas_height_mm)
        self._canvas_widget._relayout()

        self._status_label.setText("No slot selected.")
        self._update_batch_controls()
        self._update_slot_action_buttons()

    def _update_batch_controls(self) -> None:
        count = len(self._states)
        self._batch_label.setText(
            f"Print {self._state_index + 1} of {count}" if count else "Print 0 of 0"
        )
        self._previous_button.setEnabled(count > 0 and self._state_index > 0)
        self._next_button.setEnabled(count > 0 and self._state_index < count - 1)
        self._export_button.setText("Export All..." if count > 1 else "Export...")

    def _show_batch_state(self, index: int) -> None:
        if not 0 <= index < len(self._states):
            return
        self._state_index = index
        self.load_state(self._states[index])

    def _on_previous(self) -> None:
        self._show_batch_state(self._state_index - 1)

    def _on_next(self) -> None:
        self._show_batch_state(self._state_index + 1)

    def clear_state(self) -> None:
        """Release the current collage and restore the editor placeholder."""

        self._state = None
        self._states = []
        self._state_index = 0
        self._selected_slot_index = None
        self._preview_cache.clear()
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._slot_widgets = []
        self._canvas_widget._state = _EMPTY_STATE_PLACEHOLDER
        self._aspect_container.set_aspect(5.0, 7.0)
        self._canvas_widget._relayout()
        self._status_label.setText("No slot selected.")
        self._update_batch_controls()
        self._update_slot_action_buttons()

    # -- slot selection ---------------------------------------------------

    def _on_slot_clicked(self, slot_index: int) -> None:
        self._select_slot(slot_index)

    def _select_slot(self, slot_index: Optional[int]) -> None:
        self._selected_slot_index = slot_index
        for widget in self._slot_widgets:
            widget.set_selected(widget.slot_index == slot_index)
        if slot_index is None:
            self._status_label.setText("No slot selected.")
        else:
            widget = self._slot_widgets[slot_index]
            state = "filled" if widget.assignment() is not None else "empty"
            self._status_label.setText(f"Slot {slot_index + 1} selected ({state}).")
        self._update_slot_action_buttons()

    def _selected_widget(self) -> Optional[ImageSlotWidget]:
        if self._selected_slot_index is None:
            return None
        return self._slot_widgets[self._selected_slot_index]

    def _update_slot_action_buttons(self) -> None:
        widget = self._selected_widget()
        has_assignment = widget is not None and widget.assignment() is not None
        self._center_button.setEnabled(has_assignment)
        self._replace_button.setEnabled(widget is not None)
        self._remove_button.setEnabled(has_assignment)
        self._reset_all_button.setEnabled(bool(self._state and self._state.assignments))

    def _on_slot_position_changed(self, slot_index: int) -> None:
        # Positions are stored directly on the ImageAssignment by the slot
        # widget; nothing further to persist here.
        pass

    # -- toolbar actions ---------------------------------------------------

    def _on_center_selected(self) -> None:
        widget = self._selected_widget()
        if widget is None or widget.assignment() is None:
            return
        widget.assignment().reset_position()
        widget.update()

    def _on_reset_all(self) -> None:
        if not self._states:
            return
        for state in self._states:
            for assignment in state.assignments.values():
                assignment.reset_position()
        for widget in self._slot_widgets:
            widget.update()

    def _on_replace_image(self) -> None:
        if self._state is None or self._selected_slot_index is None:
            return
        extensions = " ".join(f"*{ext}" for ext in SUPPORTED_IMAGE_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Replace image", "", f"Image files ({extensions});;All files (*.*)"
        )
        if not path:
            return
        try:
            metadata = read_image_metadata(path)
        except ImageLoadError as exc:
            QMessageBox.warning(self, "Could not open image", str(exc))
            return

        slot_index = self._selected_slot_index
        assignment = ImageAssignment(
            source_path=path,
            source_width_px=metadata.width,
            source_height_px=metadata.height,
            source_orientation=metadata.orientation,
        )
        self._state.assignments[slot_index] = assignment
        widget = self._slot_widgets[slot_index]
        widget.invalidate_preview(path)
        widget.set_assignment(assignment)
        self._update_slot_action_buttons()

    def _on_remove_image(self) -> None:
        if self._state is None or self._selected_slot_index is None:
            return
        slot_index = self._selected_slot_index
        self._state.assignments.pop(slot_index, None)
        widget = self._slot_widgets[slot_index]
        widget.set_assignment(None)
        self._update_slot_action_buttons()

    # -- export ---------------------------------------------------------

    def _on_export(self) -> None:
        if not self._states:
            return

        warnings = [
            os.path.basename(assignment.source_path)
            for state in self._states
            for index, slot in enumerate(state.layout.slots)
            if (assignment := state.assignments.get(index)) is not None
            and image_needs_upscale_warning(assignment, slot.width_mm, slot.height_mm, state.export_dpi)
        ]
        if warnings:
            proceed = QMessageBox.warning(
                self,
                "Image resolution warning",
                "The following photo(s) are smaller than ideal for their slot at "
                f"{self._state.export_dpi} DPI and may appear soft when printed:\n\n"
                + "\n".join(warnings)
                + "\n\nContinue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if proceed != QMessageBox.StandardButton.Yes:
                return

        destination_path, chosen_filter = QFileDialog.getSaveFileName(
            self,
            "Export collage batch",
            "collage.png",
            "PNG Image (*.png);;TIFF Image (*.tif *.tiff);;JPEG Image (*.jpg *.jpeg)",
        )
        if not destination_path:
            return
        if not os.path.splitext(destination_path)[1]:
            if chosen_filter.startswith("TIFF"):
                destination_path += ".tif"
            elif chosen_filter.startswith("JPEG"):
                destination_path += ".jpg"
            else:
                destination_path += ".png"

        output_paths = build_batch_export_paths(destination_path, len(self._states))
        existing_paths = [path for path in output_paths if os.path.exists(path)]
        if existing_paths:
            overwrite = QMessageBox.warning(
                self,
                "Replace existing files?",
                f"{len(existing_paths)} output file(s) already exist and will be replaced. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return

        jobs = list(zip(self._states, output_paths))
        self._set_busy(True, f"Exporting {len(jobs)} collage(s)...")
        self._export_thread = QThread(self)
        self._export_worker = _ExportWorker(jobs)
        self._export_worker.moveToThread(self._export_thread)
        self._export_thread.started.connect(self._export_worker.run)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.finished.connect(self._export_thread.quit)
        self._export_thread.start()

    def _on_export_finished(self, success: bool, message: str) -> None:
        if self._selected_slot_index is None:
            status_text = "No slot selected."
        else:
            widget = self._slot_widgets[self._selected_slot_index]
            slot_state = "filled" if widget.assignment() is not None else "empty"
            status_text = (
                f"Slot {self._selected_slot_index + 1} selected ({slot_state})."
            )
        self._set_busy(False, status_text)
        if success:
            QMessageBox.information(self, "Export complete", f"Collage saved to:\n{message}")
        else:
            QMessageBox.critical(self, "Export failed", message)
        if self._export_thread is not None:
            self._export_thread.wait()
        self._export_thread = None
        self._export_worker = None

    def _set_busy(self, busy: bool, status_text: str) -> None:
        self._export_button.setEnabled(not busy)
        self._back_button.setEnabled(not busy)
        self._restart_button.setEnabled(not busy)
        self._previous_button.setEnabled(
            not busy and self._state_index > 0
        )
        self._next_button.setEnabled(
            not busy and self._state_index < len(self._states) - 1
        )
        for button in (
            self._center_button,
            self._reset_all_button,
            self._replace_button,
            self._remove_button,
        ):
            button.setEnabled(not busy and button.isEnabled())
        self.setCursor(Qt.CursorShape.WaitCursor if busy else Qt.CursorShape.ArrowCursor)
        self._status_label.setText(status_text)
        if not busy:
            self._update_slot_action_buttons()


class _EmptyStatePlaceholder:
    """Sentinel with the minimal attributes CanvasWidget reads before a
    real CollageState has been loaded, so the widget can be constructed
    once in __init__ and simply refreshed later in load_state()."""

    class _Layout:
        canvas_width_mm = 127.0
        canvas_height_mm = 177.8
        columns = 1
        rows = 2
        slots: tuple = ()

    layout = _Layout()


_EMPTY_STATE_PLACEHOLDER = _EmptyStatePlaceholder()
