"""Build the fixed ice-age level (PRD section 4): 96 x 64 cells of 32 px.

Usage:
  python scripts/build_map.py layout   # (re)generate the layout -> maps/ice_age_layout.json
  python scripts/build_map.py build    # autotile + export + previews + checklist (default: both)

The layout is generated once from a fixed seed and then saved, so the map is
fixed, not random per game. maps/ice_age_layout.json is the editable source of
truth (terrain per cell + objects); `build` turns it into:

  maps/ice_age.tmj           Tiled map with embedded tilesets (Phaser 3 loads it with
                             this.load.tilemapTiledJSON); layers:
                               terrain   96x64 logic layer, one terrain per cell
                               ground0-3 97x65 dual-grid display layers, offset (-16,-16)
                               objects   volcanoes, resource points, trees, start zones,
                                         human start buildings (footprints only)
  maps/ice_age_preview.png   full-size render (3072 x 2048)
  maps/ice_age_overview.png  ownership / chunk / resource overview with legend
  maps/ice_age_check.md      PRD 4.2 acceptance checklist with measured values
"""
import json
import math
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from terrainlib import ROOT, TILE, display_layers, registry

W, H = 96, 64
SEED = 2026
MAPS = ROOT / "maps"
LAYOUT = MAPS / "ice_age_layout.json"

NATURE = [  # start zones, PRD 4.2: north-west, south-west, north centre, south coast
    {"name": "自然1", "c": (9, 12), "theme": "nw"},
    {"name": "自然2", "c": (9, 47), "theme": "sw"},
    {"name": "自然3", "c": (64, 8), "theme": "n"},
    {"name": "自然4", "c": (71, 53), "theme": "s"},
]
OUTPOSTS = [{"name": "前哨1", "c": (17, 28)}, {"name": "前哨2", "c": (25, 37)}]
MAIN = {"name": "人类主城", "c": (80, 28)}
NATURE_CELLS = 120          # PRD: about 120 cells per start zone
SAFE = 12                   # PRD: >= 12 cells from a nature start zone to human land (see check)
WEST_EDGE = 27              # main human land starts here (west of it: neutral forest + outposts)

# human start buildings (PRD 5.3): type, footprint, top-left cell
BUILDINGS = {
    "人类主城": [("岩洞", 3, 3, 84, 24), ("篝火营地", 2, 2, 76, 29), ("篝火营地", 2, 2, 86, 34),
              ("石屋", 2, 2, 79, 21), ("兽皮帐篷", 1, 1, 73, 25), ("兽皮帐篷", 1, 1, 81, 34),
              ("兽皮帐篷", 1, 1, 90, 29), ("兽皮帐篷", 1, 1, 77, 37)],
    "前哨1": [("篝火营地", 2, 2, 16, 27), ("兽皮帐篷", 1, 1, 19, 29), ("兽皮帐篷", 1, 1, 15, 30)],
    "前哨2": [("篝火营地", 2, 2, 24, 36), ("兽皮帐篷", 1, 1, 27, 38), ("兽皮帐篷", 1, 1, 23, 39)],
}


def value_noise(seed, cell=6.0):
    rng = np.random.default_rng(seed)
    gw, gh = int(W / cell) + 3, int(H / cell) + 3
    g = rng.random((gh, gw))
    ys, xs = np.mgrid[0:H, 0:W] + 0.5
    fx, fy = xs / cell, ys / cell
    x0, y0 = np.floor(fx).astype(int), np.floor(fy).astype(int)
    tx, ty = fx - x0, fy - y0
    tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
    v = (g[y0, x0] * (1 - tx) + g[y0, x0 + 1] * tx) * (1 - ty) + (g[y0 + 1, x0] * (1 - tx) + g[y0 + 1, x0 + 1] * tx) * ty
    return (v - 0.5) * 2


