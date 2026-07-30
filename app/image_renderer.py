"""Pillow-based image loading, preview caching, and final export rendering.

This module contains all Pillow (PIL) I/O for the application. GUI code
must never decode, resize, or crop images directly; it should call into
this module instead. The only place PySide6 is imported is inside
:func:`pil_image_to_qimage`, which is a thin conversion helper used solely
to hand a decoded preview image to Qt for on-screen painting -- the
conversion itself performs no resampling or cropping.

Two independent code paths matter for image quality:

* **Preview path** (:class:`PreviewCache`): loads and downsamples images
  once to a bounded preview resolution purely for fast, responsive
  on-screen display. Preview data is cached in memory only and is never
  written to disk or used for export.
* **Export path** (:func:`render_collage`): always re-opens the *original*
  source file from disk, applies EXIF orientation correction, computes the
  crop box from the stored normalized position, crops, and resizes with a
  single high-quality LANCZOS resample directly to the exact export pixel
  dimensions. It never touches preview data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageOps

from app.constants import (
    CANVAS_BACKGROUND_RGB,
    PREVIEW_CACHE_MAX_DIMENSION_PX,
    SUPPORTED_IMAGE_EXTENSIONS,
)
from app.layout_engine import (
    classify_source_orientation,
    crop_box_in_source_px,
    export_canvas_pixel_size,
    requires_upscaling,
    slot_pixel_rect,
)
from app.models import CollageState, ImageAssignment, SourceOrientation

logger = logging.getLogger(__name__)

# Pillow's high-quality downscaling filter, used for every final resize.
_RESAMPLE_FILTER = Image.LANCZOS


class ImageLoadError(RuntimeError):
    """Raised when a source image file cannot be opened or decoded."""


@dataclass(frozen=True)
class ImageMetadata:
    """EXIF-corrected metadata describing an imported source image."""

    width: int
    height: int
    orientation: SourceOrientation


def is_supported_image_file(path: str) -> bool:
    """Return True if ``path``'s extension is one of the supported formats."""

    lowered = path.lower()
    return any(lowered.endswith(ext) for ext in SUPPORTED_IMAGE_EXTENSIONS)


def load_corrected_image(path: str) -> Image.Image:
    """Open ``path`` and return a fully decoded, EXIF-orientation-corrected
    PIL Image.

    Raises:
        ImageLoadError: if the file cannot be opened or decoded.
    """

    try:
        image = Image.open(path)
        image.load()
    except Exception as exc:  # noqa: BLE001 - convert any Pillow/OS failure
        raise ImageLoadError(f"Could not open image: {path}") from exc

    try:
        corrected = ImageOps.exif_transpose(image)
    except Exception as exc:  # noqa: BLE001
        logger.warning("EXIF orientation correction failed for %s: %s", path, exc)
        corrected = image

    if corrected is None:
        corrected = image
    return corrected


def read_image_metadata(path: str) -> ImageMetadata:
    """Read EXIF-corrected width/height/orientation for a source image
    without keeping the decoded pixel buffer around longer than needed."""

    image = load_corrected_image(path)
    try:
        width, height = image.width, image.height
        orientation = classify_source_orientation(width, height)
        return ImageMetadata(width=width, height=height, orientation=orientation)
    finally:
        image.close()


def image_needs_upscale_warning(assignment: ImageAssignment, slot_width_mm: float, slot_height_mm: float, dpi: int) -> bool:
    """Return True if rendering this assignment's slot at ``dpi`` would
    require enlarging the source image beyond its native resolution."""

    from app.layout_engine import mm_to_px

    target_w = mm_to_px(slot_width_mm, dpi)
    target_h = mm_to_px(slot_height_mm, dpi)
    return requires_upscaling(
        assignment.source_width_px, assignment.source_height_px, target_w, target_h
    )


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    """Flatten any alpha/transparency onto a white background and return an
    RGB image, since exported slots must never contain transparency."""

    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, CANVAS_BACKGROUND_RGB)
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return image.convert("RGB")


def render_slot_image(
    assignment: ImageAssignment, target_width_px: int, target_height_px: int
) -> Image.Image:
    """Render a single populated slot at exactly ``target_width_px`` x
    ``target_height_px`` pixels, loading the *original* source file fresh
    from disk and applying the assignment's stored normalized crop
    position. Crops the source in its native pixel space first, then
    performs a single LANCZOS resize directly to the target size.
    """

    image = load_corrected_image(assignment.source_path)
    try:
        left, top, right, bottom = crop_box_in_source_px(
            image.width,
            image.height,
            target_width_px,
            target_height_px,
            assignment.norm_x,
            assignment.norm_y,
        )
        box = (
            max(0, min(image.width - 1, int(round(left)))),
            max(0, min(image.height - 1, int(round(top)))),
            max(1, min(image.width, int(round(right)))),
            max(1, min(image.height, int(round(bottom)))),
        )
        cropped = image.crop(box)
        resized = cropped.resize((target_width_px, target_height_px), _RESAMPLE_FILTER)
        return _flatten_to_rgb(resized)
    finally:
        image.close()


