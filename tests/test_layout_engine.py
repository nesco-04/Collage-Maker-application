"""Tests for app.layout_engine: mm/px conversion, slot-count and
orientation selection, cover-scale math, crop-position clamping, and
export pixel dimensions."""

from __future__ import annotations

import math

import pytest

from app.constants import DEFAULT_EXPORT_DPI, PrintSizeId
from app.layout_engine import (
    allowed_movement_axes,
    classify_source_orientation,
    clamp_normalized,
    compute_canvas_layout,
    compute_cover_scale,
    compute_overflow,
    crop_box_in_source_px,
    export_canvas_pixel_size,
    mm_to_px,
    normalized_delta_from_drag,
    px_to_mm,
    requires_upscaling,
    scaled_size,
    slot_pixel_rect,
)
from app.models import Orientation, SourceOrientation


# ---------------------------------------------------------------------------
# Millimeter <-> pixel conversion
# ---------------------------------------------------------------------------


def test_mm_to_px_basic_conversion():
    # 1 inch = 25.4 mm, so at 300 DPI, 25.4mm -> 300px exactly.
    assert mm_to_px(25.4, 300) == 300


def test_mm_to_px_matches_formula():
    assert mm_to_px(111.0, 300) == round((111.0 / 25.4) * 300)
    assert mm_to_px(86.0, 300) == round((86.0 / 25.4) * 300)


def test_px_to_mm_round_trip_approximately():
    mm = 100.0
    dpi = 300
    px = mm_to_px(mm, dpi)
    back = px_to_mm(px, dpi)
    assert back == pytest.approx(mm, abs=0.1)


# ---------------------------------------------------------------------------
# Slot-count and orientation selection
# ---------------------------------------------------------------------------


def test_4x6_layout_is_landscape_with_one_slot():
    layout = compute_canvas_layout(PrintSizeId.FOUR_BY_SIX)
    assert layout.orientation == Orientation.LANDSCAPE
    assert layout.columns == 1
    assert layout.rows == 1
    assert layout.slot_count == 1
    assert layout.canvas_width_mm == pytest.approx(152.4)
    assert layout.canvas_height_mm == pytest.approx(101.6)


def test_5x7_layout_is_portrait_with_two_slots():
    layout = compute_canvas_layout(PrintSizeId.FIVE_BY_SEVEN)
    assert layout.orientation == Orientation.PORTRAIT
    assert layout.columns == 1
    assert layout.rows == 2
    assert layout.slot_count == 2
    assert layout.canvas_width_mm == pytest.approx(127.0)
    assert layout.canvas_height_mm == pytest.approx(177.8)


def test_8x10_layout_is_landscape_with_four_slots():
    layout = compute_canvas_layout(PrintSizeId.EIGHT_BY_TEN)
    assert layout.orientation == Orientation.LANDSCAPE
    assert layout.columns == 2
    assert layout.rows == 2
    assert layout.slot_count == 4
    assert layout.canvas_width_mm == pytest.approx(254.0)
    assert layout.canvas_height_mm == pytest.approx(203.2)


def test_5x7_slots_are_centered_with_even_margins():
    layout = compute_canvas_layout(PrintSizeId.FIVE_BY_SEVEN)
    # 1 column x 111mm slots on a 127mm-wide canvas -> 16mm total margin,
    # split evenly left/right.
    left_margin = layout.slots[0].x_mm
    right_margin = layout.canvas_width_mm - (layout.slots[0].x_mm + layout.slots[0].width_mm)
    assert left_margin == pytest.approx(right_margin, abs=1e-6)


def test_slots_are_in_reading_order():
    layout = compute_canvas_layout(PrintSizeId.EIGHT_BY_TEN)
    # 2x2 grid: expect (row, col) in order (0,0) (0,1) (1,0) (1,1)
    expected = [(0, 0), (0, 1), (1, 0), (1, 1)]
    actual = [(slot.row, slot.column) for slot in layout.slots]
    assert actual == expected


def test_all_slots_have_fixed_slot_dimensions():
    for size_id in (
        PrintSizeId.FOUR_BY_SIX,
        PrintSizeId.FIVE_BY_SEVEN,
        PrintSizeId.EIGHT_BY_TEN,
    ):
        layout = compute_canvas_layout(size_id)
        for slot in layout.slots:
            assert slot.width_mm == pytest.approx(111.0)
            assert slot.height_mm == pytest.approx(86.0)


