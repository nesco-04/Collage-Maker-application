"""Tests for app.image_renderer: EXIF-correct loading, cover-crop
rendering, preview caching, and export-canvas construction.

These tests generate small synthetic images with Pillow at test time and
do not depend on PySide6, keeping the core rendering pipeline testable in
a headless environment (e.g. CI without a display).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.constants import PrintSizeId, DEFAULT_EXPORT_DPI
from app.image_renderer import (
    ImageLoadError,
    PreviewCache,
    is_supported_image_file,
    load_corrected_image,
    read_image_metadata,
    render_collage,
    render_slot_image,
    save_collage,
)
from app.layout_engine import compute_canvas_layout, export_canvas_pixel_size
from app.models import CollageState, ImageAssignment, SourceOrientation


def _make_image(path: Path, width: int, height: int, color=(255, 0, 0)) -> None:
    Image.new("RGB", (width, height), color).save(path)


# ---------------------------------------------------------------------------
# File-type support
# ---------------------------------------------------------------------------


def test_is_supported_image_file_accepts_common_formats():
    assert is_supported_image_file("photo.jpg")
    assert is_supported_image_file("photo.JPEG")
    assert is_supported_image_file("photo.png")
    assert is_supported_image_file("photo.tiff")
    assert is_supported_image_file("photo.bmp")


def test_is_supported_image_file_rejects_unknown_extension():
    assert not is_supported_image_file("document.pdf")
    assert not is_supported_image_file("notes.txt")


# ---------------------------------------------------------------------------
# Loading and metadata
# ---------------------------------------------------------------------------


def test_load_corrected_image_raises_for_missing_file(tmp_path: Path):
    missing = tmp_path / "does_not_exist.png"
    with pytest.raises(ImageLoadError):
        load_corrected_image(str(missing))


def test_read_image_metadata_portrait(tmp_path: Path):
    path = tmp_path / "portrait.png"
    _make_image(path, 400, 800)
    metadata = read_image_metadata(str(path))
    assert metadata.width == 400
    assert metadata.height == 800
    assert metadata.orientation == SourceOrientation.PORTRAIT


def test_read_image_metadata_landscape(tmp_path: Path):
    path = tmp_path / "landscape.png"
    _make_image(path, 800, 400)
    metadata = read_image_metadata(str(path))
    assert metadata.orientation == SourceOrientation.LANDSCAPE


def test_exif_orientation_is_corrected(tmp_path: Path):
    # Build a 400x800 (portrait) image but tag it as rotated 90 degrees via
    # EXIF orientation 6 ("rotate 270 CW to display correctly" per the EXIF
    # spec, i.e. the stored raster is actually the physically-rotated data
    # and orientation reports how to un-rotate it back to upright).
    path = tmp_path / "rotated.jpg"
    raw = Image.new("RGB", (800, 400), (0, 255, 0))  # stored raster: landscape
    exif = raw.getexif()
    exif[274] = 6  # Orientation tag: rotate 90 CW to correct
    raw.save(path, exif=exif)

    corrected = load_corrected_image(str(path))
    try:
        # After correcting a 90-degree rotation, width/height swap.
        assert corrected.width == 400
        assert corrected.height == 800
    finally:
        corrected.close()


# ---------------------------------------------------------------------------
# Cover-crop slot rendering
# ---------------------------------------------------------------------------


def test_render_slot_image_produces_exact_target_size(tmp_path: Path):
    path = tmp_path / "source.png"
    _make_image(path, 3000, 2000, color=(10, 20, 30))
    assignment = ImageAssignment(
        source_path=str(path),
        source_width_px=3000,
        source_height_px=2000,
        source_orientation=SourceOrientation.LANDSCAPE,
    )
    rendered = render_slot_image(assignment, target_width_px=1311, target_height_px=1016)
    assert rendered.size == (1311, 1016)
    assert rendered.mode == "RGB"


def test_render_slot_image_no_visible_blank_space_at_extreme_positions(tmp_path: Path):
    path = tmp_path / "source_extreme.png"
    _make_image(path, 3000, 1000, color=(50, 60, 70))
    for norm_x in (-1.0, 0.0, 1.0):
        assignment = ImageAssignment(
            source_path=str(path),
            source_width_px=3000,
            source_height_px=1000,
            source_orientation=SourceOrientation.LANDSCAPE,
            norm_x=norm_x,
        )
        rendered = render_slot_image(assignment, target_width_px=500, target_height_px=300)
        # A uniform-color source image with no blank padding must remain a
        # single uniform color after any valid crop/resize.
        extrema = rendered.convert("RGB").getextrema()
        assert all(lo == hi for lo, hi in extrema)


# ---------------------------------------------------------------------------
# Full collage rendering
# ---------------------------------------------------------------------------


def _build_state_with_images(tmp_path: Path, print_size_id: PrintSizeId, count: int) -> CollageState:
    layout = compute_canvas_layout(print_size_id)
    state = CollageState(print_size_id=print_size_id, layout=layout, export_dpi=DEFAULT_EXPORT_DPI)
    for index in range(count):
        path = tmp_path / f"img_{index}.png"
        _make_image(path, 1200, 900, color=(index * 30 % 255, 100, 150))
        state.assignments[index] = ImageAssignment(
            source_path=str(path),
            source_width_px=1200,
            source_height_px=900,
            source_orientation=SourceOrientation.LANDSCAPE,
        )
    return state


def test_render_collage_4x6_has_one_slot_and_correct_dimensions(tmp_path: Path):
    state = _build_state_with_images(tmp_path, PrintSizeId.FOUR_BY_SIX, count=1)
    assert state.layout.slot_count == 1
    canvas = render_collage(state)
    assert canvas.size == export_canvas_pixel_size(state.layout, state.export_dpi)


def test_render_collage_matches_export_pixel_dimensions(tmp_path: Path):
    state = _build_state_with_images(tmp_path, PrintSizeId.FIVE_BY_SEVEN, count=1)
    canvas = render_collage(state)
    expected_size = export_canvas_pixel_size(state.layout, state.export_dpi)
    assert canvas.size == expected_size


def test_render_collage_leaves_unfilled_slots_white(tmp_path: Path):
    # 5x7 layout has 2 slots; only fill 1, leaving the second blank.
    state = _build_state_with_images(tmp_path, PrintSizeId.FIVE_BY_SEVEN, count=1)
    canvas = render_collage(state)
    second_slot = state.layout.slots[1]
    from app.layout_engine import slot_pixel_rect

    x, y, w, h = slot_pixel_rect(second_slot, state.export_dpi)
    center_pixel = canvas.getpixel((x + w // 2, y + h // 2))
    assert center_pixel == (255, 255, 255)


def test_render_collage_8x10_has_four_slot_capacity(tmp_path: Path):
    state = _build_state_with_images(tmp_path, PrintSizeId.EIGHT_BY_TEN, count=4)
    assert state.layout.slot_count == 4
    canvas = render_collage(state)
    expected_size = export_canvas_pixel_size(state.layout, state.export_dpi)
    assert canvas.size == expected_size


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------


def test_save_collage_png(tmp_path: Path):
    image = Image.new("RGB", (100, 80), (255, 255, 255))
    destination = tmp_path / "out.png"
    save_collage(image, str(destination))
    assert destination.exists()
    with Image.open(destination) as reloaded:
        assert reloaded.size == (100, 80)


def test_save_collage_jpeg(tmp_path: Path):
    image = Image.new("RGB", (100, 80), (10, 20, 30))
    destination = tmp_path / "out.jpg"
    save_collage(image, str(destination))
    assert destination.exists()


# ---------------------------------------------------------------------------
# Preview cache
# ---------------------------------------------------------------------------


def test_preview_cache_bounds_dimensions(tmp_path: Path):
    path = tmp_path / "large.png"
    _make_image(path, 4000, 3000)
    cache = PreviewCache(max_dimension_px=500)
    preview = cache.get(str(path))
    assert max(preview.width, preview.height) <= 500


def test_preview_cache_returns_cached_instance_on_second_call(tmp_path: Path):
    path = tmp_path / "cached.png"
    _make_image(path, 200, 200)
    cache = PreviewCache()
    first = cache.get(str(path))
    second = cache.get(str(path))
    assert first is second


def test_preview_cache_invalidate_forces_rebuild(tmp_path: Path):
    path = tmp_path / "cached2.png"
    _make_image(path, 200, 200)
    cache = PreviewCache()
    first = cache.get(str(path))
    cache.invalidate(str(path))
    second = cache.get(str(path))
    assert first is not second
