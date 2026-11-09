"""Turn PixelLab raw output into game-ready assets.

Usage:
  python scripts/postprocess.py [unit_id ...]     (default: every unit under units/)

For each unit it:
  * puts every frame into one shared cell (frames are centred, so the pivot stays put)
  * builds the 8 directions from the 5 drawn ones (west side = mirrored east side)
  * hardens alpha and, if style.yaml sets `palette`, snaps every colour to it
  * writes units/<id>/<id>.png  - spritesheet (one row per animation+direction)
           units/<id>/<id>.json - atlas in TexturePacker "JSON Hash" format, which
                                  Phaser 3 (load.atlas) and PixiJS (Spritesheet) read
                                  directly; animations are listed under "animations"
  * writes preview GIFs into preview/
"""
import json
import pathlib
import sys

import numpy as np
import yaml
from PIL import Image

import normals

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIRS = ["south", "south-east", "east", "north-east", "north", "north-west", "west", "south-west"]
GROUND = (196, 206, 214, 255)  # neutral snowy grey for previews


# ---------- colour ----------
def load_palette(path):
    cols = [l.strip().lstrip("#") for l in (ROOT / path).read_text().split() if l.strip()]
    return np.array([[int(c[i:i + 2], 16) for i in (0, 2, 4)] for c in cols], dtype=np.float64)


def srgb_to_lab(rgb):
    c = rgb / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


class Palette:
    """Snap colours to a palette. With path=None it only hardens alpha."""

    def __init__(self, path):
        self.off = path is None
        if self.off:
            return
        self.rgb = load_palette(path)
        self.lab = srgb_to_lab(self.rgb)
        self.cache = {}

    def apply(self, im):
        a = np.array(im.convert("RGBA"))
        alpha = a[..., 3] >= 128
        if self.off:
            a[..., 3] = np.where(alpha, 255, 0)
            a[~alpha] = 0
            return Image.fromarray(a, "RGBA")
        px = a[..., :3][alpha]
        uniq, inv = np.unique(px, axis=0, return_inverse=True)
        d = ((srgb_to_lab(uniq.astype(np.float64))[:, None, :] - self.lab[None]) ** 2).sum(-1)
        mapped = self.rgb[d.argmin(1)].astype(np.uint8)
        out = np.zeros_like(a)
        out[..., :3][alpha] = mapped[inv.ravel()]
        out[..., 3] = np.where(alpha, 255, 0)
        return Image.fromarray(out, "RGBA")