def test_export_canvas_pixel_size_at_300_dpi():
    layout_4x6 = compute_canvas_layout(PrintSizeId.FOUR_BY_SIX)
    width_px, height_px = export_canvas_pixel_size(layout_4x6, DEFAULT_EXPORT_DPI)
    assert width_px == mm_to_px(152.4, 300)
    assert height_px == mm_to_px(101.6, 300)

    layout_5x7 = compute_canvas_layout(PrintSizeId.FIVE_BY_SEVEN)
    width_px, height_px = export_canvas_pixel_size(layout_5x7, DEFAULT_EXPORT_DPI)
    assert width_px == mm_to_px(127.0, 300)
    assert height_px == mm_to_px(177.8, 300)

    layout_8x10 = compute_canvas_layout(PrintSizeId.EIGHT_BY_TEN)
    width_px, height_px = export_canvas_pixel_size(layout_8x10, DEFAULT_EXPORT_DPI)
    assert width_px == mm_to_px(254.0, 300)
    assert height_px == mm_to_px(203.2, 300)


def test_slot_pixel_rects_tile_without_gaps_or_overlaps():
    layout = compute_canvas_layout(PrintSizeId.EIGHT_BY_TEN)
    dpi = 300
    rects = [slot_pixel_rect(slot, dpi) for slot in layout.slots]
    # Slots (0,0) and (0,1) are horizontally adjacent in the same row.
    row0 = [r for slot, r in zip(layout.slots, rects) if slot.row == 0]
    row0_sorted = sorted(row0, key=lambda r: r[0])
    left_rect, right_rect = row0_sorted
    assert left_rect[0] + left_rect[2] == right_rect[0]


# ---------------------------------------------------------------------------
# Source orientation classification
# ---------------------------------------------------------------------------


def test_classify_source_orientation():
    assert classify_source_orientation(2000, 1000) == SourceOrientation.LANDSCAPE
    assert classify_source_orientation(1000, 2000) == SourceOrientation.PORTRAIT
    assert classify_source_orientation(1500, 1500) == SourceOrientation.SQUARE


# ---------------------------------------------------------------------------
# Cover-scale mathematics
# ---------------------------------------------------------------------------


def test_portrait_cover_scaling_fills_width_and_overflows_height():
    # Portrait source: 1000 wide x 2000 tall, target slot 111x86 mm ratio.
    source_w, source_h = 1000.0, 2000.0
    target_w, target_h = 111.0, 86.0
    scale = compute_cover_scale(source_w, source_h, target_w, target_h)
    scaled_w, scaled_h = scaled_size(source_w, source_h, scale)
    assert scaled_w == pytest.approx(target_w, abs=1e-6)
    assert scaled_h >= target_h
    overflow_w, overflow_h = compute_overflow(source_w, source_h, target_w, target_h)
    assert overflow_w == pytest.approx(0.0, abs=1e-6)
    assert overflow_h > 0


def test_landscape_cover_scaling_fills_height_and_overflows_width():
    # Landscape source: 2000 wide x 1000 tall.
    source_w, source_h = 2000.0, 1000.0
    target_w, target_h = 111.0, 86.0
    scale = compute_cover_scale(source_w, source_h, target_w, target_h)
    scaled_w, scaled_h = scaled_size(source_w, source_h, scale)
    assert scaled_h == pytest.approx(target_h, abs=1e-6)
    assert scaled_w >= target_w
    overflow_w, overflow_h = compute_overflow(source_w, source_h, target_w, target_h)
    assert overflow_h == pytest.approx(0.0, abs=1e-6)
    assert overflow_w > 0


def test_square_image_cover_scaling_uses_general_formula():
    # Square source onto a wider-than-tall slot (111x86): width should be
    # the binding constraint, producing vertical overflow after scaling.
    source_w, source_h = 1000.0, 1000.0
    target_w, target_h = 111.0, 86.0
    overflow_w, overflow_h = compute_overflow(source_w, source_h, target_w, target_h)
    assert overflow_w == pytest.approx(0.0, abs=1e-6)
    assert overflow_h > 0

    # Square source onto a taller-than-wide slot: height binds, producing
    # horizontal overflow.
    overflow_w2, overflow_h2 = compute_overflow(source_w, source_h, 86.0, 111.0)
    assert overflow_h2 == pytest.approx(0.0, abs=1e-6)
    assert overflow_w2 > 0


