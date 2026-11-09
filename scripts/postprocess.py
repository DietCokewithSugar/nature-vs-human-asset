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


def load_unit_frames(uid, style):
    raw = ROOT / "units" / uid / "raw"
    meta = json.loads((raw / "metadata.json").read_text())
    fr = meta["states"][0]["frames"]
    drawn = style["drawn_directions"]
    mirror = style["mirror_map"]

    anims = {"rotation": {d: [raw / fr["rotations"][d]] for d in DIRS}}
    for name, per_dir in fr.get("animations", {}).items():
        anims[name] = {d: [raw / p for p in paths] for d, paths in per_dir.items()}

    imgs, cell = {}, 0
    for name, per_dir in anims.items():
        imgs[name] = {}
        for d in drawn:
            if d in per_dir:
                imgs[name][d] = [Image.open(p).convert("RGBA") for p in per_dir[d]]
                cell = max(cell, *(max(i.size) for i in imgs[name][d]))
    cell += cell % 2
    for name in imgs:
        for d in list(imgs[name]):
            imgs[name][d] = [centred(i, cell) for i in imgs[name][d]]
        for d, src in mirror.items():
            if src in imgs[name]:
                imgs[name][d] = [i.transpose(Image.FLIP_LEFT_RIGHT) for i in imgs[name][src]]
    return imgs, cell


def foot_anchor(frames, cell):
    """Anchor at the horizontal centre / lowest opaque row of the static south pose."""
    bbox = frames["rotation"]["south"][0].getbbox()
    return {"x": 0.5, "y": round(bbox[3] / cell, 4)} if bbox else {"x": 0.5, "y": 1.0}


def process(uid, style, pal):
    unit_cfg = yaml.safe_load((ROOT / "prompts/units" / f"{uid}.yaml").read_text())
    frames, cell = load_unit_frames(uid, style)
    fps = {"rotation": 1, "idle": 6, "walk": 10, "attack": 10}

    rows = [(n, d) for n in frames for d in DIRS if d in frames[n]]
    cols = max(len(frames[n][d]) for n, d in rows)
    sheet = Image.new("RGBA", (cols * cell, len(rows) * cell))
    atlas = {"frames": {}, "animations": {}}
    for r, (n, d) in enumerate(rows):
        names = []
        for i, im in enumerate(frames[n][d]):
            im = pal.apply(im)
            frames[n][d][i] = im
            sheet.paste(im, (i * cell, r * cell))
            key = f"{n}_{d}_{i}"
            names.append(key)
            atlas["frames"][key] = {
                "frame": {"x": i * cell, "y": r * cell, "w": cell, "h": cell},
                "rotated": False, "trimmed": False,
                "spriteSourceSize": {"x": 0, "y": 0, "w": cell, "h": cell},
                "sourceSize": {"w": cell, "h": cell},
            }
        atlas["animations"][f"{n}_{d}"] = names
    out = ROOT / "units" / uid
    sheet.save(out / f"{uid}.png", optimize=True)
    atlas["meta"] = {
        "app": "nature-vs-human-asset/scripts/postprocess.py", "version": "1",
        "image": f"{uid}.png", "format": "RGBA8888",
        "size": {"w": sheet.width, "h": sheet.height}, "scale": "1",
        "unit": {
            "id": uid, "display_name": unit_cfg.get("display_name"), "faction": unit_cfg.get("faction"),
            "era": unit_cfg.get("era"), "size_class": unit_cfg.get("size_class"),
            "art_canvas": unit_cfg.get("canvas"), "cell": cell,
            "anchor": foot_anchor(frames, cell), "fps": {n: fps.get(n, 8) for n in frames},
            "directions": DIRS, "mirrored": style["mirror_map"],
        },
    }
    (out / f"{uid}.json").write_text(json.dumps(atlas, indent=1, ensure_ascii=False) + "\n")
    write_previews(uid, frames, cell, fps)
    print(f"{uid}: cell {cell}px, {len(rows)} rows x {cols} cols -> {sheet.size}")
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
