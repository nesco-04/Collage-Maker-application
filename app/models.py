"""Data model classes describing collage state.

These classes hold only plain data (paths, floats, enums) so that the
application state can be reasoned about, tested, and (de)serialized
independently of Qt or Pillow. Nothing in this module touches the file
system or performs image decoding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.constants import PrintSizeId


class Orientation(str, Enum):
    """Canvas orientation."""

    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class SourceOrientation(str, Enum):
    """Classification of a source image's aspect ratio."""

    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"
    SQUARE = "square"


@dataclass(frozen=True)
class SlotGeometry:
    """Physical position/size of a single slot on the canvas, in millimeters.

    ``x_mm``/``y_mm`` is the top-left corner of the slot relative to the
    top-left corner of the canvas.
    """

    row: int
    column: int
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float


@dataclass(frozen=True)
class CanvasLayout:
    """Result of the slot-count/orientation calculation for a print size.

    Attributes:
        print_size_id: Which standard print size this layout is based on.
        orientation: The chosen canvas orientation (portrait/landscape).
        canvas_width_mm: Physical canvas width in millimeters (post-orientation).
        canvas_height_mm: Physical canvas height in millimeters (post-orientation).
        columns: Number of slot columns that fit.
        rows: Number of slot rows that fit.
        slots: Slot geometries in reading order (left-to-right, top-to-bottom).
    """

    print_size_id: PrintSizeId
    orientation: Orientation
    canvas_width_mm: float
    canvas_height_mm: float
    columns: int
    rows: int
    slots: tuple[SlotGeometry, ...]

    @property
    def slot_count(self) -> int:
        return self.columns * self.rows


@dataclass
class ImageAssignment:
    """A single imported image assigned to a slot, with its crop state.

    Attributes:
        source_path: Absolute path to the original, untouched source file.
        source_width_px: Width of the image in pixels *after* EXIF
            orientation correction has been conceptually applied.
        source_height_px: Height of the image in pixels after EXIF
            orientation correction.
        source_orientation: Portrait / landscape / square classification.
        norm_x: Normalized horizontal crop offset in [-1.0, 1.0]. 0 means
            centered; -1/+1 mean the crop is pushed fully to one edge of
            the overflow range. Meaningless (kept at 0) if there is no
            horizontal overflow.
        norm_y: Normalized vertical crop offset in [-1.0, 1.0], same
            convention as ``norm_x`` but for the vertical axis.
    """

    source_path: str
    source_width_px: int
    source_height_px: int
    source_orientation: SourceOrientation
    norm_x: float = 0.0
    norm_y: float = 0.0

    def reset_position(self) -> None:
        """Recenter the crop (normalized position back to zero)."""

        self.norm_x = 0.0
        self.norm_y = 0.0


@dataclass
class CollageState:
    """Top-level mutable application state shared across GUI pages.

    Attributes:
        print_size_id: Selected standard print size.
        layout: The computed CanvasLayout (columns/rows/slots) for that size.
        export_dpi: Target export resolution in dots per inch.
        assignments: Mapping of slot index (0-based, reading order) to the
            ImageAssignment occupying that slot. Empty slots have no entry.
    """

    print_size_id: PrintSizeId
    layout: CanvasLayout
    export_dpi: int
    assignments: dict[int, ImageAssignment] = field(default_factory=dict)

    def clear_assignments(self) -> None:
        self.assignments.clear()

    def assignment_for_slot(self, slot_index: int) -> Optional[ImageAssignment]:
        return self.assignments.get(slot_index)