def test_cover_never_distorts_aspect_ratio_independently():
    # The same uniform scale must apply to both axes.
    source_w, source_h = 1234.0, 987.0
    target_w, target_h = 111.0, 86.0
    scale = compute_cover_scale(source_w, source_h, target_w, target_h)
    scaled_w, scaled_h = scaled_size(source_w, source_h, scale)
    assert scaled_w / source_w == pytest.approx(scaled_h / source_h)


# ---------------------------------------------------------------------------
# Allowed movement axes
# ---------------------------------------------------------------------------


def test_allowed_movement_axes_portrait_only_vertical():
    overflow_w, overflow_h = compute_overflow(1000, 2000, 111.0, 86.0)
    allow_x, allow_y = allowed_movement_axes(overflow_w, overflow_h)
    assert allow_x is False
    assert allow_y is True


def test_allowed_movement_axes_landscape_only_horizontal():
    overflow_w, overflow_h = compute_overflow(2000, 1000, 111.0, 86.0)
    allow_x, allow_y = allowed_movement_axes(overflow_w, overflow_h)
    assert allow_x is True
    assert allow_y is False


# ---------------------------------------------------------------------------
# Normalized position clamping and crop-box math
# ---------------------------------------------------------------------------


def test_clamp_normalized_within_range_unchanged():
    assert clamp_normalized(0.5) == pytest.approx(0.5)
    assert clamp_normalized(-0.75) == pytest.approx(-0.75)


def test_clamp_normalized_clamps_out_of_range_values():
    assert clamp_normalized(5.0) == 1.0
    assert clamp_normalized(-5.0) == -1.0
    assert clamp_normalized(1.0) == 1.0
    assert clamp_normalized(-1.0) == -1.0


@pytest.mark.parametrize("norm_x,norm_y", [(-1.0, -1.0), (0.0, 0.0), (1.0, 1.0), (-0.3, 0.6)])
def test_crop_box_never_exceeds_source_bounds(norm_x, norm_y):
    source_w, source_h = 3000.0, 2000.0
    target_w, target_h = 111.0, 86.0
    left, top, right, bottom = crop_box_in_source_px(
        source_w, source_h, target_w, target_h, norm_x, norm_y
    )
    assert left >= -1e-6
    assert top >= -1e-6
    assert right <= source_w + 1e-6
    assert bottom <= source_h + 1e-6
    assert right > left
    assert bottom > top


def test_crop_box_center_position_is_centered():
    source_w, source_h = 4000.0, 2000.0  # landscape, overflow on width
    target_w, target_h = 111.0, 86.0
    left, top, right, bottom = crop_box_in_source_px(source_w, source_h, target_w, target_h, 0.0, 0.0)
    overflow_w, _ = compute_overflow(source_w, source_h, target_w, target_h)
    scale = compute_cover_scale(source_w, source_h, target_w, target_h)
    expected_left = (overflow_w / 2.0) / scale
    assert left == pytest.approx(expected_left, rel=1e-6)


def test_crop_box_out_of_range_normalized_values_are_clamped_and_stay_in_bounds():
    source_w, source_h = 4000.0, 2000.0
    target_w, target_h = 111.0, 86.0
    left, top, right, bottom = crop_box_in_source_px(
        source_w, source_h, target_w, target_h, 999.0, -999.0
    )
    assert left >= -1e-6
    assert right <= source_w + 1e-6


def test_normalized_delta_from_drag_no_overflow_returns_zero():
    assert normalized_delta_from_drag(50.0, 0.0) == 0.0


def test_normalized_delta_from_drag_direction_and_magnitude():
    # Dragging toward positive X by the full half-overflow should move the
    # normalized position by exactly -1.0 (fully toward the opposite end).
    overflow_px = 200.0
    delta = normalized_delta_from_drag(100.0, overflow_px)
    assert delta == pytest.approx(-1.0)


def test_requires_upscaling_true_when_source_smaller_than_target():
    assert requires_upscaling(100, 80, 1000, 800) is True


def test_requires_upscaling_false_when_source_larger_than_target():
    assert requires_upscaling(4000, 3000, 1000, 800) is False