# ---------- frames ----------
def centred(im, cell):
    c = Image.new("RGBA", (cell, cell))
    c.paste(im, ((cell - im.width) // 2, (cell - im.height) // 2))
    return c


VARIANTS = {  # extra attack versions: folder under units/<id>/variants/ -> label
    "attackkf": "PixelLab key poses + interpolation",
    "attackhand": "AI hand-edited (text-grid method)",
    "death": "AI hand-edited collapse",
}
BASE_ANIMS = ("rotation", "idle", "walk", "attack")
DIRV = {"south": (0, 1), "south-east": (0.7071, 0.7071), "east": (1, 0), "north-east": (0.7071, -0.7071),
        "north": (0, -1), "north-west": (-0.7071, -0.7071), "west": (-1, 0), "south-west": (-0.7071, 0.7071)}


def load_unit_frames(uid, style):
    """-> frames[name][dir] = [Image], ms[name][dir] = [int|None], hits[name_dir] = idx, cells[name]"""
    raw = ROOT / "units" / uid / "raw"
    meta = json.loads((raw / "metadata.json").read_text())
    fr = meta["states"][0]["frames"]
    drawn = style["drawn_directions"]
    mirror = style["mirror_map"]

    src = {"rotation": {d: [(raw / fr["rotations"][d], None)] for d in DIRS}}
    for name, per_dir in fr.get("animations", {}).items():
        src[name] = {d: [(raw / p, None) for p in paths] for d, paths in per_dir.items()}
    hits = {}
    for v in VARIANTS:
        vdir = ROOT / "units" / uid / "variants" / v
        if not vdir.exists():
            continue
        src[v] = {}
        for d in drawn:
            sq = vdir / d / "sequence.json"
            if sq.exists():
                seq = json.loads(sq.read_text())
                src[v][d] = [(vdir / d / f["file"], f["ms"]) for f in seq["frames"]]
                hits[f"{v}_{d}"] = seq["hit"]

    frames, ms, cells = {}, {}, {}
    for name, per_dir in src.items():
        frames[name], ms[name] = {}, {}
        for d in drawn:
            if d in per_dir:
                frames[name][d] = [Image.open(p).convert("RGBA") for p, _ in per_dir[d]]
                ms[name][d] = [m for _, m in per_dir[d]]
        sizes = [max(i.size) for fl in frames[name].values() for i in fl]
        cells[name] = max(sizes) if sizes else 0
    # base animations share one cell so they line up; variants keep their own
    base = max(cells[n] for n in BASE_ANIMS if n in cells)
    base += base % 2
    for name in frames:
        c = base if name in BASE_ANIMS else max(base, cells[name] + cells[name] % 2)
        cells[name] = c
        for d in list(frames[name]):
            frames[name][d] = [centred(i, c) for i in frames[name][d]]
        for d, sd in mirror.items():
            if sd in frames[name]:
                frames[name][d] = [i.transpose(Image.FLIP_LEFT_RIGHT) for i in frames[name][sd]]
                ms[name][d] = list(ms[name][sd])
                if f"{name}_{sd}" in hits:
                    hits[f"{name}_{d}"] = hits[f"{name}_{sd}"]
    # the original attack has no authored hit frame: pick the frame that reaches
    # furthest in the facing direction
    for d, fl in frames.get("attack", {}).items():
        vx, vy = DIRV[d]
        best, bi = -1e9, len(fl) // 2
        for i, im in enumerate(fl[1:], start=1):
            a = np.array(im)[..., 3] > 127
            ys, xs = np.nonzero(a)
            if not len(xs):
                continue
            proj = (xs - im.width / 2) * vx + (ys - im.height / 2) * vy
            sc = float(np.percentile(proj, 98))
            if sc > best:
                best, bi = sc, i
        hits[f"attack_{d}"] = bi
    return frames, ms, hits, cells, base


def foot_offset(frames, cell):
    """Feet: lowest opaque row of the static south pose, in px below the cell centre."""
    bbox = frames["rotation"]["south"][0].getbbox()
    return (bbox[3] - cell / 2) if bbox else cell / 2


def pack(strips, max_w=2048):
    """Shelf-pack strips [(key, w, h)] -> {key: (x, y)}, sheet size."""
    pos, x, y, shelf_h, W = {}, 0, 0, 0, 0
    for key, w, h in strips:
        if x and x + w > max_w:
            x, y, shelf_h = 0, y + shelf_h, 0
        pos[key] = (x, y)
        x += w
        shelf_h = max(shelf_h, h)
        W = max(W, x)
    return pos, (W, y + shelf_h)


def process(uid, style, pal):
    unit_cfg = yaml.safe_load((ROOT / "prompts/units" / f"{uid}.yaml").read_text())
    frames, ms, hits, cells, cell = load_unit_frames(uid, style)
    fps = {"rotation": 1, "idle": 6, "walk": 10, "attack": 10, "attackkf": 10, "attackhand": 10, "death": 10}

    rows = [(n, d) for n in frames for d in DIRS if d in frames[n]]
    strips = [((n, d), len(frames[n][d]) * cells[n], cells[n]) for n, d in rows]
    pos, size = pack(strips)
    sheet = Image.new("RGBA", size)
    atlas = {"frames": {}, "animations": {}}
    for n, d in rows:
        c = cells[n]
        x0, y0 = pos[(n, d)]
        names = []
        for i, im in enumerate(frames[n][d]):
            im = pal.apply(im)
            frames[n][d][i] = im
            sheet.paste(im, (x0 + i * c, y0))
            key = f"{n}_{d}_{i}"
            names.append(key)
            dur = ms[n][d][i] or round(1000 / fps.get(n, 8))
            atlas["frames"][key] = {
                "frame": {"x": x0 + i * c, "y": y0, "w": c, "h": c},
                "rotated": False, "trimmed": False,
                "spriteSourceSize": {"x": 0, "y": 0, "w": c, "h": c},
                "sourceSize": {"w": c, "h": c}, "duration": dur,
            }
        atlas["animations"][f"{n}_{d}"] = names
    out = ROOT / "units" / uid
    sheet.save(out / f"{uid}.png", optimize=True)
    foot = foot_offset(frames, cell)
    atlas["meta"] = {
        "app": "nature-vs-human-asset/scripts/postprocess.py", "version": "2",
        "image": f"{uid}.png", "format": "RGBA8888",
        "size": {"w": sheet.width, "h": sheet.height}, "scale": "1",
        "unit": {
            "id": uid, "display_name": unit_cfg.get("display_name"), "faction": unit_cfg.get("faction"),
            "era": unit_cfg.get("era"), "size_class": unit_cfg.get("size_class"),
            "art_canvas": unit_cfg.get("canvas"), "cell": cell, "cells": cells,
            # frames are centred in their cells: feet are `foot` px below the centre
            "foot": foot, "anchor": {"x": 0.5, "y": round((cell / 2 + foot) / cell, 4)},
            "fps": {n: fps.get(n, 8) for n in frames}, "hit": hits,
            "variants": {v: VARIANTS[v] for v in VARIANTS if v in frames},
            "directions": DIRS, "mirrored": style["mirror_map"],
            "normal_map": f"{uid}_n.png",
        },
    }
    (out / f"{uid}.json").write_text(json.dumps(atlas, indent=1, ensure_ascii=False) + "\n")
    write_previews(uid, {n: f for n, f in frames.items() if n in BASE_ANIMS}, cell, fps)
    if normals.available():
        normals.unit(uid)
    print(f"{uid}: base cell {cell}px, {len(rows)} strips -> sheet {sheet.size}")
    return frames, cell


def write_previews(uid, frames, cell, fps, scale=4):
    prev = ROOT / "preview"
    prev.mkdir(exist_ok=True)
    for n, per_dir in frames.items():
        if n == "rotation":
            continue
        dirs = [d for d in DIRS if d in per_dir]
        nf = max(len(per_dir[d]) for d in dirs)
        out = []
        for i in range(nf):
            canvas = Image.new("RGBA", (cell * len(dirs), cell), GROUND)
            for j, d in enumerate(dirs):
                canvas.alpha_composite(per_dir[d][i % len(per_dir[d])], (j * cell, 0))
            out.append(canvas.resize((canvas.width * scale, canvas.height * scale), Image.NEAREST).convert("RGB"))
        out[0].save(prev / f"{uid}_{n}.gif", save_all=True, append_images=out[1:],
                    duration=int(1000 / fps.get(n, 8)), loop=0, disposal=2)


def main():
    style = yaml.safe_load((ROOT / "prompts/style.yaml").read_text())
    pal = Palette(style.get("palette"))
    ids = sys.argv[1:] or sorted(p.name for p in (ROOT / "units").iterdir() if (p / "raw/metadata.json").exists())
    for uid in ids:
        process(uid, style, pal)


if __name__ == "__main__":
    main()