# ---------------------------------------------------------------- layout
def layout():
    _, terrains = registry()
    T = {t["id"]: t["index"] for t in terrains}
    rng = np.random.default_rng(SEED)
    ys, xs = np.mgrid[0:H, 0:W]
    n1, n2, n3 = value_noise(SEED + 1, 7), value_noise(SEED + 2, 4), value_noise(SEED + 3, 10)
    grid = np.full((H, W), T["x_forest"], np.int32)

    # sea along the south edge
    coast = 57.5 + 1.6 * np.sin(xs[0] / 9.0) + 1.2 * value_noise(SEED + 4, 8)[0]
    land = ys < coast[None, :]
    shallow_end = coast[None, :] + 2.5
    grid[~land] = T["x_shallow"]
    grid[ys >= shallow_end] = T["x_deep"]

    # nature start zones: the ~120 lowest-scoring cells of a noisy disc
    dist_nat = np.full((H, W), 1e9)
    nature = np.zeros((H, W), bool)
    for z in NATURE:
        cx, cy = z["c"]
        d = np.hypot(xs + 0.5 - cx, ys + 0.5 - cy)
        dist_nat = np.minimum(dist_nat, d)
        score = d / 6.4 + 0.22 * n2
        score[~land & (ys >= shallow_end)] = 1e9
        idx = np.argsort(score, axis=None)[:NATURE_CELLS]
        m = np.zeros(H * W, bool)
        m[idx] = True
        z["mask"] = m.reshape(H, W)
        nature |= z["mask"]

    # human land: east of the forest belt, never within SAFE cells of a nature zone centre
    human = land & ((xs + 2.2 * n1) >= WEST_EDGE) & (dist_nat + 1.6 * (n2 + 1) >= SAFE + 0.5) & (dist_nat >= SAFE)
    for o in OUTPOSTS:
        cx, cy = o["c"]
        human |= (np.hypot(xs + 0.5 - cx - 1, ys + 0.5 - cy - 1) + 0.9 * n2 < 4.4) & land
    human &= ~nature

    # human ground: swept snow, trampled mud around the camps, levelled camp ground under buildings
    grid[human] = T["h_snow"]
    mud = human & ((n3 > 0.4) | (np.hypot(xs - MAIN["c"][0], ys - MAIN["c"][1]) + 3 * n2 < 9))
    grid[mud] = T["h_mud"]
    for site, blds in BUILDINGS.items():
        for _, bw, bh, bx, by in blds:
            grid[by - 1:by + bh + 1, bx - 1:bx + bw + 1][human[by - 1:by + bh + 1, bx - 1:bx + bw + 1]] = T["h_camp"]
    # gravel shore along the human coast
    shore = human & (ys >= coast[None, :] - 2.2)
    grid[shore] = T["h_shore"]
    # stone-lined stream from the north edge to the sea
    rx = 45 + 2.5 * np.sin(np.arange(H) / 7.0) + 1.5 * np.sin(np.arange(H) / 3.1)
    for y in range(H):
        for x in (int(round(rx[y])), int(round(rx[y])) + 1):
            if human[y, x]:
                grid[y, x] = T["h_weir"]

    # nature zones by theme
    for z in NATURE:
        m = z["mask"]
        cx, cy = z["c"]
        dy, dx = ys + 0.5 - cy, xs + 0.5 - cx
        th = z["theme"]
        grid[m] = T["n_tundra"]
        if th == "nw":
            grid[m & (dy + 2 * n2 < -2.5)] = T["n_glacier"]
            grid[m & (dy + 2 * n2 > 1.5)] = T["n_steppe"]
            grid[m & (np.hypot(dx - 2, dy - 1) < 1.6)] = T["n_stream"]
        elif th == "sw":
            grid[m] = T["n_steppe"]
            grid[m & (dx + 2 * n2 > 2.5)] = T["n_rocks"]
            grid[m & (np.abs(dx + 0.5 * dy + 1) < 0.9) & (dy > -3)] = T["n_stream"]
        elif th == "n":
            grid[m & (dy + 2 * n2 < -3)] = T["n_glacier"]
            grid[m & (dx + 2 * n2 > 2)] = T["n_rocks"]
            grid[m & (np.hypot(dx + 2.5, dy - 1.5) < 1.5)] = T["n_stream"]
        elif th == "s":
            grid[m] = T["n_steppe"]
            grid[m & (ys >= coast[None, :] - 2.2)] = T["n_beach"]
            grid[m & ~land] = T["n_beach"]
            grid[m & (np.abs(dx - 0.2 * dy) < 0.8) & (dy > -4)] = T["n_stream"]
            grid[m & (dx + dy * 0.3 + 2 * n2 < -3.5) & (grid == T["n_steppe"])] = T["n_tundra"]

    # objects ---------------------------------------------------------------
    objs = []
    for z in NATURE:
        objs.append({"class": "nature_start", "name": z["name"], "nest": list(z["c"]),
                     "cells": int(z["mask"].sum())})
    for site, blds in BUILDINGS.items():
        for kind, bw, bh, bx, by in blds:
            objs.append({"class": "human_building", "site": site, "type": kind, "cell": [bx, by], "size": [bw, bh]})
    objs.append({"class": "human_start", "name": MAIN["name"], "c": list(MAIN["c"])})
    for o in OUTPOSTS:
        objs.append({"class": "human_start", "name": o["name"], "c": list(o["c"])})

    # volcanoes: one each side of the midline, equidistant from nature and human
    bcent = [(b["cell"][0] + b["size"][0] / 2, b["cell"][1] + b["size"][1] / 2) for b in objs if b["class"] == "human_building"]
    nat_cells = np.argwhere(nature)
    taken = set()
    for target in [(23, 15), (23, 46)]:
        best = None
        for vy in range(target[1] - 7, target[1] + 8):
            for vx in range(target[0] - 7, target[0] + 8):
                foot = grid[vy:vy + 3, vx:vx + 3]
                ring = (slice(vy - 2, vy + 5), slice(vx - 2, vx + 5))
                if foot.shape != (3, 3) or (foot != T["x_forest"]).any() or human[ring].any() or nature[ring].any():
                    continue
                c = (vx + 1.5, vy + 1.5)
                dn = np.hypot(nat_cells[:, 1] + 0.5 - c[0], nat_cells[:, 0] + 0.5 - c[1]).min()
                dh = min(math.hypot(bx - c[0], by - c[1]) for bx, by in bcent)
                diff = abs(dn - dh) / max(dn, dh)
                cost = diff * 10 + math.hypot(vx - target[0], vy - target[1]) * 0.05
                if diff <= 0.08 and (best is None or cost < best[0]):
                    best = (cost, vx, vy)
        _, vx, vy = best
        grid[vy:vy + 3, vx:vx + 3] = T["x_basalt"]
        objs.append({"class": "volcano", "cell": [vx, vy], "size": [3, 3], "sprite": "volcano"})
        taken |= {(vx + i, vy + j) for i in range(3) for j in range(3)}

    # resource points (PRD 4.2 / 6.1): forest, water, sand
    def place(kind, near, cond, maxd=8, avoid=()):
        best = None
        for y in range(H):
            for x in range(W):
                if (x, y) in taken or not cond(x, y):
                    continue
                d = min(math.hypot(x + 0.5 - a, y + 0.5 - b) for a, b in near)
                if d > maxd:
                    continue
                pen = sum(max(0, 3 - math.hypot(x - ax, y - ay)) for ax, ay in avoid)
                score = abs(d - maxd * 0.45) + pen * 3 + rng.random() * 0.8
                if best is None or score < best[0]:
                    best = (score, x, y)
        _, x, y = best
        taken.add((x, y))
        objs.append({"class": "resource", "kind": kind, "cell": [x, y], "sprite": f"res_{kind}"})
        return (x, y)

    def neighbours(x, y):
        return [grid[y + dy, x + dx] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if 0 <= x + dx < W and 0 <= y + dy < H]

    water_t = {T["n_stream"], T["h_weir"], T["x_shallow"]}
    for b in objs:
        if b["class"] == "human_building":
            taken |= {(b["cell"][0] + i, b["cell"][1] + j) for i in range(b["size"][0]) for j in range(b["size"][1])}
    for z in NATURE:
        m = z["mask"]
        zc = [(x + 0.5, y + 0.5) for y, x in np.argwhere(m)]
        near = [z["c"]]
        p = []
        p.append(place("forest", near, lambda x, y: m[y, x] and T["x_forest"] in neighbours(x, y), avoid=p))
        p.append(place("water", near, lambda x, y: m[y, x] and grid[y, x] not in water_t and bool(water_t & set(neighbours(x, y))), avoid=p))
        p.append(place("sand", near, lambda x, y: m[y, x] and grid[y, x] in (T["n_rocks"], T["n_beach"], T["n_tundra"], T["n_steppe"]), avoid=p))
    for site in ["人类主城", "前哨1", "前哨2"]:
        bl = [b for b in objs if b["class"] == "human_building" and b["site"] == site]
        near = [(b["cell"][0] + b["size"][0] / 2, b["cell"][1] + b["size"][1] / 2) for b in bl]
        n_each = 2 if site == "人类主城" else 1
        p = []
        ground = (T["h_snow"], T["h_mud"], T["h_camp"])
        for _ in range(n_each):
            # forest point: prefer the forest edge; water point: a spring on open ground or by the stream
            p.append(place("forest", near, lambda x, y: human[y, x] and grid[y, x] in ground, avoid=p))
            p.append(place("water", near, lambda x, y: human[y, x] and grid[y, x] in ground, avoid=p))
            p.append(place("sand", near, lambda x, y: human[y, x] and grid[y, x] in (T["h_mud"], T["h_snow"], T["h_shore"]), avoid=p))

    # trees along forest edges (3/4 view: the southern edge of the canopy gets trunks)
    kinds = ["tree_spruce", "tree_spruce_b", "tree_pine", "tree_dead"]
    for y in range(H - 1):
        for x in range(W):
            near_volcano = any(o["class"] == "volcano" and o["cell"][0] - 1 <= x <= o["cell"][0] + 3
                               and o["cell"][1] - 2 <= y <= o["cell"][1] + 3 for o in objs)
            if grid[y, x] == T["x_forest"] and grid[y + 1, x] != T["x_forest"] and (x, y) not in taken \
                    and not near_volcano and rng.random() < 0.45:
                objs.append({"class": "tree", "cell": [x, y], "sprite": kinds[rng.choice(4, p=[0.38, 0.3, 0.22, 0.1])]})

    out = {"id": "ice_age", "width": W, "height": H, "tile": TILE, "seed": SEED,
           "terrain_ids": [t["id"] for t in terrains],
           "terrain": ["".join(chr(65 + v) for v in row) for row in grid],  # A = terrain 0, B = 1, ...
           "objects": objs}
    MAPS.mkdir(exist_ok=True)
    LAYOUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print("layout saved")


