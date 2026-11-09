"""Generate the Wang tilesets listed in prompts/tilesets.yaml.

Usage: PIXELLAB_API_KEY=... python scripts/generate_tilesets.py [prompts/tilesets.yaml]

Writes tilesets/<id>.png (4x4 atlas of 32px tiles) and tilesets/<id>.json
(per tile: atlas cell and its NW/NE/SW/SE corners as "lower"/"upper").
Already generated sets are skipped.
"""
import base64
import io
import json
import pathlib
import time

import yaml
from PIL import Image

from pixellab_api import PixelLab

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    import sys
    cfg = yaml.safe_load((ROOT / (sys.argv[1] if len(sys.argv) > 1 else "prompts/tilesets.yaml")).read_text())
    out = ROOT / "tilesets"
    out.mkdir(exist_ok=True)
    c = PixelLab()
    jobs = {}
    for ts in cfg["tilesets"]:
        if (out / f"{ts['id']}.json").exists():
            continue
        body = {**cfg["common"], **{k: v for k, v in ts.items() if k != "id"}}
        r = c.post_when_free("/create-tileset", body)
        print("queued", ts["id"], r.get("tileset_id"), flush=True)
        jobs[ts["id"]] = (r, body)
    for tid, (r, body) in jobs.items():
        if r.get("background_job_id"):
            c.wait_job(r["background_job_id"])
        while True:
            t = c.get(f"/tilesets/{r['tileset_id']}")
            if (t.get("tileset") or t).get("tiles"):
                break
            time.sleep(8)
        tiles = (t.get("tileset") or t)["tiles"]
        size = body["tile_size"]["width"]
        n = len(tiles)
        cols = 4  # 4x4 atlas
        atlas = Image.new("RGBA", (cols * size, ((n + cols - 1) // cols) * size))
        meta = {"id": tid, "tileset_id": r["tileset_id"], "tile_size": size, "request": body, "tiles": []}
        for i, tile in enumerate(tiles):
            img = tile["image"]
            b64 = img.get("base64") if isinstance(img, dict) else img
            im = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
            x, y = (i % cols) * size, (i // cols) * size
            atlas.paste(im, (x, y))
            meta["tiles"].append({"x": x, "y": y, "corners": tile.get("corners")})
        atlas.save(out / f"{tid}.png")
        (out / f"{tid}.json").write_text(json.dumps(meta, indent=1) + "\n")
        print("saved", tid, n, "tiles", flush=True)


if __name__ == "__main__":
    main()
