"""Side-by-side GIF of the attack versions for one direction, with real timing.

  python scripts/compare_attacks.py [dir]      -> preview/attack_compare_<unit>.gif
Panels: original (re-timed around its hit frame) | keyframe | hand-edited.
"""
import json
import pathlib
import sys

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
LABELS = [("attack", "PixelLab original"), ("attackkf", "PixelLab keyframe"), ("attackhand", "AI hand-edited")]


def seq(atlas, sheet, key, d):
    names = atlas["animations"].get(f"{key}_{d}")
    if not names:
        return None
    if key == "attack":   # same derived timing the site uses with "timing" on
        h = atlas["meta"]["unit"]["hit"].get(f"attack_{d}", len(names) // 2)
        ms = [120 if i == 0 else 110 if i < h - 1 else 50 if i == h - 1 else 160 if i == h else 120 if i == len(names) - 1 else 90
              for i in range(len(names))]
    else:
        ms = [atlas["frames"][n]["duration"] for n in names]
    ims = []
    for n in names:
        f = atlas["frames"][n]["frame"]
        ims.append(sheet.crop((f["x"], f["y"], f["x"] + f["w"], f["y"] + f["h"])))
    return ims, ms


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "east"
    for uid in ["nature_ice_leafcutter_bee", "nature_ice_sardinian_pika", "nature_ice_smilodon", "nature_ice_mammoth"]:
        a = json.loads((ROOT / "units" / uid / f"{uid}.json").read_text())
        sheet = Image.open(ROOT / "units" / uid / f"{uid}.png").convert("RGBA")
        seqs = [(lab, seq(a, sheet, k, d)) for k, lab in LABELS]
        seqs = [(lab, s) for lab, s in seqs if s]
        cell = max(max(i.width for i in s[0]) for _, s in seqs)
        S = 4 if cell <= 64 else 2
        W, H = cell * S, cell * S + 18
        total = max(sum(s[1]) for _, s in seqs) + 300
        frames, durs, tick = [], [], 30
        for t in range(0, total, tick):
            canvas = Image.new("RGB", (W * len(seqs), H), (205, 214, 224))
            dr = ImageDraw.Draw(canvas)
            for j, (lab, (ims, ms)) in enumerate(seqs):
                acc, idx = 0, len(ims) - 1
                for i, m in enumerate(ms):
                    if t < acc + m:
                        idx = i
                        break
                    acc += m
                if t >= sum(ms):
                    idx = len(ims) - 1
                im = ims[idx].resize((ims[idx].width * S, ims[idx].height * S), Image.NEAREST)
                canvas.paste(im, (j * W + (W - im.width) // 2, 18 + (cell * S - im.height) // 2), im)
                dr.text((j * W + 6, 3), lab, fill=(30, 30, 40))
            if frames and canvas.tobytes() == frames[-1].tobytes():
                durs[-1] += tick
            else:
                frames.append(canvas)
                durs.append(tick)
        out = ROOT / "preview" / f"attack_compare_{uid.replace('nature_ice_', '')}.gif"
        frames[0].save(out, save_all=True, append_images=frames[1:], duration=durs, loop=0)
        print(out.name, len(frames), "frames")


if __name__ == "__main__":
    main()