# ---------------------------------------------------------------- build
def load_layout():
    L = json.loads(LAYOUT.read_text())
    grid = np.array([[ord(c) - 65 for c in row] for row in L["terrain"]], np.int32)
    return L, grid


def tile_choice(i, j, col):
    if col != 15:
        return col
    h = (i * 73856093 ^ j * 19349663) & 0xFFFF
    r = h / 65536
    return 15 if r < 0.55 else 16 + int((r - 0.55) / 0.15)


def build():
    meta = json.loads((ROOT / "terrain/ice_age.json").read_text())
    _, terrains = registry()
    prio = {t["index"]: t["priority"] for t in terrains}
    L, grid = load_layout()
    layers = display_layers(grid, prio)
    cols = meta["columns"]

    # ---- Tiled export
    logic_png = logic_tileset(terrains)
    n_terrain = cols * meta["rows"]
    first_logic = 1 + n_terrain
    tiled_layers = [{
        "type": "tilelayer", "name": "terrain", "id": 1, "width": W, "height": H, "x": 0, "y": 0,
        "opacity": 0.6, "visible": False,
        "data": [int(first_logic + v) for v in grid.flatten()],
        "properties": [{"name": "note", "type": "string", "value": "logic: one terrain per cell; edit this, then rerun build"}],
    }]
    for k, lay in enumerate(layers):
        data = []
        for j in range(H + 1):
            for i in range(W + 1):
                v = lay[j, i]
                if v < 0:
                    data.append(0)
                else:
                    t, m = divmod(int(v), 16)
                    data.append(1 + t * cols + tile_choice(i, j, m))
        tiled_layers.append({"type": "tilelayer", "name": f"ground{k}", "id": 2 + k, "width": W + 1, "height": H + 1,
                             "x": 0, "y": 0, "offsetx": -TILE // 2, "offsety": -TILE // 2, "opacity": 1, "visible": True,
                             "data": data})
    objs = []
    oid = 1
    for o in L["objects"]:
        props = [{"name": k, "type": "string", "value": json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}
                 for k, v in o.items() if k not in ("class",)]
        if "cell" in o:
            w, h = o.get("size", [1, 1])
            x, y, ww, hh = o["cell"][0] * TILE, o["cell"][1] * TILE, w * TILE, h * TILE
        else:
            c = o.get("nest") or o.get("c")
            x, y, ww, hh = c[0] * TILE, c[1] * TILE, 0, 0
        objs.append({"id": oid, "name": o.get("name", o.get("type", o.get("kind", o.get("sprite", "")))),
                     "type": o["class"], "x": x, "y": y, "width": ww, "height": hh, "rotation": 0,
                     "visible": True, "point": ww == 0, "properties": props})
        oid += 1
    tiled_layers.append({"type": "objectgroup", "name": "objects", "id": 6, "draworder": "topdown", "x": 0, "y": 0,
                         "opacity": 1, "visible": True, "objects": objs})
    tsj = json.loads((ROOT / "terrain/ice_age.tsj").read_text())
    ts_terrain = {**{k: v for k, v in tsj.items() if k not in ("type", "version", "tiledversion")},
                  "firstgid": 1, "image": "../terrain/ice_age.png"}
    ts_logic = {"firstgid": first_logic, "name": "ice_age_logic", "image": "../terrain/" + logic_png,
                "imagewidth": TILE * len(terrains), "imageheight": TILE, "tilewidth": TILE, "tileheight": TILE,
                "columns": len(terrains), "tilecount": len(terrains), "margin": 0, "spacing": 0,
                "tiles": [{"id": t["index"], "properties": [{"name": "terrain", "type": "string", "value": t["id"]}]}
                          for t in terrains]}
    tmj = {"type": "map", "version": "1.10", "tiledversion": "1.11.0", "orientation": "orthogonal",
           "renderorder": "right-down", "width": W, "height": H, "tilewidth": TILE, "tileheight": TILE,
           "infinite": False, "nextlayerid": 7, "nextobjectid": oid, "layers": tiled_layers,
           "tilesets": [ts_terrain, ts_logic],
           "properties": [{"name": "era", "type": "string", "value": "ice_age"},
                          {"name": "chunk", "type": "int", "value": 8},
                          {"name": "terrain_meta", "type": "string", "value": "../terrain/ice_age.json"},
                          {"name": "objects_meta", "type": "string", "value": "../objects/map/objects.json"}]}
    (MAPS / "ice_age.tmj").write_text(json.dumps(tmj, ensure_ascii=False) + "\n")

    img = render(grid, layers, L, meta)
    img.save(MAPS / "ice_age_preview.png", optimize=True)
    stats = check(grid, L, terrains)
    overview(img, grid, L, terrains, stats)
    print("built", stats["summary"])


