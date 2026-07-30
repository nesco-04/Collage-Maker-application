"""Centralized physical, rendering, and styling constants.

All measurements are expressed in millimeters unless the name ends in
``_PX`` or ``_DPI``. Keeping every tunable constant in one module makes it
possible to change spacing, colors, or default DPI without touching the
geometry or rendering code.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------

MM_PER_INCH: Final[float] = 25.4

# ---------------------------------------------------------------------------
# Print (canvas) sizes, defined in inches then converted to exact mm.
# ---------------------------------------------------------------------------


class PrintSizeId(str, Enum):
    """Identifiers for the supported standard print sizes."""

    FIVE_BY_SEVEN = "5x7"
    EIGHT_BY_TEN = "8x10"


PRINT_SIZES_INCHES: Final[dict[PrintSizeId, tuple[float, float]]] = {
    PrintSizeId.FIVE_BY_SEVEN: (5.0, 7.0),
    PrintSizeId.EIGHT_BY_TEN: (8.0, 10.0),
}

PRINT_SIZE_LABELS: Final[dict[PrintSizeId, str]] = {
    PrintSizeId.FIVE_BY_SEVEN: "5 x 7 inches",
    PrintSizeId.EIGHT_BY_TEN: "8 x 10 inches",
}


def print_size_mm(size_id: PrintSizeId) -> tuple[float, float]:
    """Return the (width_mm, height_mm) for a print size, as given (unrotated)."""

    width_in, height_in = PRINT_SIZES_INCHES[size_id]
    return width_in * MM_PER_INCH, height_in * MM_PER_INCH


# ---------------------------------------------------------------------------
# Image slot geometry
# ---------------------------------------------------------------------------

SLOT_WIDTH_MM: Final[float] = 111.0
SLOT_HEIGHT_MM: Final[float] = 86.0

# ---------------------------------------------------------------------------
# Rendering / export
# ---------------------------------------------------------------------------

DEFAULT_EXPORT_DPI: Final[int] = 300

# No gaps between slots by default; kept as a named constant so a future
# version can introduce spacing without touching layout math elsewhere.
SLOT_SPACING_MM: Final[float] = 0.0

CANVAS_BACKGROUND_RGB: Final[tuple[int, int, int]] = (255, 255, 255)

# Editor-only decoration colors (never rendered into the exported image).
EDITOR_EMPTY_SLOT_BORDER_RGB: Final[tuple[int, int, int]] = (200, 200, 200)
EDITOR_SELECTED_SLOT_BORDER_RGB: Final[tuple[int, int, int]] = (30, 120, 220)
EDITOR_SLOT_BORDER_WIDTH_PX: Final[int] = 2
EDITOR_SELECTED_SLOT_BORDER_WIDTH_PX: Final[int] = 3

# Preview cache target long-edge size in pixels; large enough for a crisp
# on-screen preview at typical window sizes, small enough to stay fast.
PREVIEW_CACHE_MAX_DIMENSION_PX: Final[int] = 900

# Supported import file extensions (WebP included when Pillow supports it).
SUPPORTED_IMAGE_EXTENSIONS: Final[tuple[str, ...]] = (
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
)

# Minimum effective pixels-per-mm at export DPI below which we warn the user
# that the source image is too small for its assigned crop area.
MIN_ACCEPTABLE_PPI_RATIO: Final[float] = 1.0  # 1.0 == exactly meets export DPI

# Normalized crop-position bounds.
NORM_POSITION_MIN: Final[float] = -1.0
NORM_POSITION_MAX: Final[float] = 1.0
