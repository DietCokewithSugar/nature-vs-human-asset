"""Render an in-game-like mock scene from the processed spritesheets.

Usage: python scripts/preview_scene.py

Shows what the art direction doc asks to check: relative scale on the 32px
grid, code-drawn ellipse shadows + faction rings (green = nature, orange =
human), and a crowd of units at 2x display scale. Writes preview/scene.gif and
preview/lineup.png.
"""
import json
import pathlib
import random

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
TILE = 32
RING = {"nature": (99, 199, 77, 255), "human": (247, 118, 34, 255)}


def load(uid):
    d = ROOT / "units" / uid
    atlas = json.loads((d / f"{uid}.json").read_text())
    sheet = Image.open(d / f"{uid}.png").convert("RGBA")
    frames = {k: sheet.crop((v["frame"]["x"], v["frame"]["y"], v["frame"]["x"] + v["frame"]["w"],
                             v["frame"]["y"] + v["frame"]["h"])) for k, v in atlas["frames"].items()}
    return atlas, frames


def ground(w, h, seed=0):
    rnd = random.Random(seed)
    img = Image.new("RGBA", (w, h), (214, 222, 230, 255))
    dr = ImageDraw.Draw(img)
    for _ in range(w * h // 90):
        x, y = rnd.randrange(w), rnd.randrange(h)
        dr.point((x, y), fill=rnd.choice([(192, 203, 220, 255), (232, 238, 244, 255), (176, 186, 200, 255)]))
    for x in range(0, w, TILE):
        dr.line([(x, 0), (x, h)], fill=(200, 208, 220, 255))
    for y in range(0, h, TILE):
        dr.line([(0, y), (w, y)], fill=(200, 208, 220, 255))
    return img


def draw_unit(img, atlas, frames, anim, frame_i, foot_x, foot_y):
    u = atlas["meta"]["unit"]
    cell = u["cell"]
    names = atlas["animations"].get(anim) or atlas["animations"][f"idle_{anim.split('_', 1)[1]}"]
    fr = frames[names[frame_i % len(names)]]
    bbox = fr.getbbox() or (0, 0, cell, cell)
    body_w = bbox[2] - bbox[0]
    # code-drawn shadow + faction ring under the feet
    ov = Image.new("RGBA", img.size)
    d = ImageDraw.Draw(ov)
    rx, ry = max(5, body_w * 0.42), max(2, body_w * 0.16)
    d.ellipse([foot_x - rx, foot_y - ry, foot_x + rx, foot_y + ry], fill=(30, 30, 50, 90))
    d.ellipse([foot_x - rx - 1, foot_y - ry - 1, foot_x + rx + 1, foot_y + ry + 1], outline=RING[u["faction"]])
    img.alpha_composite(ov)
    ax, ay = u["anchor"]["x"] * cell, u["anchor"]["y"] * cell
    img.alpha_composite(fr, (int(foot_x - ax), int(foot_y - ay)))


def main():
    ids = sorted(p.name for p in (ROOT / "units").iterdir() if any(p.glob("*.json")) and (p / f"{p.name}.json").exists())
    units = {uid: load(uid) for uid in ids}
    prev = ROOT / "preview"
    prev.mkdir(exist_ok=True)

    # 1. lineup: every unit facing south-east, on the grid, 3x
    w = TILE * (2 + 3 * len(ids))
    img = ground(w, TILE * 3, 1)
    x = TILE * 1.5
    for uid in ids:
        atlas, frames = units[uid]
        span = 2 if atlas["meta"]["unit"]["size_class"] == "large" else 1
        draw_unit(img, atlas, frames, "idle_south-east", 0, x + TILE * span / 2, TILE * 2.3)
        x += TILE * 3
    img.resize((img.width * 3, img.height * 3), Image.NEAREST).save(prev / "lineup.png")

    # 2. crowd scene: ~100 units, walking, 2x
    W, H = TILE * 20, TILE * 12
    rnd = random.Random(7)
    mix = []
    for uid, (atlas, _) in units.items():
        sc = atlas["meta"]["unit"]["size_class"]
        mix += [uid] * {"large": 6, "medium": 47}.get(sc, 20)
    dirs = ["south", "south-east", "east", "north-east", "north", "north-west", "west", "south-west"]
    actors = []
    for uid in mix:
        atlas = units[uid][0]
        faction = atlas["meta"]["unit"]["faction"]
        # nature on the left, human on the right, mingling in the middle
        cx = rnd.gauss(W * (0.33 if faction == "nature" else 0.67), W * 0.16)
        actors.append([uid, min(max(cx, 16), W - 16), rnd.uniform(28, H - 6), rnd.choice(dirs), rnd.randrange(6)])
    actors.sort(key=lambda a: a[2])
    base = ground(W, H, 3)
    gif = []
    for f in range(12):
        img = base.copy()
        for uid, ax, ay, d, off in actors:
            atlas, frames = units[uid]
            anim = f"walk_{d}" if f"walk_{d}" in atlas["animations"] else f"idle_{d}"
            draw_unit(img, atlas, frames, anim, f + off, ax, ay)
        gif.append(img.resize((W * 2, H * 2), Image.NEAREST).convert("RGB"))
    gif[0].save(prev / "scene.gif", save_all=True, append_images=gif[1:], duration=100, loop=0)
    print(f"lineup + scene with {len(actors)} units written to preview/")


if __name__ == "__main__":
    main()
