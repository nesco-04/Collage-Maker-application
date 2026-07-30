# Collage Maker

A Windows desktop application for building 5x7 or 8x10 inch print collages
from 111 mm x 86 mm photo slots. Built with **PySide6** (GUI) and
**Pillow** (image processing), with all layout/crop math implemented as
pure, unit-tested functions.

## Features

- Choose a **5 x 7 in** (2 slots, portrait) or **8 x 10 in** (4 slots,
  landscape) print layout.
- Import 1 to N photos (JPEG, PNG, TIFF, BMP, WebP) via the native Windows
  file picker.
- Each photo automatically fills its slot ("cover" scaling) without
  distortion, then can be dragged, arrow-key-nudged, replaced, or removed.
- The entire print stays visible and correctly proportioned as you resize
  the window.
- Export renders directly from your original files at exactly the correct
  pixel size for **300 DPI** print output -- never from a preview or
  thumbnail.

## Project layout

```
main.py                  Application entry point
app/
  constants.py            Centralized physical/rendering constants
  models.py                Data model (CollageState, ImageAssignment, ...)
  layout_engine.py         Pure geometry/crop math (unit tested)
  image_renderer.py        Pillow I/O: loading, preview cache, export render
  image_slot_widget.py      Interactive per-slot Qt widget
  selection_page.py         Page 1: print size + photo import
  editor_page.py            Page 2: responsive collage editor + export
  main_window.py            Page navigation / state ownership
tests/
  test_layout_engine.py     Geometry/crop math tests
  test_image_scaling.py     Pillow rendering/export tests
requirements.txt
run_app.bat                Development launcher (creates venv if needed)
build_windows.bat          Builds a standalone .exe with PyInstaller
collage_app.spec           PyInstaller build specification
```

## Requirements

- Windows 10/11
- Python 3.12+ (3.13/3.14 also supported)

## Setup

```bat
python -m venv .venv
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt
```

Or simply double-click / run `run_app.bat`, which creates the virtual
environment and installs dependencies automatically on first run.

## Running from source

```bat
run_app.bat
```

or, with the virtual environment already active:

```bat
python main.py
```

This opens the Collage Maker window. No console/server process is
involved -- it is a normal desktop GUI application.

## Running the tests

```bat
.venv\Scripts\pytest -q
```

All layout, cover-scaling, crop-clamping, and export-dimension logic in
`app/layout_engine.py` and `app/image_renderer.py` is covered by pure,
GUI-independent unit tests in `tests/`.

## Building a standalone Windows executable

```bat
build_windows.bat
```

This installs PyInstaller (if not already present) and runs:

```bat
pyinstaller collage_app.spec --noconfirm
```

The result is `dist\CollageMaker\CollageMaker.exe` -- a windowed
application (no console window) that runs on a machine **without Python
installed**. Distribute the entire `dist\CollageMaker\` folder.

## How to use the app

1. **Selection page**: pick 5x7 or 8x10, click **Browse for Photos...**,
   select 1 to the layout's maximum number of images, then **Continue**.
   Highlight one or more photos and use **Remove Selected**, or use
   **Clear All** to empty the selection.
2. **Editor page**:
   - Click a slot to select it (blue outline).
   - Drag directly on an image to reposition it within its slot. A
     portrait photo can be dragged vertically; a landscape photo can be
     dragged horizontally; the cursor and allowed drag direction adapt to
     each photo's actual overflow.
   - Use arrow keys to nudge the selected image's position.
   - **Center Selected Image** recenters the current slot's photo.
   - **Reset All Positions** recenters every photo.
   - **Replace Image...** / **Remove Image** change or clear the selected
     slot.
   - **Back** returns to the selection page without losing your photo
     list or crop positions.
   - **Restart** discards the current collage and returns to a clean
     selection page with no photos selected.
   - **Export...** opens a Save As dialog (PNG/TIFF/JPEG) and renders the
     final collage directly from your original files at 300 DPI.

## Image-scaling and crop-position mathematics

**Cover scaling.** For a slot of size `(target_w, target_h)` and a source
image of size `(source_w, source_h)`, the uniform scale factor applied is:

```
scale = max(target_w / source_w, target_h / source_h)
```

This guarantees the scaled image is at least as large as the slot on both
axes (no gaps), while never scaling the two axes independently (no
distortion). After scaling, exactly one axis will have zero or
near-zero overflow (the "binding" axis) and the other will typically
overflow -- that overflowing axis is the one the user can drag:

- **Portrait photo** (taller than wide): width binds to the slot's width,
  height overflows -> vertical dragging only.
- **Landscape photo** (wider than tall): height binds to the slot's
  height, width overflows -> horizontal dragging only.
- **Square/unusual photo**: whichever axis overflows (determined
  generically by the same formula) becomes draggable; if rounding leaves
  both axes with a hair of overflow, both are draggable.

**Normalized crop position.** Position is stored as `norm_x, norm_y` in
`[-1.0, 1.0]`, not in pixels, so resizing the preview never changes the
stored crop. The crop window's top-left corner, in the *cover-scaled*
image's coordinate space, is:

```
overflow_w = scaled_w - target_w   (>= 0)
overflow_h = scaled_h - target_h   (>= 0)

