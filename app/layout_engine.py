"""Pure geometry and image-scaling math for the collage application.

Every function in this module is a pure function: no file I/O, no Qt, no
Pillow. This keeps the core layout/crop mathematics fully unit-testable
and guarantees that preview rendering and final export rendering agree,
because both call through this same module.

Coordinate conventions
-----------------------
* All canvas/slot geometry is expressed in millimeters until converted to
  pixels for rendering (see :func:`mm_to_px`).
* Cover-scale crop math is expressed generically in "target pixel" units
  (which may be export-resolution pixels or small preview pixels -- the
  math is identical either way) so the same functions serve both the
  editor preview and the final export renderer.
* Normalized crop positions (``norm_x``, ``norm_y``) range over
  ``[-1.0, 1.0]``. ``0.0`` means centered. ``-1.0`` means the crop window
  is pushed to the start (left/top) of the available overflow range,
  ``+1.0`` means it is pushed to the end (right/bottom). Because the crop
  window's position is always computed as a linear interpolation between
  ``0`` and the maximum overflow, an in-range normalized value can never
  produce a crop box that exceeds the scaled image bounds -- blank space
  inside a slot is mathematically impossible as long as ``norm_x``/
  ``norm_y`` stay within ``[-1.0, 1.0]``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.constants import (
    MM_PER_INCH,
    NORM_POSITION_MAX,
    NORM_POSITION_MIN,
    SLOT_HEIGHT_MM,
    SLOT_WIDTH_MM,
    DEFAULT_EXPORT_DPI,
    print_size_mm,
)
from app.models import CanvasLayout, Orientation, SlotGeometry, SourceOrientation
from app.constants import PrintSizeId

# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------


def mm_to_px(millimeters: float, dpi: int) -> int:
    """Convert a millimeter measurement to whole pixels at the given DPI.

    ``pixels = round((millimeters / 25.4) * dpi)`` as required for
    print-accurate export sizing.
    """

    return round((millimeters / MM_PER_INCH) * dpi)


def px_to_mm(pixels: float, dpi: int) -> float:
    """Convert a pixel measurement back to millimeters at the given DPI."""

    return (pixels / dpi) * MM_PER_INCH


# ---------------------------------------------------------------------------
# Canvas orientation and slot-count calculation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _OrientationCandidate:
    canvas_width_mm: float
    canvas_height_mm: float
    columns: int
    rows: int
    slot_count: int
    margin_x_mm: float
    margin_y_mm: float

    @property
    def margin_imbalance_mm(self) -> float:
        """Absolute difference between the horizontal and vertical outer
        margin totals; smaller means the unused border is more evenly
        distributed between the two axes."""

        return abs(self.margin_x_mm - self.margin_y_mm)

    @property
    def orientation(self) -> Orientation:
        return (
            Orientation.LANDSCAPE
            if self.canvas_width_mm > self.canvas_height_mm
            else Orientation.PORTRAIT
        )


def _evaluate_candidate(canvas_width_mm: float, canvas_height_mm: float) -> _OrientationCandidate:
    columns = math.floor(canvas_width_mm / SLOT_WIDTH_MM)
    rows = math.floor(canvas_height_mm / SLOT_HEIGHT_MM)
    margin_x = canvas_width_mm - columns * SLOT_WIDTH_MM
    margin_y = canvas_height_mm - rows * SLOT_HEIGHT_MM
    return _OrientationCandidate(
        canvas_width_mm=canvas_width_mm,
        canvas_height_mm=canvas_height_mm,
        columns=columns,
        rows=rows,
        slot_count=columns * rows,
        margin_x_mm=margin_x,
        margin_y_mm=margin_y,
    )


def compute_canvas_layout(
    print_size_id: PrintSizeId, dpi: int = DEFAULT_EXPORT_DPI
) -> CanvasLayout:
    """Compute the best canvas orientation and slot grid for a print size.

    Evaluates both the as-given orientation and its 90-degree swap,
    picking whichever fits the most complete ``SLOT_WIDTH_MM`` x
    ``SLOT_HEIGHT_MM`` slots. Ties are broken by preferring the
    orientation whose leftover outer margin is most evenly distributed
    between the horizontal and vertical axes. The resulting slot grid is
    centered on the canvas.
    """

    base_width_mm, base_height_mm = print_size_mm(print_size_id)

    candidates = [
        _evaluate_candidate(base_width_mm, base_height_mm),
        _evaluate_candidate(base_height_mm, base_width_mm),
    ]

    best = max(
        candidates,
        key=lambda c: (c.slot_count, -c.margin_imbalance_mm),
    )

    start_x_mm = best.margin_x_mm / 2.0
    start_y_mm = best.margin_y_mm / 2.0

    slots: list[SlotGeometry] = []
    for row in range(best.rows):
        for column in range(best.columns):
            slots.append(
                SlotGeometry(
                    row=row,
                    column=column,
                    x_mm=start_x_mm + column * SLOT_WIDTH_MM,
                    y_mm=start_y_mm + row * SLOT_HEIGHT_MM,
                    width_mm=SLOT_WIDTH_MM,
                    height_mm=SLOT_HEIGHT_MM,
                )
            )

    return CanvasLayout(
        print_size_id=print_size_id,
        orientation=best.orientation,
        canvas_width_mm=best.canvas_width_mm,
        canvas_height_mm=best.canvas_height_mm,
        columns=best.columns,
        rows=best.rows,
        slots=tuple(slots),
    )


def slot_pixel_rect(slot: SlotGeometry, dpi: int) -> tuple[int, int, int, int]:
    """Return ``(x_px, y_px, width_px, height_px)`` for a slot at the given
    DPI. Pixel spans are derived from rounding each slot's absolute start
    and end coordinates (rather than rounding width/height independently
    and adding), which guarantees that adjacent slots tile edge-to-edge
    with no 1-pixel gaps or overlaps caused by rounding drift."""

    x_px = mm_to_px(slot.x_mm, dpi)
    y_px = mm_to_px(slot.y_mm, dpi)
    right_px = mm_to_px(slot.x_mm + slot.width_mm, dpi)
    bottom_px = mm_to_px(slot.y_mm + slot.height_mm, dpi)
    return x_px, y_px, right_px - x_px, bottom_px - y_px


def export_canvas_pixel_size(layout: CanvasLayout, dpi: int) -> tuple[int, int]:
    """Return the exact (width_px, height_px) export canvas size for a layout."""

    return (
        mm_to_px(layout.canvas_width_mm, dpi),
        mm_to_px(layout.canvas_height_mm, dpi),
    )


# ---------------------------------------------------------------------------
# Source image orientation classification
# ---------------------------------------------------------------------------


def classify_source_orientation(width_px: int, height_px: int) -> SourceOrientation:
    """Classify an (already EXIF-corrected) image as portrait/landscape/square."""

    if width_px > height_px:
        return SourceOrientation.LANDSCAPE
    if height_px > width_px:
        return SourceOrientation.PORTRAIT
    return SourceOrientation.SQUARE


# ---------------------------------------------------------------------------
# Cover-scale crop mathematics
# ---------------------------------------------------------------------------


def compute_cover_scale(
    source_width: float, source_height: float, target_width: float, target_height: float
) -> float:
    """Return the uniform scale factor that makes the source image "cover"
    the target rectangle (fill it completely with no distortion, allowing
    overflow on at most one axis)."""

    if source_width <= 0 or source_height <= 0:
        raise ValueError("source_width and source_height must be positive")
    return max(target_width / source_width, target_height / source_height)


def scaled_size(source_width: float, source_height: float, scale: float) -> tuple[float, float]:
    """Return the (width, height) of a source image after applying ``scale``."""

    return source_width * scale, source_height * scale


def compute_overflow(
    source_width: float, source_height: float, target_width: float, target_height: float
) -> tuple[float, float]:
    """Return (overflow_width, overflow_height): how much the cover-scaled
    image exceeds the target rectangle on each axis. Both values are
    clamped to be >= 0 (rounding may otherwise produce tiny negatives)."""

    scale = compute_cover_scale(source_width, source_height, target_width, target_height)
    scaled_w, scaled_h = scaled_size(source_width, source_height, scale)
    overflow_w = max(0.0, scaled_w - target_width)
    overflow_h = max(0.0, scaled_h - target_height)
    return overflow_w, overflow_h


def allowed_movement_axes(
    overflow_width: float, overflow_height: float, epsilon: float = 1e-6
) -> tuple[bool, bool]:
    """Return (allow_horizontal, allow_vertical) booleans indicating which
    axes have overflow (and are thus draggable) beyond a tiny rounding
    epsilon."""

    return overflow_width > epsilon, overflow_height > epsilon


def clamp_normalized(value: float) -> float:
    """Clamp a normalized crop coordinate to the valid [-1.0, 1.0] range."""

    return max(NORM_POSITION_MIN, min(NORM_POSITION_MAX, value))


def crop_box_in_source_px(
    source_width: float,
    source_height: float,
    target_width: float,
    target_height: float,
    norm_x: float,
    norm_y: float,
) -> tuple[float, float, float, float]:
    """Compute the crop rectangle, expressed in *source image pixel
    coordinates*, that should be extracted and resized to
    ``(target_width, target_height)`` to realize the cover-crop for the
    given normalized position.

    Cropping directly from source-pixel coordinates (rather than resizing
    the whole source first and cropping the resized copy) means the final
    resize step only ever touches the exact pixels needed, minimizing
    unnecessary resampling.

    Returns:
        ``(left, top, right, bottom)`` in source-image pixel space. This
        box is always fully contained within the source image bounds for
        any ``norm_x``/``norm_y`` within ``[-1.0, 1.0]``.
    """

    norm_x = clamp_normalized(norm_x)
    norm_y = clamp_normalized(norm_y)

    scale = compute_cover_scale(source_width, source_height, target_width, target_height)
    overflow_w, overflow_h = compute_overflow(source_width, source_height, target_width, target_height)

    # Position of the crop window's top-left corner within the *scaled*
    # image, linearly interpolated across the available overflow range.
    crop_left_scaled = (overflow_w / 2.0) * (1.0 + norm_x)
    crop_top_scaled = (overflow_h / 2.0) * (1.0 + norm_y)

    # Convert back into source-image pixel coordinates.
    left = crop_left_scaled / scale
    top = crop_top_scaled / scale
    right = left + target_width / scale
    bottom = top + target_height / scale

    return left, top, right, bottom


def normalized_delta_from_drag(
    drag_delta_px: float, overflow_px: float
) -> float:
    """Convert a mouse-drag delta (in preview pixels, positive = image
    dragged toward larger screen coordinates) into a change in a
    normalized crop coordinate.

    Dragging the image toward larger X/Y visually reveals more of the
    image's start (left/top) edge, which corresponds to *decreasing* the
    normalized position (moving the crop window's start toward zero).
    Returns 0.0 if there is no overflow on this axis (nothing to drag).
    """

    if overflow_px <= 0:
        return 0.0
    return -drag_delta_px / (overflow_px / 2.0)


def requires_upscaling(
    source_width: float, source_height: float, target_width: float, target_height: float
) -> bool:
    """Return True if covering the target rectangle requires enlarging the
    source image beyond its native resolution (i.e. the effective print
    resolution would fall below the target DPI)."""

    scale = compute_cover_scale(source_width, source_height, target_width, target_height)
    return scale > 1.0
