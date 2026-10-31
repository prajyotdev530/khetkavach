"""Unit tests for the overlay renderer: a small known array gives the expected colours, and masked pixels are
fully transparent (BUILD_SPEC §12)."""

import base64
import io

import numpy as np
from PIL import Image

from app.engine import overlay


def decode(png_b64: str) -> np.ndarray:
    """Turn a base64 PNG back into an RGBA array."""
    return np.array(Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGBA"))


def test_change_ramp_colours_and_mask():
    """Each ΔNDVI bin maps to its documented colour; the masked pixel is transparent."""
    values = np.array([[-0.30, -0.10, 0.0], [0.10, 0.30, 0.0]])
    valid = np.array([[True, True, True], [True, True, False]])
    img = decode(overlay.change_png(values, valid))
    expected = ["#B2182B", "#EF8A62", "#F0F0F0", "#91CF60", "#1A9850"]
    got = [img[0, 0], img[0, 1], img[0, 2], img[1, 0], img[1, 1]]
    for pixel, hex_colour in zip(got, expected):
        assert tuple(pixel[:3]) == overlay._rgb(hex_colour)
        assert pixel[3] == 255
    assert img[1, 2][3] == 0


def test_ndvi_ramp_lower_bound_is_inclusive():
    """Green-cover bins: <0.15, 0.15-0.30, ... so exactly 0.15 is the second colour."""
    img = decode(overlay.ndvi_png(np.array([[0.10, 0.15, 0.70]]), np.ones((1, 3), bool)))
    assert tuple(img[0, 0][:3]) == overlay._rgb("#A50026")
    assert tuple(img[0, 1][:3]) == overlay._rgb("#F46D43")
    assert tuple(img[0, 2][:3]) == overlay._rgb("#1A9850")


def test_nan_values_are_transparent_and_masked_pct():
    """NaN pixels are transparent even if flagged valid; masked_pct counts hidden pixels."""
    img = decode(overlay.ndvi_png(np.array([[np.nan, 0.5]]), np.ones((1, 2), bool)))
    assert img[0, 0][3] == 0 and img[0, 1][3] == 255
    assert overlay.masked_pct(np.array([True, False, False, True])) == 50.0


def test_truecolor_scaling():
    """DN 3000 saturates to white; DN 0 is black; masked pixels transparent."""
    red = np.array([[3000.0, 0.0, 1500.0]])
    img = decode(overlay.truecolor_png(red, red, red, np.array([[True, True, False]])))
    assert tuple(img[0, 0]) == (255, 255, 255, 255)
    assert tuple(img[0, 1]) == (0, 0, 0, 255)
    assert img[0, 2][3] == 0
