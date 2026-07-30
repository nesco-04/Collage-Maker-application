"""Interactive widget representing a single collage slot.

Displays the assigned image (via a shared :class:`PreviewCache`), cropped
according to the slot's stored normalized position, and lets the user
click to select, drag to reposition, and use arrow keys to nudge the crop.
All positioning math is delegated to :mod:`app.layout_engine` so the
displayed crop is always mathematically identical to what
:mod:`app.image_renderer` will produce at export time.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.constants import (
    EDITOR_EMPTY_SLOT_BORDER_RGB,
    EDITOR_SELECTED_SLOT_BORDER_RGB,
    EDITOR_SELECTED_SLOT_BORDER_WIDTH_PX,
    EDITOR_SLOT_BORDER_WIDTH_PX,
    CANVAS_BACKGROUND_RGB,
)
from app.image_renderer import PreviewCache, pil_image_to_qimage
from app.layout_engine import (
    allowed_movement_axes,
    clamp_normalized,
    compute_overflow,
    crop_box_in_source_px,
    normalized_delta_from_drag,
)
from app.models import ImageAssignment, SlotGeometry

# Normalized-position change applied per arrow-key press.
KEYBOARD_NUDGE_STEP = 0.05


class ImageSlotWidget(QWidget):
    """A single print slot: shows an optional cropped preview image and
    handles selection, drag-to-reposition, and keyboard nudging.

    Signals:
        clicked: emitted with this widget's slot_index when the slot is
            clicked (used by the editor page to update slot selection).
        position_changed: emitted (with slot_index) whenever the user's
            interaction changes the assigned image's normalized crop
            position.
    """

    clicked = Signal(int)
    position_changed = Signal(int)

    def __init__(
        self,
        slot_index: int,
        slot_geometry: SlotGeometry,
        preview_cache: PreviewCache,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.slot_index = slot_index
        self.slot_geometry = slot_geometry
        self._preview_cache = preview_cache
        self._qimage_cache: dict[str, QImage] = {}

        self._assignment: Optional[ImageAssignment] = None
        self._selected = False

        self._drag_active = False
        self._drag_start_pos = QPointF()
        self._drag_start_norm = (0.0, 0.0)
        self._drag_overflow_px = (0.0, 0.0)
        self._drag_allowed = (False, False)

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(
            "Click to select this slot. Drag the image to reposition it. "
            "Use arrow keys to nudge the selected image."
        )

    # -- state -------------------------------------------------------

    def set_assignment(self, assignment: Optional[ImageAssignment]) -> None:
        """Assign (or clear, with ``None``) the image shown in this slot."""

        self._assignment = assignment
        self._update_cursor_for_state()
        self.update()

    def assignment(self) -> Optional[ImageAssignment]:
        return self._assignment

    def set_selected(self, selected: bool) -> None:
        if self._selected != selected:
            self._selected = selected
            self.update()

    def is_selected(self) -> bool:
        return self._selected

    def invalidate_preview(self, path: str) -> None:
        """Drop any cached QImage for ``path`` (e.g. after Replace Image)."""

        self._qimage_cache.pop(path, None)

    # -- geometry helpers ---------------------------------------------

    def _get_qimage(self, path: str) -> QImage:
        cached = self._qimage_cache.get(path)
        if cached is not None:
            return cached
        pil_preview = self._preview_cache.get(path)
        qimage = pil_image_to_qimage(pil_preview)
        self._qimage_cache[path] = qimage
        return qimage

    def _current_overflow_px(self) -> tuple[float, float]:
        """Overflow of the (preview-resolution) source image beyond this
        widget's current on-screen size, used for drag/nudge clamping."""

        if self._assignment is None:
            return 0.0, 0.0
        qimage = self._get_qimage(self._assignment.source_path)
        return compute_overflow(
            qimage.width(), qimage.height(), self.width(), self.height()
        )

    def _update_cursor_for_state(self) -> None:
        if self._assignment is None:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        overflow_w, overflow_h = self._current_overflow_px()
        allow_x, allow_y = allowed_movement_axes(overflow_w, overflow_h)
        if allow_x or allow_y:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    # -- painting -------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override signature
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = self.rect()
        painter.fillRect(rect, QColor(*CANVAS_BACKGROUND_RGB))

        if self._assignment is not None:
            self._paint_image(painter, rect)
        else:
            painter.setPen(QColor(*EDITOR_EMPTY_SLOT_BORDER_RGB))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "Empty slot")

        self._paint_border(painter, rect)
        painter.end()

    def _paint_image(self, painter: QPainter, rect: QRect) -> None:
        assert self._assignment is not None
        qimage = self._get_qimage(self._assignment.source_path)
        target_w = max(1, rect.width())
        target_h = max(1, rect.height())
        left, top, right, bottom = crop_box_in_source_px(
            qimage.width(),
            qimage.height(),
            target_w,
            target_h,
            self._assignment.norm_x,
            self._assignment.norm_y,
        )
        crop_rect = QRect(
            int(round(left)), int(round(top)), max(1, int(round(right - left))), max(1, int(round(bottom - top)))
        )
        crop_rect = crop_rect.intersected(QRect(0, 0, qimage.width(), qimage.height()))
        if crop_rect.width() <= 0 or crop_rect.height() <= 0:
            return
        cropped = qimage.copy(crop_rect)
        scaled = cropped.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawImage(0, 0, scaled)

    def _paint_border(self, painter: QPainter, rect: QRect) -> None:
        if self._selected:
            color = QColor(*EDITOR_SELECTED_SLOT_BORDER_RGB)
            width = EDITOR_SELECTED_SLOT_BORDER_WIDTH_PX
        else:
            color = QColor(*EDITOR_EMPTY_SLOT_BORDER_RGB)
            width = EDITOR_SLOT_BORDER_WIDTH_PX
        pen = QPen(color, width)
        painter.setPen(pen)
        half = width // 2 if width > 1 else 0
        painter.drawRect(rect.adjusted(half, half, -half - 1, -half - 1))

    # -- resize: crop is normalized, so nothing to recompute on resize --

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_cursor_for_state()

    # -- mouse interaction -----------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.clicked.emit(self.slot_index)
        if self._assignment is None:
            return
        overflow_w, overflow_h = self._current_overflow_px()
        allow_x, allow_y = allowed_movement_axes(overflow_w, overflow_h)
        if not (allow_x or allow_y):
            return
        self._drag_active = True
        self._drag_start_pos = event.position()
        self._drag_start_norm = (self._assignment.norm_x, self._assignment.norm_y)
        self._drag_overflow_px = (overflow_w, overflow_h)
        self._drag_allowed = (allow_x, allow_y)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._drag_active or self._assignment is None:
            return
        delta = event.position() - self._drag_start_pos
        overflow_w, overflow_h = self._drag_overflow_px
        allow_x, allow_y = self._drag_allowed

        new_norm_x = self._drag_start_norm[0]
        new_norm_y = self._drag_start_norm[1]
        if allow_x:
            new_norm_x = clamp_normalized(
                self._drag_start_norm[0] + normalized_delta_from_drag(delta.x(), overflow_w)
            )
        if allow_y:
            new_norm_y = clamp_normalized(
                self._drag_start_norm[1] + normalized_delta_from_drag(delta.y(), overflow_h)
            )

        if (new_norm_x, new_norm_y) != (self._assignment.norm_x, self._assignment.norm_y):
            self._assignment.norm_x = new_norm_x
            self._assignment.norm_y = new_norm_y
            self.update()
            self.position_changed.emit(self.slot_index)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag_active = False
        self._update_cursor_for_state()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not self._drag_active:
            self._update_cursor_for_state()
        super().leaveEvent(event)

    # -- keyboard nudge ---------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._assignment is None:
            super().keyPressEvent(event)
            return

        overflow_w, overflow_h = self._current_overflow_px()
        allow_x, allow_y = allowed_movement_axes(overflow_w, overflow_h)

        key = event.key()
        handled = False
        if key == Qt.Key.Key_Left and allow_x:
            self._assignment.norm_x = clamp_normalized(self._assignment.norm_x - KEYBOARD_NUDGE_STEP)
            handled = True
        elif key == Qt.Key.Key_Right and allow_x:
            self._assignment.norm_x = clamp_normalized(self._assignment.norm_x + KEYBOARD_NUDGE_STEP)
            handled = True
        elif key == Qt.Key.Key_Up and allow_y:
            self._assignment.norm_y = clamp_normalized(self._assignment.norm_y - KEYBOARD_NUDGE_STEP)
            handled = True
        elif key == Qt.Key.Key_Down and allow_y:
            self._assignment.norm_y = clamp_normalized(self._assignment.norm_y + KEYBOARD_NUDGE_STEP)
            handled = True

        if handled:
            self.update()
            self.position_changed.emit(self.slot_index)
        else:
            super().keyPressEvent(event)
