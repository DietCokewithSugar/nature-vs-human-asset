"""Attack variant "combo": AI draws the key poses, the hand-edit step does the rest.

  PIXELLAB_API_KEY=... python scripts/attack_combo.py <unit_id> [--dirs east,south-east]

Per drawn direction:
  1. AI draws the two key poses (anticipation, strike):
     --keys pixen: Pixen image edit of the base pose, prompts from `attack_keys`
                   (1 generation each; best for side and front views)
     --keys v3:    one v3 animation from the base pose; the frame pulled furthest
                   back and the one reaching furthest are taken (1 generation;
                   keeps diagonal/back camera angles, which Pixen edits lose)
  2. Hand-edit step (no AI in-betweens, so nothing drifts):
     - palette lock: every key-pose pixel snaps to the base pose's own colours
     - alignment: hind end and feet pinned to the base pose so the body does not jump
     - frames: stance, ease-in (warp), anticipation (held), smear (stretched strike +
       arc), strike (held hit), follow-through, recover (warp), overshoot, stance
     - timing from aseprite-ai-artist rules/44
Writes units/<id>/variants/attackcombo/<dir>/ (frames + sequence.json) and keeps
the raw AI keys as key_anticipation.png / key_strike.png for review.
"""
import argparse
import shutil
import subprocess
import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import yaml
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from attack_keyframes import FACING, KEEP, b64, images_of, pad  # noqa: E402
from handedit import FACE, Frame, base_frame, bright_colors, mag_for, regions  # noqa: E402
from pixellab_api import PixelLab  # noqa: E402
from postprocess import srgb_to_lab  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _patches(mask):
    """8-connected patches of True pixels (sprites are small: plain flood fill)."""
    seen = np.zeros(mask.shape, bool)
    h, w = mask.shape
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        stack, patch = [(y0, x0)], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            patch.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        yield patch


def palette_lock(im, base, keep_far=28.0, max_patch=0.03, face=None):
    """Snap every opaque pixel of `im` to the nearest (CIELAB) colour of `base`.
    Colours far from every base colour (e.g. the inside of an open mouth, which
    the closed-mouth base pose does not have) are kept, but only as small patches
    (each connected patch under `max_patch` of the sprite): a far colour spread
    over a big area (a red outline along the whole body) is drift, so it snaps."""
    a, b = np.array(im.convert("RGBA")), np.array(base.convert("RGBA"))
    pal = np.unique(b[b[..., 3] > 127][:, :3], axis=0).astype(float)
    if not len(pal):
        return im
    lab_p = srgb_to_lab(pal)
    m = a[..., 3] > 127
    px = a[..., :3][m].astype(float)
    uniq, inv = np.unique(px, axis=0, return_inverse=True)
    d = ((srgb_to_lab(uniq)[:, None] - lab_p[None]) ** 2).sum(-1)
    nearest = pal[d.argmin(1)]
    far = np.sqrt(d.min(1)) > keep_far
    # per-pixel: far colour?  then keep it only inside small connected patches
    far_px = np.zeros(m.shape, bool)
    far_px[m] = far[inv.ravel()]
    if face is not None:
        # new colours belong to the head end (open mouth, teeth, eyes): only keep
        # them in the front 40% of the body along the facing direction
        ys, xs = np.nonzero(m)
        proj = xs * face[0] + ys * face[1]
        cut = np.quantile(proj, 0.6)
        yy, xx = np.mgrid[:m.shape[0], :m.shape[1]]
        far_px &= (xx * face[0] + yy * face[1]) >= cut
    limit = max(4, max_patch * m.sum())
    keep = np.zeros(m.shape, bool)
    # a real new feature (mouth interior, teeth) sits inside the outline; colour
    # drift shows up on the silhouette edge, touching transparency
    edge = np.zeros(m.shape, bool)
    pad_m = np.pad(m, 1)
    edge[:] = ~(pad_m[:-2, 1:-1] & pad_m[2:, 1:-1] & pad_m[1:-1, :-2] & pad_m[1:-1, 2:])
    for patch in _patches(far_px):
        if len(patch) <= limit and not any(edge[y, x] for y, x in patch):
            for y, x in patch:
                keep[y, x] = True
    rgb = np.zeros(m.shape + (3,), np.uint8)
    rgb[m] = nearest[inv.ravel()].astype(np.uint8)
    rgb[keep] = a[..., :3][keep]
    out = np.zeros_like(a)
    out[..., :3] = rgb
    out[..., 3] = np.where(m, 255, 0)
    return Image.fromarray(out, "RGBA")


def align(im, base, d):
    """Pin the key pose to the base: same ground line; on side views the hind end
    stays where it was (the front is what moves); otherwise keep it centred."""
    bb, ba = im.getbbox(), base.getbbox()
    if not bb or not ba:
        return im
    fx, fy = FACE[d]
    dy = ba[3] - bb[3]
    if fx > 0.1:
        dx = ba[0] - bb[0]
    else:
        dx = round((ba[0] + ba[2]) / 2 - (bb[0] + bb[2]) / 2)
    out = Image.new("RGBA", im.size)
    out.alpha_composite(im, (int(dx), int(dy)))
    return out


