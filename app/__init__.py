"""Collage Maker application package.

This package separates pure geometry/image-math (layout_engine, models,
constants, image_renderer) from the PySide6 presentation layer
(main_window, selection_page, editor_page, image_slot_widget) so the
core logic can be unit tested without a running Qt application.
"""
