"""Turn small satellite arrays into transparent PNG map layers (BUILD_SPEC §4, layer 2).

Each pixel is coloured from a fixed, documented colour ramp; masked pixels (cloud, shadow, water, no data) are
fully transparent. PNGs stay at the satellite's native 10 m pixel size (about 50 × 50 pixels for the 500 m box),
so they are only a few kilobytes; the browser scales them up with crisp pixel edges.
"""

from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image

# Colour ramps from BUILD_SPEC §4 (low to high).
CHANGE_EDGES = [-0.20, -0.05, 0.05, 0.20]
CHANGE_COLORS = ["#B2182B", "#EF8A62", "#F0F0F0", "#91CF60", "#1A9850"]
NDVI_EDGES = [0.15, 0.30, 0.45, 0.60]
NDVI_COLORS = ["#A50026", "#F46D43", "#FEE08B", "#A6D96A", "#1A9850"]
TRUECOLOR_MAX_DN = 3000.0   # reflectance 0-0.3 (DN after offset removal) maps to 0-255
TRUECOLOR_GAMMA = 1.2


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    """Convert '#RRGGBB' into an (r, g, b) tuple."""
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _png_base64(rgba: np.ndarray) -> str:
    """Encode an H×W×4 uint8 array as an optimised PNG and return it base64-encoded."""
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def ramp_rgba(values: np.ndarray, valid: np.ndarray, edges: list[float], colors: list[str],
              right: bool) -> np.ndarray:
    """Colour each valid pixel by which bin of `edges` its value falls in; invalid pixels become transparent.

    `right=True` means a value equal to an edge belongs to the lower bin (used for the "≤ −0.20" change ramp);
    `right=False` puts it in the upper bin (used for the "< 0.15" green-cover ramp).
    """
    ok = valid & np.isfinite(values)
    bins = np.digitize(np.where(ok, values, 0.0), edges, right=right)
    palette = np.array([_rgb(c) + (255,) for c in colors], dtype=np.uint8)
    rgba = palette[bins]
    rgba[~ok] = (0, 0, 0, 0)
    return rgba


def change_png(delta: np.ndarray, valid: np.ndarray, edges: list[float] | None = None) -> str:
    """PNG for "change vs last year" (ΔNDVI, or ΔVH dB for radar with its own edges)."""
    return _png_base64(ramp_rgba(delta, valid, edges or CHANGE_EDGES, CHANGE_COLORS, right=True))


def ndvi_png(ndvi: np.ndarray, valid: np.ndarray) -> str:
    """PNG for "green cover now" (NDVI)."""
    return _png_base64(ramp_rgba(ndvi, valid, NDVI_EDGES, NDVI_COLORS, right=False))


def truecolor_png(red: np.ndarray, green: np.ndarray, blue: np.ndarray, valid: np.ndarray) -> str:
    """Natural-colour PNG from Sentinel-2 B04/B03/B02 (DN after offset), scaled 0-3000 with gamma 1.2."""
    stack = np.stack([red, green, blue], axis=-1).astype("float64")
    scaled = np.clip(np.nan_to_num(stack, nan=0.0) / TRUECOLOR_MAX_DN, 0.0, 1.0) ** (1.0 / TRUECOLOR_GAMMA)
    rgba = np.zeros(stack.shape[:2] + (4,), dtype=np.uint8)
    rgba[..., :3] = (scaled * 255).round().astype(np.uint8)
    rgba[..., 3] = np.where(valid, 255, 0)
    return _png_base64(rgba)


def masked_pct(valid: np.ndarray) -> float:
    """Share of the box (in %) hidden by cloud, shadow, water or missing data."""
    return round(100.0 * (1.0 - float(valid.mean())), 1) if valid.size else 100.0
