"""Generate a unit with PixelLab from its prompt YAML.

Usage:
  PIXELLAB_API_KEY=... python scripts/generate.py prompts/units/<id>.yaml [--anims walk,attack] [--dirs south,east]

Steps (each is skipped if already done, so re-running never double-charges):
  1. create the 8-direction character (create-character-v3)
  2. queue each animation for the drawn directions only (mirrored ones are free)
  3. download the character ZIP into units/<id>/raw/
Progress, ids and billing are recorded in units/<id>/source.json, which also
serves as the provenance record (tool, date, prompt, cost).
"""
import argparse
import datetime as dt
import io
import json
import pathlib
import zipfile

import yaml

from pixellab_api import PixelLab

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_unit(path):
    style = yaml.safe_load((ROOT / "prompts/style.yaml").read_text())
    unit = yaml.safe_load(pathlib.Path(path).read_text())
    return {**style, **unit}


def save(src_path, src):
    src_path.write_text(json.dumps(src, indent=2, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("unit")
    ap.add_argument("--anims", help="comma list of animation names (default: all)")
    ap.add_argument("--dirs", help="comma list of directions (default: drawn_directions)")
    ap.add_argument("--character-id", help="adopt an already-created character")
    a = ap.parse_args()

    u = load_unit(a.unit)
    out = ROOT / "units" / u["id"]
    out.mkdir(parents=True, exist_ok=True)
    src_path = out / "source.json"
    src = json.loads(src_path.read_text()) if src_path.exists() else {
        "id": u["id"], "tool": "PixelLab API v2", "license": "PixelLab ToS (commercial use per plan)",
        "created": dt.date.today().isoformat(), "generations_spent": 0, "animations": {},
    }
    c = PixelLab()

    def spend(job):
        g = (job.get("usage") or {}).get("generations") or 0
        src["generations_spent"] = round(src["generations_spent"] + g, 3)

    # 1. character
    if a.character_id:
        src["character_id"] = a.character_id
    if not src.get("character_id"):
        body = {k: u[k] for k in ("description", "view", "template_id", "outline", "detail", "no_background", "seed")}
        body["image_size"] = {"width": u["canvas"], "height": u["canvas"]}
        body["name"] = u["id"]
        r = c.post("/create-character-v3", body)
        src.update(character_id=r["character_id"], create_request=body)
        save(src_path, src)
        print("creating character", r["character_id"])
        spend(c.wait_job(r["background_job_id"]))
        save(src_path, src)

    # 2. animations
    dirs = a.dirs.split(",") if a.dirs else u["drawn_directions"]
    wanted = a.anims.split(",") if a.anims else [x["name"] for x in u.get("animations", [])]
    for anim in u.get("animations", []):
        if anim["name"] not in wanted:
            continue
        rec = src["animations"].setdefault(anim["name"], {"directions": {}})
        for d in dirs:
            if d in rec["directions"]:
                continue
            body = {"character_id": src["character_id"], "mode": "v3", "animation_name": anim["name"],
                    "action_description": anim["action"], "frame_count": anim["frames"],
                    "keep_first_frame": False, "directions": [d]}
            if rec.get("animation_group_id"):
                body["animation_group_id"] = rec["animation_group_id"]
            r = c.post("/characters/animations", body)
            rec["animation_group_id"] = r.get("animation_group_id", rec.get("animation_group_id"))
            job_ids = r.get("background_job_ids") or [r.get("background_job_id")]
            print(f"animating {anim['name']}/{d}", job_ids)
            for jid in job_ids:
                spend(c.wait_job(jid))
            rec["directions"][d] = "done"
            save(src_path, src)

    # 3. download
    z = zipfile.ZipFile(io.BytesIO(c.download(f"/characters/{src['character_id']}/zip")))
    raw = out / "raw"
    z.extractall(raw)
    save(src_path, src)
    print("saved", raw, "| generations spent on this unit:", src["generations_spent"], "| balance:", c.balance()["subscription"])


if __name__ == "__main__":
    main()