def logic_tileset(terrains):
    """Flat colour swatches for painting the logic layer in Tiled."""
    atlas = Image.open(ROOT / "terrain/ice_age.png").convert("RGBA")
    out = Image.new("RGBA", (TILE * len(terrains), TILE))
    d = ImageDraw.Draw(out)
    for t in terrains:
        sw = atlas.crop((15 * TILE, t["index"] * TILE, 16 * TILE, (t["index"] + 1) * TILE))
        c = tuple(int(v) for v in np.array(sw).reshape(-1, 4)[:, :3].mean(0))
        x = t["index"] * TILE
        d.rectangle([x, 0, x + TILE - 1, TILE - 1], fill=c + (255,))
        ring = {"human": (240, 150, 40), "nature": (40, 190, 70), "neutral": (200, 200, 200), "volcano": (220, 60, 50)}[t["owner"]]
        d.rectangle([x, 0, x + TILE - 1, TILE - 1], outline=ring + (255,), width=2)
        d.text((x + 4, 11), t["id"].split("_")[1][:5], fill=(0, 0, 0, 255))
        d.text((x + 3, 10), t["id"].split("_")[1][:5], fill=(255, 255, 255, 255))
    name = "ice_age_logic.png"
    out.save(ROOT / "terrain" / name)
    return name