crop_left = (overflow_w / 2) * (1 + norm_x)
crop_top  = (overflow_h / 2) * (1 + norm_y)
```

Because `norm_x`/`norm_y` are clamped to `[-1.0, 1.0]`, `crop_left` is
always within `[0, overflow_w]` and `crop_top` within `[0, overflow_h]` --
the crop window can mathematically never extend past the scaled image's
edges, so **no blank space can ever appear inside a populated slot**.

**Rendering the crop.** Rather than resizing the whole source image and
then cropping it (which wastes a full extra resample of the entire
image), the crop window is converted back into the *original* source
image's pixel coordinates by dividing by `scale`, the source is cropped
directly, and only that (much smaller, once cover-scale is undone)
region is resized with **LANCZOS** to the exact target pixel size. Preview
rendering and final export rendering call this exact same math (with
different target pixel sizes -- a small preview size vs. the full 300 DPI
export size), so what you see while dragging is guaranteed to match the
exported result.

**Export sizing.** The export canvas is sized in pixels from the
millimeter print dimensions and the export DPI:

```
pixels = round((millimeters / 25.4) * dpi)
```

Slot pixel rectangles are derived from rounding each slot's absolute
start/end coordinates (not width/height independently), so adjacent slots
always tile with no 1-pixel gaps or overlaps.

## Acceptance criteria checklist

| Criterion | Status |
| --- | --- |
| Selecting 5x7 shows a maximum of 2 images | `SelectionPage._max_slot_count`, `compute_canvas_layout` |
| Selecting 8x10 shows a maximum of 4 images | Same as above |
| Continue works with fewer than the maximum images | `SelectionPage._revalidate` only requires `1 <= count <= max` |
| Portrait images fill slot width, reposition vertically | `compute_cover_scale` + `allowed_movement_axes` + drag/nudge logic |
| Landscape images fill slot height, reposition horizontally | Same |
| No repositioning exposes blank space | `crop_box_in_source_px` clamps via `norm_x`/`norm_y in [-1, 1]` |
| Images are never distorted | Single uniform `scale` applied to both axes |
| Entire print remains visible while resizing | `AspectRatioContainer` + `CanvasWidget._relayout` |
| Preview resizing does not change stored crop | Positions stored as normalized values, independent of pixel size |
| Export uses original files, not previews | `render_slot_image` always calls `load_corrected_image` on `assignment.source_path` |
| Correct aspect ratio and 300 DPI pixel dimensions | `export_canvas_pixel_size`, tested in `test_layout_engine.py` |
| Empty slots export as white | `render_collage` only pastes populated slots onto a white canvas |
| Editor decorations never appear in export | Borders/selection outlines are drawn only in `ImageSlotWidget.paintEvent`, never in `image_renderer.py` |
| `python main.py` launches the app | Verified |
| PyInstaller build produces a standalone .exe | `collage_app.spec` / `build_windows.bat` |

## Privacy

All image processing happens locally. The application never uploads,
transmits, or shares your photos or metadata.