def run_dir(api, uid, cfg, d, out, rebuild=False, reseed=0, key_source="pixen"):
    keys = cfg["attack_keys"]
    # attack_new_colors: false -> every pixel snaps to the base palette (no new mouth colours)
    keep_far = 28.0 if cfg.get("attack_new_colors", True) else float("inf")
    if not rebuild and not reseed and (out / "sequence.json").exists():
        print(uid, d, "already done, skipping", flush=True)
        return 0
    if not reseed and (out / "key_anticipation.png").exists() and (out / "key_strike.png").exists():
        rebuild = True   # resume: AI keys were already paid for
    face = FACING[d]
    back = " Seen from behind: the face and mouth are not visible." if d == "north" else ""
    base = base_frame(uid, d)
    size = base.w

    view = ("Keep exactly the same camera angle and three-quarter viewing direction as the input image; "
            "do not turn the body sideways or toward the viewer.") if d in ("south-east", "north-east", "north") else ""

    def edit(text, seed):
        r = api.post_when_free("/edit-image-pixen", {
            "image": b64(base.im), "description": f"{text.format(facing=face)}{back} {view} {KEEP}",
            "width": size, "height": size, "no_background": True, "seed": seed})
        return pad(images_of(api.wait_job(r["background_job_id"]))[0], size)

    spent = 0
    if key_source == "v3" and not (rebuild and (out / "key_strike.png").exists()):
        # v3 animates from the base pose and keeps its camera angle (Pixen edits
        # tend to turn diagonal/back views into side views): take the frame pulled
        # furthest back as the wind-up and the one reaching furthest as the strike
        fx_, fy_ = FACE[d]
        r = api.post_when_free("/animate-with-text-v3", {
            "first_frame": b64(base.im),
            "action": f"crouches low and pulls back, then lunges forward {face} and bites hard with jaws wide open, then recovers{back}",
            "frame_count": 8, "no_background": True, "seed": cfg["seed"] + 31 + reseed * 100})
        fr = [pad(x, size) for x in images_of(api.wait_job(r["background_job_id"]))]
        spent = 1

        def reach(im):
            a = np.array(im)[..., 3] > 127
            ys, xs = np.nonzero(a)
            if not len(xs):
                return 0.0
            return float(np.percentile((xs - size / 2) * fx_ + (ys - size / 2) * fy_, 98))
        rs = [reach(x) for x in fr]
        si = int(np.argmax(rs))
        ai = int(np.argmin(rs[:max(1, si)])) if si > 0 else 0
        raw_a, raw_s = fr[ai], fr[si]
        out.mkdir(parents=True, exist_ok=True)
        raw_a.save(out / "key_anticipation.png")
        raw_s.save(out / "key_strike.png")
    elif rebuild and (out / "key_strike.png").exists():   # reuse the AI keys, redo only the hand steps
        raw_a = Image.open(out / "key_anticipation.png").convert("RGBA")
        raw_s = Image.open(out / "key_strike.png").convert("RGBA")
    else:
        with ThreadPoolExecutor(2) as ex:
            fa = ex.submit(edit, keys["anticipation"], cfg["seed"] + 21 + reseed * 100)
            fs = ex.submit(edit, keys["strike"], cfg["seed"] + 22 + reseed * 100)
            raw_a, raw_s = fa.result(), fs.result()
        spent = 2
        out.mkdir(parents=True, exist_ok=True)
        raw_a.save(out / "key_anticipation.png")
        raw_s.save(out / "key_strike.png")
    antic = Frame(align(palette_lock(raw_a, base.im, face=FACE[d], keep_far=keep_far), base.im, d)).cleanup()
    strike = Frame(align(palette_lock(raw_s, base.im, face=FACE[d], keep_far=keep_far), base.im, d)).cleanup()

    fx, fy = FACE[d]
    mag = mag_for(cfg)
    region = "x+" if fx > 0.1 else "top"
    head, _ = regions(base, d)
    cols = bright_colors(strike, head)

    def from_(fr, ops):
        f = fr.copy()
        for op in ops:
            op(f)
        return f

    def smear(f):
        f.scale(1 + 0.12 * abs(fx), 1 + 0.08 * abs(fy), anchor="bottom")
        bb = f.im.getbbox()
        if bb:
            if abs(fx) > 0.1:
                xa = bb[2] - 2
                pts = [(xa - 3 * mag, bb[1] + (bb[3] - bb[1]) * 0.25), (xa + 2 * mag, (bb[1] + bb[3]) * 0.5), (xa - 2 * mag, bb[3] - 4)]
            else:
                ya = bb[3] - 2 if fy > 0 else bb[1] + 2
                pts = [(bb[0] + 4, ya), ((bb[0] + bb[2]) / 2, ya + fy * 3 * mag), (bb[2] - 4, ya)]
            f.smear(pts, cols)

    frames = [
        (100, base.copy()),
        (110, from_(base, [lambda f: f.warp(-fx * 2 * mag, -2 * mag if abs(fx) > 0.1 else -fy * 2 * mag, region)])),
        (220, antic),                                            # wind-up, held
        (50, from_(strike, [smear])),                            # smear
        (150, strike),                                           # hit, held
        (80, from_(strike, [lambda f: f.warp(-fx * 2 * mag, -fy * 2 * mag, region)])),   # follow-through
        (100, from_(base, [lambda f: f.warp(fx * 2 * mag, fy * 2 * mag, region)])),      # recover
        (50, from_(base, [lambda f: f.offset(round(-fx), round(-fy))])),               # overshoot
        (120, base.copy()),
    ]
    for i, (_, f) in enumerate(frames):
        f.im.save(out / f"frame_{i:02d}.png")
    (out / "sequence.json").write_text(json.dumps({
        "frames": [{"file": f"frame_{i:02d}.png", "ms": ms} for i, (ms, _) in enumerate(frames)], "hit": 4,
        "method": "combo: AI key poses (Pixen edit) + hand palette lock, alignment, smear, warp tweens, timing"}, indent=1) + "\n")
    print(uid, d, "ok", "(rebuilt from saved keys)" if not spent else "", flush=True)
    return spent