def render(grid, layers, L, meta):
    atlas = Image.open(ROOT / "terrain/ice_age.png").convert("RGBA")
    cols = meta["columns"]
    cache = {}

    def tile(gid_col, t):
        key = (t, gid_col)
        if key not in cache:
            cache[key] = atlas.crop((gid_col * TILE, t * TILE, (gid_col + 1) * TILE, (t + 1) * TILE))
        return cache[key]

    img = Image.new("RGBA", (W * TILE, H * TILE), (0, 0, 0, 255))
    for lay in layers:
        for j in range(H + 1):
            for i in range(W + 1):
                v = lay[j, i]
                if v < 0:
                    continue
                t, m = divmod(int(v), 16)
                paste_clipped(img, tile(tile_choice(i, j, m), t), i * TILE - 16, j * TILE - 16)
    # objects sorted by their base line (3/4 view)
    reg = json.loads((ROOT / "objects/map/objects.json").read_text())
    sprites = {k: Image.open(ROOT / "objects/map" / v["png"]).convert("RGBA") for k, v in reg.items()}
    drawn = []
    for o in L["objects"]:
        if "sprite" in o:
            fw, fh = reg[o["sprite"]]["footprint"]
            base_y = (o["cell"][1] + fh) * TILE
            cx = (o["cell"][0] + fw / 2) * TILE
            drawn.append((base_y, cx, sprites[o["sprite"]]))
    d = ImageDraw.Draw(img)
    for o in L["objects"]:
        if o["class"] == "human_building":
            x, y = o["cell"][0] * TILE, o["cell"][1] * TILE
            w, h = o["size"][0] * TILE, o["size"][1] * TILE
            d.rectangle([x + 2, y + 2, x + w - 3, y + h - 3], outline=(240, 150, 40, 255), width=2)
            d.text((x + 5, y + 5), o["type"][:2] if w == TILE else o["type"], fill=(255, 235, 200, 255),
                   font=font(11))
    for base_y, cx, sp in sorted(drawn, key=lambda t: t[0]):
        paste_clipped(img, sp, int(cx - sp.width / 2), int(base_y - sp.height))
    return img


