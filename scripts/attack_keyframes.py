"""Attack variant "keyframe": key poses first, then in-betweens.

  PIXELLAB_API_KEY=... python scripts/attack_keyframes.py <unit_id> [--dirs east,south-east]

For each drawn direction:
  1. base       = the unit's static pose for that direction, padded so the
                  lunge has room (canvas x2, multiple of 4)
  2. anticipation = Pixen edit of base: wind-up, weight back      (1 generation)
  3. strike       = Pixen edit of base: full extension at impact  (1 generation)
  4. in-betweens  = v3 interpolation anticipation -> strike       (1 generation)
Then the sequence is timed like a hand-animated attack (see
aseprite-ai-artist rules/44: long wind-up, ~50 ms action, held hit, slower
recovery) and written to units/<id>/variants/attackkf/<dir>/ with
sequence.json (frame files, per-frame ms, index of the hit frame).

Prompts come from `attack_keys` in the unit YAML.
"""
import argparse
import base64
import io
import json
import math
import pathlib
from concurrent.futures import ThreadPoolExecutor

import yaml
from PIL import Image

from pixellab_api import PixelLab

ROOT = pathlib.Path(__file__).resolve().parent.parent
FACING = {
    "south": "toward the viewer (downward on screen)",
    "south-east": "toward the lower right",
    "east": "to the right",
    "north-east": "toward the upper right, away from the viewer",
    "north": "straight away from the viewer (upward on screen)",
}
KEEP = ("Keep exactly the same creature, colours, outline, size and facing direction; "
        "only the pose changes.")


def b64(im):
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return {"type": "base64", "base64": base64.b64encode(buf.getvalue()).decode(), "format": "png"}


def unb64(obj):
    data = obj["base64"] if isinstance(obj, dict) else obj
    return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGBA")


def pad(im, size):
    c = Image.new("RGBA", (size, size))
    c.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    return c


def images_of(job):
    lr = job["last_response"]
    if "images" in lr:
        return [unb64(i) for i in lr["images"]]
    if "image" in lr:
        return [unb64(lr["image"])]
    raise RuntimeError(f"no images in {list(lr)}")


def run_dir(api, uid, cfg, d, out):
    keys = cfg["attack_keys"]
    face = FACING[d]
    back = " Seen from behind: the face and mouth are not visible." if d == "north" else ""
    rot = Image.open(ROOT / "units" / uid / "raw" / "Idle" / "rotations" / f"{d}.png").convert("RGBA")
    size = int(math.ceil(rot.width * 2 / 4) * 4)
    base = pad(rot, size)
    out.mkdir(parents=True, exist_ok=True)
    base.save(out / "base.png")

    def edit(text, seed):
        r = api.post_when_free("/edit-image-pixen", {
            "image": b64(base), "description": f"{text.format(facing=face)}{back} {KEEP}",
            "width": size, "height": size, "no_background": True, "seed": seed})
        return images_of(api.wait_job(r["background_job_id"]))[0]

    spent = 0
    with ThreadPoolExecutor(2) as ex:
        fa = ex.submit(edit, keys["anticipation"], cfg["seed"] + 11)
        fs = ex.submit(edit, keys["strike"], cfg["seed"] + 12)
        antic, strike = pad(fa.result(), size), pad(fs.result(), size)
    spent += 2
    antic.save(out / "anticipation.png")
    strike.save(out / "strike.png")

    r = api.post_when_free("/animate-with-text-v3", {
        "first_frame": b64(antic), "last_frame": b64(strike),
        "action": keys.get("motion", "a fast, powerful strike forward") + f", moving {face}{back}",
        "frame_count": 4, "no_background": True, "seed": cfg["seed"] + 13})
    mids = [pad(m, size) for m in images_of(api.wait_job(r["background_job_id"]))]
    spent += 1
    # drop in-betweens that just repeat the keys
    mids = [m for m in mids if m.tobytes() not in (antic.tobytes(), strike.tobytes())]
    for i, m in enumerate(mids):
        m.save(out / f"mid_{i}.png")

    # timing (ms): stance, wind-up hold, fast action, held hit, follow, recover
    seq = [("base.png", 100), ("anticipation.png", 260)]
    seq += [(f"mid_{i}.png", 50) for i in range(len(mids))]
    hit = len(seq)
    seq += [("strike.png", 150)]
    if mids:
        seq += [(f"mid_{len(mids) - 1}.png", 90), (f"mid_{max(0, len(mids) // 2 - 1)}.png", 90)]
    seq += [("base.png", 140)]
    (out / "sequence.json").write_text(json.dumps({
        "frames": [{"file": f, "ms": ms} for f, ms in seq], "hit": hit, "generations": spent,
        "prompts": {"anticipation": keys["anticipation"], "strike": keys["strike"], "facing": face},
    }, indent=1) + "\n")
    print(uid, d, "ok", len(seq), "frames", flush=True)
    return spent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("unit")
    ap.add_argument("--dirs", default="south,south-east,east,north-east,north")
    ap.add_argument("--reseed", type=int, default=0, help="add to every seed to get a different take")
    a = ap.parse_args()
    style = yaml.safe_load((ROOT / "prompts/style.yaml").read_text())
    cfg = {**style, **yaml.safe_load((ROOT / "prompts/units" / f"{a.unit}.yaml").read_text())}
    cfg["seed"] += a.reseed * 100
    api = PixelLab()
    base = ROOT / "units" / a.unit / "variants" / "attackkf"
    with ThreadPoolExecutor(5) as ex:
        spent = sum(ex.map(lambda d: run_dir(api, a.unit, cfg, d, base / d), a.dirs.split(",")))
    src = ROOT / "units" / a.unit / "source.json"
    s = json.loads(src.read_text())
    s["generations_spent"] = round(s["generations_spent"] + spent, 3)
    v = s.setdefault("variants", {}).setdefault("attackkf", {"method": "PixelLab Pixen key poses + v3 interpolation"})
    v["keys"] = cfg["attack_keys"]
    v.setdefault("takes", []).append({"directions": a.dirs.split(","), "reseed": a.reseed})
    src.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
