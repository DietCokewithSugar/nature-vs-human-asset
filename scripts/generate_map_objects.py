"""Generate map objects (volcano, resource points, trees) from prompts/map_objects.yaml.

Usage:
  PIXELLAB_API_KEY=... python scripts/generate_map_objects.py candidates [id ...]
  python scripts/generate_map_objects.py pick <id> <seed> [name]

candidates: one PixelLab /map-objects call per seed; writes
objects/map/<id>/cand_<seed>.png and objects/map/<id>/candidates.png (side by side,
on a light and a dark strip). Existing candidates are skipped.
pick: copies the chosen candidate to objects/map/<id>.png and records it in
objects/map/objects.json (footprint, anchor, provenance).
"""
import json
import pathlib
import sys
import time

import yaml
from PIL import Image

from pixellab_api import PixelLab

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "objects/map"
CFG = yaml.safe_load((ROOT / "prompts/map_objects.yaml").read_text())
OBJ = {o["id"]: o for o in CFG["objects"]}


def body_for(o, seed):
    c = CFG["common"]
    return {"description": o["description"], "image_size": {"width": o["size"][0], "height": o["size"][1]},
            "view": c["view"], "outline": c["outline"], "shading": c["shading"], "detail": c["detail"], "seed": seed}


def candidates(ids):
    c = PixelLab()
    pending = []
    for oid in ids or OBJ:
        o = OBJ[oid]
        d = OUT / oid
        d.mkdir(parents=True, exist_ok=True)
        for seed in o["seeds"][: CFG["common"]["candidates"]]:
            if (d / f"cand_{seed}.png").exists():
                continue
            body = body_for(o, seed)
            r = c.post_when_free("/map-objects", body)
            pending.append((oid, seed, r["object_id"], body))
            print("queued", oid, seed, flush=True)
    for oid, seed, obj_id, body in pending:
        while True:
            r = c.s.get(f"https://api.pixellab.ai/v2/map-objects/{obj_id}", timeout=60)
            if r.status_code == 423:
                time.sleep(6)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"{oid} {seed}: {r.status_code} {r.text[:300]}")
            meta = r.json()
            if meta.get("status") == "completed":
                break
            time.sleep(6)
        png = c.s.get(meta["download_url"], timeout=120)
        png.raise_for_status()
        d = OUT / oid
        (d / f"cand_{seed}.png").write_bytes(png.content)
        (d / f"cand_{seed}.json").write_text(json.dumps({"object_id": obj_id, "request": body,
                                                         "tool": "PixelLab v2 /map-objects",
                                                         "date": time.strftime("%Y-%m-%d")}, indent=1) + "\n")
        print("saved", oid, seed, flush=True)
    for oid in ids or OBJ:
        sheet(oid)


def sheet(oid):
    d = OUT / oid
    ims = [(p, Image.open(p).convert("RGBA")) for p in sorted(d.glob("cand_*.png"))]
    if not ims:
        return
    w = sum(im.width for _, im in ims) + 8 * (len(ims) + 1)
    h = max(im.height for _, im in ims)
    out = Image.new("RGBA", (w, h * 2 + 24), (0, 0, 0, 0))
    out.paste((230, 236, 242, 255), (0, 0, w, h + 12))
    out.paste((52, 58, 66, 255), (0, h + 12, w, h * 2 + 24))
    x = 8
    for _, im in ims:
        out.alpha_composite(im, (x, 6 + h - im.height))
        out.alpha_composite(im, (x, h + 18 + h - im.height))
        x += im.width + 8
    out.resize((out.width * 3, out.height * 3), Image.NEAREST).save(d / "candidates.png")


def pick(oid, seed, name=None):
    """name: register the candidate under another name (e.g. a second tree variant)."""
    o = OBJ[oid]
    src = OUT / oid / f"cand_{seed}.png"
    im = Image.open(src).convert("RGBA")
    name = name or oid
    im.save(OUT / f"{name}.png")
    reg_path = OUT / "objects.json"
    reg = json.loads(reg_path.read_text()) if reg_path.exists() else {}
    prov = json.loads((OUT / oid / f"cand_{seed}.json").read_text())
    reg[name] = {"source": oid, "png": f"{name}.png", "size": list(im.size), "footprint": o["footprint"],
                # pixel in the sprite that sits on the bottom-centre of the footprint
                "anchor": [im.width // 2, im.height - 1], "seed": int(seed),
                "object_id": prov["object_id"], "description": o["description"], "date": prov["date"]}
    reg_path.write_text(json.dumps(dict(sorted(reg.items())), indent=1, ensure_ascii=False) + "\n")
    print("picked", name, seed)


if __name__ == "__main__":
    if sys.argv[1] == "candidates":
        candidates(sys.argv[2:])
    elif sys.argv[1] == "pick":
        pick(*sys.argv[2:5])
    else:
        raise SystemExit(__doc__)
