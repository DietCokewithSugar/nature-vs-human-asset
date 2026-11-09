"""Build the layered terrain atlas from the PixelLab base tiles.

Usage: python scripts/build_terrain_atlas.py

Inputs : terrain/raw/<set>.png|json (scripts/generate_terrain.py) and the
         `terrains` registry in prompts/terrain_ice.yaml.
Outputs: terrain/ice_age.png       one row per terrain (draw order), 19 columns:
                                   0-15 Wang overlay by corner mask (15 = full),
                                   16-18 extra full-tile variants
         terrain/ice_age_n.png     matching normal map (flat, rims tilted)
         terrain/ice_age_decals.png erosion / reclaim decals, one row per
                                   (from -> to) conversion, columns:
                                   33% v0, 33% v1, 66% v0, 66% v1
         terrain/ice_age.json      registry + atlas layout
         terrain/ice_age.tsj       Tiled tileset for the atlas
         preview/terrain_ice_age.png  contact sheet

Edges are generated, not drawn by hand: each overlay is the terrain's own
seamless base texture cut by a noisy mask (tidy for human ground, ragged for
nature), with an inner rim (soft / raised / stone-lined) and a 3/4 drop
shadow cast to the south-east (light from the top-left, as in the art plan).
"""
import json
import pathlib

import numpy as np
from PIL import Image

from terrainlib import ROOT, TILE, corners_of, field, registry, tileable_noise

OUT = ROOT / "terrain"
COLS = 19
PAD = 4


def load_base(src):
    set_id, which = src.split(".")
    meta = json.loads((OUT / "raw" / f"{set_id}.json").read_text())
    atlas = Image.open(OUT / "raw" / f"{set_id}.png").convert("RGBA")
    want = "lower" if which == "lower" else "upper"
    for t in meta["tiles"]:
        if all(v == want for v in t["corners"].values()):
            tile = atlas.crop((t["x"], t["y"], t["x"] + TILE, t["y"] + TILE))
            return np.array(tile).astype(np.float32), {"set": set_id, "tileset_id": meta["tileset_id"],
                                                       "tile_id": t["id"], "seed": meta["request"]["seed"],
                                                       "description": meta["request"][f"{want}_description"]}
    raise SystemExit(f"no full {want} tile in {set_id}")