def render_collage(state: CollageState) -> Image.Image:
    """Render the full collage canvas at export resolution.

    Every populated slot is rendered directly from its original source
    file (never from a preview cache). Unfilled slots remain the canvas
    background color (white by default). No editor decorations (borders,
    selection outlines) are ever part of this render.

    Returns:
        A new RGB PIL Image sized to exactly the export pixel dimensions
        implied by ``state.layout`` and ``state.export_dpi``.
    """

    canvas_width_px, canvas_height_px = export_canvas_pixel_size(state.layout, state.export_dpi)
    canvas = Image.new("RGB", (canvas_width_px, canvas_height_px), CANVAS_BACKGROUND_RGB)

    for index, slot in enumerate(state.layout.slots):
        assignment = state.assignments.get(index)
        if assignment is None:
            continue
        slot_x_px, slot_y_px, slot_w_px, slot_h_px = slot_pixel_rect(slot, state.export_dpi)
        try:
            rendered = render_slot_image(assignment, slot_w_px, slot_h_px)
        except ImageLoadError:
            logger.exception("Failed to render slot %d (%s); leaving blank", index, assignment.source_path)
            continue
        canvas.paste(rendered, (slot_x_px, slot_y_px))

    return canvas


def save_collage(image: Image.Image, path: str) -> None:
    """Save a rendered collage image to disk, choosing sensible defaults
    per output format (PNG default lossless, TIFF lossless, JPEG optional
    high-quality lossy).

    Raises:
        OSError: on file-system failures (permissions, missing directory,
            disk full, etc.). Callers should present this to the user
            rather than letting the application crash.
    """

    lowered = path.lower()
    if lowered.endswith(".png"):
        image.save(path, format="PNG", optimize=True)
    elif lowered.endswith(".tif") or lowered.endswith(".tiff"):
        image.save(path, format="TIFF", compression="tiff_lzw")
    elif lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        image.save(path, format="JPEG", quality=95, subsampling=0, optimize=True)
    else:
        # Default to PNG if the user typed a path without a known extension.
        image.save(path, format="PNG", optimize=True)


class PreviewCache:
    """In-memory cache of small, resampled preview images for the editor.

    Preview images are decoded and downsampled once per source path (and
    rebuilt only when explicitly invalidated, e.g. when a new image
    replaces a slot). They are held only as long as the application runs
    and are never written to disk or reused for export.
    """

    def __init__(self, max_dimension_px: int = PREVIEW_CACHE_MAX_DIMENSION_PX) -> None:
        self._max_dimension_px = max_dimension_px
        self._cache: dict[str, Image.Image] = {}

    def get(self, path: str) -> Image.Image:
        """Return a cached (or freshly built) EXIF-corrected, downsampled
        preview copy of the image at ``path``."""

        cached = self._cache.get(path)
        if cached is not None:
            return cached

        image = load_corrected_image(path)
        try:
            preview = image.copy()
            preview.thumbnail(
                (self._max_dimension_px, self._max_dimension_px), _RESAMPLE_FILTER
            )
        finally:
            image.close()

        preview = _flatten_to_rgb(preview) if preview.mode not in ("RGB", "RGBA") else preview
        self._cache[path] = preview
        return preview

    def invalidate(self, path: str) -> None:
        """Drop any cached preview for ``path`` so it will be rebuilt."""

        self._cache.pop(path, None)

    def clear(self) -> None:
        """Drop all cached preview images, releasing their memory."""

        self._cache.clear()


def pil_image_to_qimage(image: Image.Image):
    """Convert a decoded PIL Image into a ``QImage`` for on-screen painting.

    This performs no resampling or cropping -- it only repacks already
    decoded pixel data into Qt's image format. Imported lazily so this
    module can be used (and unit tested) without PySide6 installed.
    """

    from PySide6.QtGui import QImage

    # Always convert to RGBA: at 4 bytes per pixel the scanline stride is
    # always a whole number of bytes with no padding ambiguity, avoiding a
    # known QImage/Pillow pitfall where a tightly-packed 3-byte-per-pixel
    # RGB buffer can mismatch QImage's expected (aligned) stride and read
    # past the end of the buffer.
    if image.mode != "RGBA":
        image = _flatten_to_rgb(image).convert("RGBA") if image.mode != "RGB" else image.convert("RGBA")

    bytes_per_line = image.width * 4
    data = image.tobytes("raw", "RGBA")
    qimage = QImage(data, image.width, image.height, bytes_per_line, QImage.Format.Format_RGBA8888)
    # Copy so the QImage owns its own buffer independent of the Python bytes.
    return qimage.copy()