def paste_clipped(dst, src, x, y):
    sx, sy = max(0, -x), max(0, -y)
    crop = src.crop((sx, sy, src.width, src.height))
    dst.alpha_composite(crop, (x + sx, y + sy))


_fonts = {}


def font(size):
    if size not in _fonts:
        for p in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                  "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"]:
            try:
                _fonts[size] = ImageFont.truetype(p, size)
                break
            except OSError:
                continue
        else:
            _fonts[size] = ImageFont.load_default()
    return _fonts[size]


# ---------------------------------------------------------------- checks
def check(grid, L, terrains):
    owner = np.array([{"human": 0, "nature": 1, "neutral": 2, "volcano": 3}[t["owner"]] for t in terrains])[grid]
    contest = np.array([t["contestable"] for t in terrains])[grid]
    objs = L["objects"]
    vol_cells = set()
    for o in objs:
        if o["class"] == "volcano":
            vol_cells |= {(o["cell"][0] + i, o["cell"][1] + j) for i in range(3) for j in range(3)}
    n_contest = int(contest.sum())
    hum = int(((owner == 0) & contest).sum())
    nat = int(((owner == 1) & contest).sum())
    neu = int(((owner == 2) & contest).sum())
    rows = []

    def row(item, value, ok):
        rows.append((item, value, "✅" if ok else "❌"))

    row("可争夺格（去掉火山和深海）", f"{n_contest} / {W * H}", True)
    row("开局人类领地 ≥ 55%", f"{hum} 格 = {hum / n_contest:.1%}", hum / n_contest >= 0.55)
    row("开局自然领地 8–10%", f"{nat} 格 = {nat / n_contest:.1%}", 0.08 <= nat / n_contest <= 0.10)
    row("中立（森林、浅海）", f"{neu} 格 = {neu / n_contest:.1%}", True)
    zones = [o for o in objs if o["class"] == "nature_start"]
    for z in zones:
        row(f"{z['name']} 面积约 120 格", f"{z['cells']} 格", 100 <= z["cells"] <= 140)
    nat_xy = np.argwhere(owner == 1)
    hum_xy = np.argwhere(owner == 0)
    res = [o for o in objs if o["class"] == "resource"]
    blds = [o for o in objs if o["class"] == "human_building"]

    def dmin(pts, x, y):
        return float(np.hypot(pts[:, 1] - x, pts[:, 0] - y).min())

    # resources within 8 cells of each start
    for z in zones:
        cx, cy = z["nest"]
        zone_xy = nat_xy[np.hypot(nat_xy[:, 1] + 0.5 - cx, nat_xy[:, 0] + 0.5 - cy) < 9]
        got = {k: min((dmin(zone_xy, r["cell"][0], r["cell"][1]) for r in res if r["kind"] == k), default=99)
               for k in ("forest", "water", "sand")}
        row(f"{z['name']} 8 格内有森林/水源/沙土", " / ".join(f"{v:.0f}" for v in got.values()) + " 格",
            all(v <= 8 for v in got.values()))
    for site in ["人类主城", "前哨1", "前哨2"]:
        pts = np.array([[b["cell"][1] + j, b["cell"][0] + i] for b in blds if b["site"] == site
                        for i in range(b["size"][0]) for j in range(b["size"][1])])
        got = {k: min((dmin(pts, r["cell"][0], r["cell"][1]) for r in res if r["kind"] == k), default=99)
               for k in ("forest", "water", "sand")}
        row(f"{site} 8 格内有森林/水源/沙土", " / ".join(f"{v:.0f}" for v in got.values()) + " 格",
            all(v <= 8 for v in got.values()))
    # volcanoes
    bc = [(b["cell"][0] + b["size"][0] / 2, b["cell"][1] + b["size"][1] / 2) for b in blds]
    for k, v in enumerate(o for o in objs if o["class"] == "volcano"):
        c = (v["cell"][0] + 1.5, v["cell"][1] + 1.5)
        dn = float(np.hypot(nat_xy[:, 1] + 0.5 - c[0], nat_xy[:, 0] + 0.5 - c[1]).min())
        dh = min(math.hypot(x - c[0], y - c[1]) for x, y in bc)
        side = "北" if c[1] < H / 2 else "南"
        row(f"火山{k + 1}（中线{side}侧）到最近自然领地 / 人类建筑", f"{dn:.1f} / {dh:.1f} 格，相差 {abs(dn - dh) / max(dn, dh):.0%}",
            abs(dn - dh) / max(dn, dh) <= 0.10)
    # safety distance
    for z in zones:
        cx, cy = z["nest"]
        dc = float(np.hypot(hum_xy[:, 1] + 0.5 - cx, hum_xy[:, 0] + 0.5 - cy).min())
        zone_xy = nat_xy[np.hypot(nat_xy[:, 1] + 0.5 - cx, nat_xy[:, 0] + 0.5 - cy) < 9]
        de = min(float(np.hypot(hum_xy[:, 1] - x, hum_xy[:, 0] - y).min()) for y, x in zone_xy)
        row(f"{z['name']} 巢穴中心到最近人类领地 ≥ 12 格", f"{dc:.1f} 格（领地边缘到边缘 {de:.1f} 格）", dc >= 12)
    # nearest resource count 1:1
    starts = [("nature", z["nest"]) for z in zones] + [("human", c) for c in bc]
    cnt = {"nature": 0, "human": 0}
    for r in res:
        side = min(starts, key=lambda s: math.hypot(s[1][0] - r["cell"][0], s[1][1] - r["cell"][1]))[0]
        cnt[side] += 1
    row("各自最近的资源点 自然 : 人类 = 1 : 1", f"{cnt['nature']} : {cnt['human']}", cnt["nature"] == cnt["human"])
    # chunks
    ch = {"human": 0, "nature": 0, "contested": 0}
    chunk_owner = np.zeros((H // 8, W // 8), np.int32)
    for cy in range(H // 8):
        for cx in range(W // 8):
            o = owner[cy * 8:(cy + 1) * 8, cx * 8:(cx + 1) * 8]
            c = contest[cy * 8:(cy + 1) * 8, cx * 8:(cx + 1) * 8]
            tot = c.sum()
            if tot == 0:
                chunk_owner[cy, cx] = 3
                continue
            if ((o == 0) & c).sum() / tot >= 0.6:
                ch["human"] += 1; chunk_owner[cy, cx] = 0
            elif ((o == 1) & c).sum() / tot >= 0.6:
                ch["nature"] += 1; chunk_owner[cy, cx] = 1
            else:
                ch["contested"] += 1; chunk_owner[cy, cx] = 2
    row("区块（8×8）人类 / 自然 / 争夺中", f"{ch['human']} / {ch['nature']} / {ch['contested']}（共 {(W // 8) * (H // 8)}）", True)
    per_t = {t["id"]: int((grid == t["index"]).sum()) for t in terrains}
    md = ["# 冰河时代关卡 · 验收清单（PRD 4.1 / 4.2）", "",
          "由 `python scripts/build_map.py build` 自动生成。", "",
          "| 项目 | 实测 | 结果 |", "| --- | --- | --- |"]
    md += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    md += ["", "## 说明", "",
           "- **12 格安全距离**按「巢穴中心（开局领地中心）到最近的人类格」测量。若按领地边缘到边缘算 12 格，"
           "4 块自然领地周围各需约 12 格宽的中立带，人类只能占约 43%，与「人类 ≥ 55%」冲突，所以先按中心算；边缘距离一并列出供参考。",
           "- 浅海算中立、可争夺（PRD 只把火山和深海排除在外）；目前没有任何一方能转化浅海，见 README 的待确认问题。",
           "- 资源点「最近」按到最近的开局点（自然巢穴中心或人类建筑）归属后计数。", "",
           "## 各地块格数", "", "| 地块 | 格数 |", "| --- | --- |"]
    names = {t["id"]: t["name"] for t in terrains}
    md += [f"| {names[k]}（`{k}`） | {v} |" for k, v in per_t.items()]
    (MAPS / "ice_age_check.md").write_text("\n".join(md) + "\n")
    fails = [r for r in rows if r[2] == "❌"]
    return {"rows": rows, "chunk_owner": chunk_owner, "owner": owner, "contest": contest,
            "summary": f"human {hum / n_contest:.1%}, nature {nat / n_contest:.1%}, {len(fails)} failed",
            "fails": fails, "hum": hum, "nat": nat, "n": n_contest}


def overview(img, grid, L, terrains, st):
    s = 2
    small = img.resize((W * TILE // s, H * TILE // s), Image.LANCZOS)
    cell = TILE // s
    tint = Image.new("RGBA", small.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(tint)
    col = {0: (255, 160, 40, 70), 1: (40, 220, 80, 90)}
    owner = st["owner"]
    for y in range(H):
        for x in range(W):
            if owner[y, x] in col:
                d.rectangle([x * cell, y * cell, x * cell + cell - 1, y * cell + cell - 1], fill=col[owner[y, x]])
    small.alpha_composite(tint)
    d = ImageDraw.Draw(small)
    cc = {0: (255, 150, 30, 255), 1: (30, 200, 60, 255), 2: (255, 255, 255, 140), 3: (60, 90, 160, 120)}
    for cy in range(H // 8):
        for cx in range(W // 8):
            x0, y0 = cx * 8 * cell, cy * 8 * cell
            d.rectangle([x0, y0, x0 + 8 * cell - 1, y0 + 8 * cell - 1], outline=cc[st["chunk_owner"][cy, cx]], width=1)
    def icon(d, kind, x, y, r=6):
        if kind == "forest":
            d.polygon([(x, y - r - 1), (x - r, y + r), (x + r, y + r)], fill=(40, 170, 70, 255), outline=(0, 0, 0, 255))
        elif kind == "water":
            d.ellipse([x - r, y - r, x + r, y + r], fill=(70, 160, 240, 255), outline=(0, 0, 0, 255))
        else:
            d.rectangle([x - r + 1, y - r + 1, x + r - 1, y + r - 1], fill=(235, 205, 120, 255), outline=(0, 0, 0, 255))

    for o in L["objects"]:
        if o["class"] == "resource":
            x, y = o["cell"][0] * cell + cell // 2, o["cell"][1] * cell + cell // 2
            icon(d, o["kind"], x, y)
        elif o["class"] == "nature_start":
            x, y = o["nest"][0] * cell, o["nest"][1] * cell
            d.text((x - 18, y - 8), o["name"], fill=(255, 255, 255, 255), font=font(14), stroke_width=2, stroke_fill=(0, 90, 20, 255))
        elif o["class"] == "human_start":
            x, y = o["c"][0] * cell, o["c"][1] * cell
            d.text((x - 22, y - 30), o["name"], fill=(255, 255, 255, 255), font=font(14), stroke_width=2, stroke_fill=(120, 60, 0, 255))
        elif o["class"] == "volcano":
            x, y = (o["cell"][0] + 1.5) * cell, (o["cell"][1] + 3) * cell
            d.text((x - 12, y + 2), "火山", fill=(255, 255, 255, 255), font=font(13), stroke_width=2, stroke_fill=(150, 20, 20, 255))
    leg_w = 300
    out = Image.new("RGBA", (small.width + leg_w, small.height), (28, 30, 36, 255))
    out.paste(small, (0, 0))
    d = ImageDraw.Draw(out)
    x0 = small.width + 16
    y = 14
    d.text((x0, y), "冰河时代 · 96×64 格", fill=(255, 255, 255, 255), font=font(18)); y += 30
    d.text((x0, y), f"人类 {st['hum'] / st['n']:.1%}　自然 {st['nat'] / st['n']:.1%}", fill=(230, 230, 230, 255), font=font(14)); y += 26
    for c, t in [((255, 160, 40), "人类领地（橙色区块边框）"), ((40, 220, 80), "自然领地（绿色区块边框）"),
                 ((255, 255, 255), "白框：争夺中的区块"), ((60, 90, 160), "蓝框：全是深海/火山")]:
        d.rectangle([x0, y + 3, x0 + 14, y + 17], fill=c + (255,)); d.text((x0 + 22, y), t, fill=(230, 230, 230, 255), font=font(13)); y += 22
    y += 6
    for k, t in [("forest", "森林资源点"), ("water", "水源资源点"), ("sand", "沙土资源点")]:
        icon(d, k, x0 + 7, y + 9); d.text((x0 + 22, y), t, fill=(230, 230, 230, 255), font=font(13)); y += 20
    y += 10
    d.text((x0, y), "验收（PRD 4.2）", fill=(255, 255, 255, 255), font=font(15)); y += 24
    for a, b, c in st["rows"]:
        ok = c == "✅"
        if ok:
            d.line([(x0, y + 7), (x0 + 3, y + 11), (x0 + 9, y + 2)], fill=(120, 230, 120, 255), width=2)
        else:
            d.line([(x0, y + 2), (x0 + 8, y + 10)], fill=(255, 110, 110, 255), width=2)
            d.line([(x0 + 8, y + 2), (x0, y + 10)], fill=(255, 110, 110, 255), width=2)
        d.text((x0 + 14, y), a[:22], fill=(150, 230, 150, 255) if ok else (255, 120, 120, 255), font=font(11)); y += 16
        d.text((x0 + 12, y), b[:30], fill=(190, 190, 190, 255), font=font(11)); y += 17
    out.save(MAPS / "ice_age_overview.png", optimize=True)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("layout", "all"):
        layout()
    if what in ("build", "all"):
        build()