def variants(base, seed, n=3, border=3):
    """Full-tile variants: swap a few interior patches (borders untouched, so
    every variant still tiles seamlessly with the base and with each other)."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        v = base.copy()
        for _ in range(4):
            best = None
            for _ in range(40):
                s = int(rng.integers(6, 11))
                sx, sy = rng.integers(border, TILE - border - s, size=2)
                dx, dy = rng.integers(border, TILE - border - s, size=2)
                if abs(sx - dx) + abs(sy - dy) < 6:
                    continue
                patch = v[sy:sy + s, sx:sx + s]
                # seam cost: patch border vs. the pixels just outside the destination
                cost = (np.abs(patch[0] - v[dy - 1, dx:dx + s]).sum() + np.abs(patch[-1] - v[dy + s, dx:dx + s]).sum()
                        + np.abs(patch[:, 0] - v[dy:dy + s, dx - 1]).sum() + np.abs(patch[:, -1] - v[dy:dy + s, dx + s]).sum())
                if best is None or cost < best[0]:
                    best = (cost, patch.copy(), dx, dy, s)
            _, patch, dx, dy, s = best
            v[dy:dy + s, dx:dx + s] = patch
        out.append(v)
    return out


def stone_texture(seed):
    """Tileable cobbles for the stone-lined (human) stream bank."""
    rng = np.random.default_rng(seed)
    pts = rng.random((26, 2)) * TILE
    shade = rng.uniform(0.75, 1.05, len(pts))
    ys, xs = np.mgrid[0:TILE, 0:TILE] + 0.5
    d = []
    for px, py in pts:
        dx = np.abs(xs - px); dx = np.minimum(dx, TILE - dx)
        dy = np.abs(ys - py); dy = np.minimum(dy, TILE - dy)
        d.append(np.hypot(dx, dy))
    d = np.stack(d)
    order = np.argsort(d, axis=0)
    d1 = np.take_along_axis(d, order[:1], 0)[0]
    d2 = np.take_along_axis(d, order[1:2], 0)[0]
    base = np.array([150, 146, 138], np.float32)
    col = base[None, None] * shade[order[0]][..., None]
    col[(d2 - d1) < 1.1] = [62, 58, 56]
    hl = (ys - pts[order[0], 1]) < -1.5  # upper part of each stone catches the light
    col[hl & ((d2 - d1) >= 1.1)] *= 1.12
    return np.clip(col, 0, 255)


def overlay(base, mask, edge, noise, stone):
    rgba = np.zeros((TILE, TILE, 4), np.float32)
    if mask == 0:
        return rgba, np.zeros((TILE, TILE), np.float32)
    ins = field(mask, noise, edge["amp"], PAD)
    core = ins[PAD:PAD + TILE, PAD:PAD + TILE]
    rgba[core] = base[core]
    tilt = np.zeros((TILE, TILE), np.float32)  # -1 shadowed rim .. +1 lit rim, for the normal map

    def shifted(dy, dx):  # ins[y - dy, x - dx] for the tile window
        return ins[PAD - dy:PAD - dy + TILE, PAD - dx:PAD - dx + TILE]

    out_s = core & ~shifted(-1, 0)  # pixel below is outside -> south-facing edge
    out_e = core & ~shifted(0, -1)
    out_n = core & ~shifted(1, 0)
    out_w = core & ~shifted(0, 1)
    rim = edge["rim"]
    c = rgba[..., :3]
    if rim == "soft":
        c[out_s | out_e] *= 0.82
        c[(out_n | out_w) & ~(out_s | out_e)] = np.minimum(255, c[(out_n | out_w) & ~(out_s | out_e)] * 1.1 + 6)
    elif rim == "raised":
        s2 = core & ~shifted(-2, 0) & ~out_s
        c[out_s] *= 0.55
        c[s2] *= 0.75
        c[out_e & ~out_s] *= 0.72
        lit = (out_n | out_w) & ~(out_s | out_e)
        c[lit] = np.minimum(255, c[lit] * 1.18 + 14)
        tilt[out_s | s2 | out_e] = -1
        tilt[lit] = 1
    elif rim == "stone":
        band = np.zeros_like(core)
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                if abs(dy) + abs(dx) <= 3:
                    band |= core & ~shifted(dy, dx)
        c[band] = stone[band]
        edge1 = out_s | out_e | out_n | out_w
        c[edge1] = [48, 44, 42]
        tilt[band & ~edge1] = 0.6
    rgba[core, 3] = 255
    # drop shadow, cast down and slightly right
    s = edge.get("shadow", 0)
    if s:
        sh = np.zeros((TILE, TILE), np.float32)
        for k in range(1, s + 1):
            hit = shifted(k, (k + 1) // 2) & ~core
            sh = np.maximum(sh, hit * (0.42 - 0.08 * (k - 1)))
        put = (sh > 0) & ~core
        rgba[put, :3] = [12, 16, 28]
        rgba[put, 3] = sh[put] * 255
    return rgba, tilt


def decal(src_tex, dst_tex, seed, coverage):
    """Patches of the target terrain growing on a cell (33% / 66% conversion)."""
    n = tileable_noise(seed, periods=(4, 8, 16), weights=(0.5, 0.3, 0.2))
    ys, xs = np.mgrid[0:TILE, 0:TILE] + 0.5
    edge = np.minimum(np.minimum(xs, TILE - xs), np.minimum(ys, TILE - ys))
    score = n + np.clip(edge / 7, 0, 1) * 0.9 - 0.9  # stay off the cell border
    thr = np.quantile(score, 1 - coverage)
    m = score > thr
    out = np.zeros((TILE, TILE, 4), np.float32)
    out[m, :3] = dst_tex[m, :3]
    out[m, 3] = 255
    below = np.zeros_like(m)
    below[1:] = m[:-1] & ~m[1:]
    out[below, :3] = [20, 18, 22]
    out[below, 3] = 110
    return out


def to_normal(tilt, alpha):
    n = np.zeros((TILE, TILE, 4), np.float32)
    n[..., 0] = 128
    n[..., 1] = 128 - tilt * 70  # lit rims face up (north), shadowed ones face south
    n[..., 2] = 255 - np.abs(tilt) * 40
    n[..., 3] = alpha
    return n


def main():
    cfg, terrains = registry()
    rows = len(terrains)
    atlas = np.zeros((rows * TILE, COLS * TILE, 4), np.float32)
    natlas = np.zeros_like(atlas)
    bases = {}
    meta_terrains = []
    for t in terrains:
        base, prov = load_base(t["source"])
        bases[t["id"]] = base
        noise = tileable_noise(1000 + t["index"] * 17)
        stone = stone_texture(77 + t["index"])
        r = t["index"] * TILE
        for m in range(16):
            ov, tilt = overlay(base, m, t["edge"], noise, stone)
            atlas[r:r + TILE, m * TILE:(m + 1) * TILE] = ov
            natlas[r:r + TILE, m * TILE:(m + 1) * TILE] = to_normal(tilt, ov[..., 3])
        for k, v in enumerate(variants(base, 500 + t["index"])):
            atlas[r:r + TILE, (16 + k) * TILE:(17 + k) * TILE] = v
            natlas[r:r + TILE, (16 + k) * TILE:(17 + k) * TILE] = to_normal(np.zeros((TILE, TILE)), v[..., 3])
        meta_terrains.append({
            "index": t["index"], "id": t["id"], "name": t["name"], "owner": t["owner"],
            "contestable": t["contestable"], "kind": t["kind"], "durability": t.get("durability"),
            "converts_to": t.get("converts_to"), "priority": t["priority"], "row": t["index"],
            "full": [15, 16, 17, 18], "edge": t["edge"], "source": prov,
        })
    Image.fromarray(atlas.astype(np.uint8)).save(OUT / "ice_age.png")
    Image.fromarray(natlas.astype(np.uint8)).save(OUT / "ice_age_n.png")

    # decals: from -> to conversions
    pairs = []
    for t in terrains:
        ct = t.get("converts_to")
        if isinstance(ct, dict):
            pairs += [(t["id"], v) for v in ct.values()]
        elif ct:
            pairs.append((t["id"], ct))
    dec = np.zeros((len(pairs) * TILE, 4 * TILE, 4), np.float32)
    for i, (a, b) in enumerate(pairs):
        for k, (cov, var) in enumerate([(0.2, 0), (0.2, 1), (0.48, 0), (0.48, 1)]):
            dec[i * TILE:(i + 1) * TILE, k * TILE:(k + 1) * TILE] = decal(bases[a], bases[b], 3000 + i * 7 + var, cov)
    Image.fromarray(dec.astype(np.uint8)).save(OUT / "ice_age_decals.png")

    meta = {
        "id": "ice_age", "tile": TILE, "columns": COLS, "rows": rows,
        "png": "ice_age.png", "normal": "ice_age_n.png",
        "wang_bits": {"NW": 8, "NE": 4, "SW": 2, "SE": 1},
        "frame": "row = terrain index; col 0-15 = overlay for corner mask; full tile = col 15 or a variant col 16-18",
        "layering": "dual grid offset (-16,-16); per display tile draw the lowest corner terrain full, then each "
                    "higher terrain with mask = corners whose priority >= its own (scripts/terrainlib.py)",
        "terrains": meta_terrains,
        "decals": {"png": "ice_age_decals.png", "columns": {"33": [0, 1], "66": [2, 3]},
                   "rows": [{"row": i, "from": a, "to": b} for i, (a, b) in enumerate(pairs)]},
    }
    (OUT / "ice_age.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")

    tiles = []
    for t in meta_terrains:
        for c in range(COLS):
            props = [{"name": "terrain", "type": "string", "value": t["id"]},
                     {"name": "mask", "type": "int", "value": c if c < 16 else 15}]
            tiles.append({"id": t["row"] * COLS + c, "properties": props})
    tsj = {"type": "tileset", "version": "1.10", "tiledversion": "1.11.0", "name": "ice_age_terrain",
           "image": "ice_age.png", "imagewidth": COLS * TILE, "imageheight": rows * TILE,
           "tilewidth": TILE, "tileheight": TILE, "columns": COLS, "tilecount": COLS * rows,
           "margin": 0, "spacing": 0, "tiles": tiles}
    (OUT / "ice_age.tsj").write_text(json.dumps(tsj, indent=1, ensure_ascii=False) + "\n")
    contact_sheet(atlas, dec, meta_terrains, pairs)
    print(f"atlas {COLS}x{rows}, decals {len(pairs)} conversions")


def contact_sheet(atlas, dec, terrains, pairs):
    from PIL import ImageDraw
    a = Image.fromarray(atlas.astype(np.uint8))
    d = Image.fromarray(dec.astype(np.uint8))
    W = 150 + a.width + 24 + d.width
    H = max(a.height, d.height) + 24
    out = Image.new("RGBA", (W, H), (58, 62, 70, 255))
    # checker under the atlas so transparency and shadows are visible
    ck = Image.new("RGBA", a.size)
    px = ck.load()
    for y in range(a.height):
        for x in range(a.width):
            px[x, y] = (96, 100, 108, 255) if ((x // 8) + (y // 8)) % 2 else (128, 132, 140, 255)
    ck.alpha_composite(a)
    out.paste(ck, (150, 24))
    dr = ImageDraw.Draw(out)
    for t in terrains:
        dr.text((6, 24 + t["row"] * TILE + 10), f"{t['row']:2d} {t['id']}", fill=(255, 255, 255, 255))
    for c in range(COLS):
        dr.text((150 + c * TILE + 8, 6), str(c), fill=(255, 255, 255, 255))
    out.paste(d, (150 + a.width + 24, 24), d)
    out.resize((W * 2, H * 2), Image.NEAREST).save(ROOT / "preview/terrain_ice_age.png")


if __name__ == "__main__":
    main()
