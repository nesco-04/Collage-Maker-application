"""Top-level application window: hosts the selection and editor pages and
owns navigation and CollageState construction between them."""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtWidgets import QMessageBox, QStackedWidget, QWidget

from app.constants import DEFAULT_EXPORT_DPI, PrintSizeId
from app.editor_page import EditorPage
from app.image_renderer import ImageLoadError, read_image_metadata
from app.layout_engine import compute_canvas_layout
from app.models import CollageState, ImageAssignment
from app.selection_page import SelectionPage

logger = logging.getLogger(__name__)


class MainWindow(QStackedWidget):
    """Owns the SelectionPage and EditorPage and mediates navigation.

    Keeps a single :class:`CollageState` instance alive across Back/Continue
    navigation as long as the print size and photo selection are unchanged,
    so in-progress crop positions are never lost by navigating back.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Collage Maker")
        self.resize(1100, 800)

        self._state: Optional[CollageState] = None
        self._states: list[CollageState] = []
        self._last_print_size_id: Optional[PrintSizeId] = None
        self._last_file_paths: list[str] = []

        self.selection_page = SelectionPage()
        self.editor_page = EditorPage()
        self.addWidget(self.selection_page)
        self.addWidget(self.editor_page)

        self.selection_page.continue_requested.connect(self._on_continue)
        self.editor_page.back_requested.connect(self._on_back)
        self.editor_page.restart_requested.connect(self._on_restart)

        self.setCurrentWidget(self.selection_page)

    # -- navigation --------------------------------------------------

    def _on_continue(self, print_size_id: PrintSizeId, file_paths: list[str]) -> None:
        unchanged = (
            bool(self._states)
            and self._last_print_size_id == print_size_id
            and self._last_file_paths == file_paths
        )
        if not unchanged:
            try:
                self._states = self._build_states(print_size_id, file_paths)
            except ImageLoadError as exc:
                QMessageBox.critical(self, "Could not import photo", str(exc))
                return
            self._state = self._states[0]
            self._last_print_size_id = print_size_id
            self._last_file_paths = list(file_paths)

        self.editor_page.load_batch(self._states)
        self.setCurrentWidget(self.editor_page)

    def _on_back(self) -> None:
        if self._last_print_size_id is not None:
            self.selection_page.restore_selection(self._last_print_size_id, self._last_file_paths)
        self.setCurrentWidget(self.selection_page)

    def _on_restart(self) -> None:
        self.editor_page.clear_state()
        self._state = None
        self._states = []
        self._last_print_size_id = None
        self._last_file_paths = []
        self.selection_page.reset_selection()
        self.setCurrentWidget(self.selection_page)

    # -- state construction ---------------------------------------------

    @staticmethod
    def _build_states(
        print_size_id: PrintSizeId, file_paths: list[str]
    ) -> list[CollageState]:
        """Build one collage state per capacity-sized chunk of input files."""

        layout = compute_canvas_layout(print_size_id, dpi=DEFAULT_EXPORT_DPI)
        states: list[CollageState] = []
        for chunk_start in range(0, len(file_paths), layout.slot_count):
            state = CollageState(
                print_size_id=print_size_id,
                layout=layout,
                export_dpi=DEFAULT_EXPORT_DPI,
            )
            chunk = file_paths[chunk_start : chunk_start + layout.slot_count]
            for slot_index, path in enumerate(chunk):
                metadata = read_image_metadata(path)
                state.assignments[slot_index] = ImageAssignment(
                    source_path=path,
                    source_width_px=metadata.width,
                    source_height_px=metadata.height,
                    source_orientation=metadata.orientation,
                )
            states.append(state)
        return states

    @staticmethod
    def _build_state(print_size_id: PrintSizeId, file_paths: list[str]) -> CollageState:
        """Compatibility helper returning the first state of a batch."""

        states = MainWindow._build_states(print_size_id, file_paths)
        if not states:
            raise ValueError("At least one image is required")
        return states[0]
