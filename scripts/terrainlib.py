"""Shared terrain helpers: registry, dual-grid Wang masks, layered autotiling.

Rendering model (the "dual grid" used by e.g. Oskar Stalberg's Townscaper and
many tile-blending RTS renderers):

* Game logic stores ONE terrain per map cell (96 x 64 cells of 32 px).
* The display grid is offset by half a cell: display tile (i, j) covers the
  centres of cells (i-1, j-1) NW, (i, j-1) NE, (i-1, j) SW, (i, j) SE, so the
  display grid is (W+1) x (H+1) tiles drawn at (-16, -16).
* Each terrain has 16 overlay tiles, one per 4-bit corner mask
  (NW=8, NE=4, SW=2, SE=1; 15 = full tile). A display tile draws its lowest-
  priority corner terrain as a full tile, then each higher-priority terrain
  with the mask of corners whose priority is >= its own. At most 4 layers.

Any two terrains can therefore touch, and flipping one cell only redraws the
4 display tiles around it.
"""
from __future__ import annotations

import pathlib

import numpy as np
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
TILE = 32
BITS = {"NW": 8, "NE": 4, "SW": 2, "SE": 1}


def registry(path=ROOT / "prompts/terrain_ice.yaml"):
    cfg = yaml.safe_load(pathlib.Path(path).read_text())
    ts = cfg["terrains"]
    for i, t in enumerate(ts):
        t["index"] = i
        t["priority"] = i
        t.setdefault("contestable", True)
    return cfg, ts


def corners_of(mask):
    return [(mask >> 3) & 1, (mask >> 2) & 1, (mask >> 1) & 1, mask & 1]  # NW NE SW SE


def tileable_noise(seed, size=TILE, periods=(4, 8), weights=(0.65, 0.35)):
    """Smooth value noise that wraps every `size` pixels, scaled to about [-1, 1]."""
    rng = np.random.default_rng(seed)
    out = np.zeros((size, size))
    ys, xs = np.mgrid[0:size, 0:size] + 0.5
    for p, w in zip(periods, weights):
        g = rng.random((p, p))
        cell = size / p
        fx, fy = xs / cell - 0.5, ys / cell - 0.5
        x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
        tx, ty = fx - x0, fy - y0
        tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
        a = g[y0 % p, x0 % p]
        b = g[y0 % p, (x0 + 1) % p]
        c = g[(y0 + 1) % p, x0 % p]
        d = g[(y0 + 1) % p, (x0 + 1) % p]
        out += w * ((a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty)
    out -= out.mean()
    return out / np.abs(out).max()


def field(mask, noise, amp, pad=4):
    """Inside/outside of one Wang tile on a padded grid (pad px each side).

    Bilinear interpolation of the 4 corners plus wrapped noise: continuous
    across tile edges for any corner combination, so tiles join seamlessly.
    """
    nw, ne, sw, se = corners_of(mask)
    r = np.arange(-pad, TILE + pad)
    ys, xs = np.meshgrid(r, r, indexing="ij")
    u, v = (xs + 0.5) / TILE, (ys + 0.5) / TILE
    f = nw * (1 - u) * (1 - v) + ne * u * (1 - v) + sw * (1 - u) * v + se * u * v
    g = f + amp * noise[ys % TILE, xs % TILE]
    return g > 0.5


def layers_for(corners, prio):
    """corners: 4 terrain indices (NW NE SW SE). Returns [(terrain, mask)] bottom-up."""
    out = []
    for t in sorted(set(corners), key=lambda t: prio[t]):
        m = 0
        for k, c in enumerate(corners):
            if prio[c] >= prio[t]:
                m |= 8 >> k
        out.append((t, 15 if not out else m))
    return out


def display_layers(grid, prio):
    """grid: H x W array of terrain indices. Returns a list of 4 arrays
    (H+1) x (W+1) of (terrain*16+mask) or -1, bottom layer first."""
    H, W = grid.shape
    L = [np.full((H + 1, W + 1), -1, dtype=np.int32) for _ in range(4)]
    for j in range(H + 1):
        for i in range(W + 1):
            def cell(x, y):
                return grid[min(max(y, 0), H - 1), min(max(x, 0), W - 1)]
            cs = [cell(i - 1, j - 1), cell(i, j - 1), cell(i - 1, j), cell(i, j)]
            for k, (t, m) in enumerate(layers_for(cs, prio)):
                L[k][j, i] = t * 16 + m
    return L