def north_fallback(uid):
    """Back view: copy the hand warp attack (AI key poses come out sideways)."""
    u = ROOT / "units" / uid
    src_dir, dst = u / "variants" / "attackhand" / "north", u / "variants" / "attackcombo" / "north"
    if not src_dir.exists():
        print(uid, "north: no hand attack to copy (run handedit.py build first)")
        return
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src_dir, dst)
    seq = dst / "sequence.json"
    meta = json.loads(seq.read_text()) if seq.exists() else {}
    meta["method"] = "hand warp attack (fallback: AI key poses turn the back view sideways)"
    seq.write_text(json.dumps(meta, indent=1) + "\n")
    srcp = u / "source.json"
    s = json.loads(srcp.read_text())
    v = s.setdefault("variants", {}).setdefault("attackcombo", {"generations": 0, "directions": []})
    v["directions"] = sorted(set(v.get("directions", [])) | {"north"})
    v["key_sources"] = {"south": "pixen", "east": "pixen", "south-east": "v3", "north-east": "v3",
                        "north": "hand warp (fallback)", **{k: x for k, x in (v.get("key_sources") or {}).items() if k != "north"}}
    srcp.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
    print(uid, "north: hand warp fallback")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("unit")
    ap.add_argument("--dirs", default="auto",
                    help="auto (batch default): south,east from Pixen keys; south-east,north-east from v3 keys; "
                         "north copied from the hand warp attack (both AI key sources turn the back view sideways)")
    ap.add_argument("--rebuild", action="store_true", help="reuse saved AI key poses; redo only the hand steps")
    ap.add_argument("--reseed", type=int, default=0, help="new take of the AI key poses")
    ap.add_argument("--keys", default="pixen", choices=["pixen", "v3"],
                    help="pixen: image edit (best for side/front views); v3: pick keys from a v3 animation (keeps diagonal/back angles)")
    a = ap.parse_args()
    if a.dirs == "auto":
        plan = {"pixen": ["south", "east"], "v3": ["south-east", "north-east"]}
        for keys, dirs in plan.items():
            sub = [x for x in sys.argv[1:] if not x.startswith("--dirs") and not x.startswith("--keys")]
            subprocess.run([sys.executable, __file__, *sub, "--dirs", ",".join(dirs), "--keys", keys], check=True)
        north_fallback(a.unit)
        return
    style = yaml.safe_load((ROOT / "prompts/style.yaml").read_text())
    cfg = {**style, **yaml.safe_load((ROOT / "prompts/units" / f"{a.unit}.yaml").read_text())}
    api = PixelLab()
    root = ROOT / "units" / a.unit / "variants" / "attackcombo"
    with ThreadPoolExecutor(5) as ex:
        spent = sum(ex.map(lambda d: run_dir(api, a.unit, cfg, d, root / d, a.rebuild, a.reseed, a.keys), a.dirs.split(",")))
    src = ROOT / "units" / a.unit / "source.json"
    s = json.loads(src.read_text())
    s["generations_spent"] = round(s["generations_spent"] + spent, 3)
    v = s.setdefault("variants", {}).setdefault("attackcombo", {"generations": 0, "directions": []})
    v.update(method="AI key poses (Pixen edit) + AI hand-edit cleanup/tweens/timing", keys=cfg["attack_keys"])
    v["generations"] = round(v.get("generations", 0) + spent, 3)
    v["directions"] = sorted(set(v.get("directions", [])) | set(a.dirs.split(",")))
    src.write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
