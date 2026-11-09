"""Generate the terrain base textures listed in prompts/terrain_ice.yaml.

Usage: PIXELLAB_API_KEY=... python scripts/generate_terrain.py [set_id ...]

Each set is one PixelLab Wang tileset (pro mode, 32px). Writes
terrain/raw/<set>.png (4x4 atlas) and terrain/raw/<set>.json (request,
tile ids, corners). Sets already on disk are skipped. Then run
scripts/build_terrain_atlas.py.
"""
import base64
import io
import json
import pathlib
import sys
import time

import yaml
from PIL import Image

from pixellab_api import PixelLab

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    cfg = yaml.safe_load((ROOT / "prompts/terrain_ice.yaml").read_text())
    out = ROOT / "terrain/raw"
    out.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    c = PixelLab()
    jobs = {}
    for s in cfg["sets"]:
        if only and s["id"] not in only:
            continue
        if (out / f"{s['id']}.json").exists():
            continue
        body = {**cfg["common"], "seed": s["seed"],
                "lower_description": s["lower"]["description"], "upper_description": s["upper"]["description"]}
        b0 = c.balance()["subscription"]["generations"]
        r = c.post_when_free("/create-tileset", body)
        print("queued", s["id"], r.get("tileset_id"), flush=True)
        jobs[s["id"]] = (r, body, s, b0)
    for sid, (r, body, s, b0) in jobs.items():
        if r.get("background_job_id"):
            c.wait_job(r["background_job_id"])
        while True:
            t = c.get(f"/tilesets/{r['tileset_id']}")
            t = t.get("tileset") or t
            if t.get("tiles"):
                break
            time.sleep(8)
        atlas = Image.new("RGBA", (128, 128))
        meta = {"id": sid, "tileset_id": r["tileset_id"], "tool": "PixelLab v2 /create-tileset",
                "date": time.strftime("%Y-%m-%d"), "request": body,
                "lower": s["lower"]["terrain"], "upper": s["upper"]["terrain"], "tiles": []}
        for i, tile in enumerate(t["tiles"]):
            img = tile["image"]
            b64 = img.get("base64") if isinstance(img, dict) else img
            im = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
            x, y = (i % 4) * 32, (i // 4) * 32
            atlas.paste(im, (x, y))
            meta["tiles"].append({"x": x, "y": y, "id": tile.get("id"), "corners": tile.get("corners")})
        atlas.save(out / f"{sid}.png")
        (out / f"{sid}.json").write_text(json.dumps(meta, indent=1) + "\n")
        print("saved", sid, flush=True)


if __name__ == "__main__":
    main()
