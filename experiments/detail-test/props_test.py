"""Experiment A: static stone-age camp props, three PixelLab image models.
Writes PNGs + results.json (cost per call) next to this file."""
import base64, io, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from pixellab_api import PixelLab

OUT = pathlib.Path(__file__).resolve().parent / "props"
api = PixelLab()
STYLE = ("top-down 3/4 view pixel art game asset, clean dark outline, soft cel shading, light from the top-left, "
         "earthy prehistoric palette")
PROPS = {
    "hide_tent": "a prehistoric hide tent made of stitched animal skins over wooden poles",
    "campfire": "a stone ring campfire with burning logs",
    "drying_rack": "a wooden meat drying rack with an animal pelt hanging on it",
    "mammoth_bone_hut": "a round hut built from mammoth bones and tusks covered with hides",
}


def imgs(job):
    lr = job["last_response"]
    arr = lr.get("images") or ([lr["image"]] if "image" in lr else [])
    return [Image.open(io.BytesIO(base64.b64decode(i["base64"] if isinstance(i, dict) else i))).convert("RGBA") for i in arr]


def run(tag, path, body):
    r = api.post_when_free(path, body)
    if "background_job_id" in r:
        j = api.wait_job(r["background_job_id"])
    else:
        j = {"last_response": r, "usage": r.get("usage")}
    ims = imgs(j)
    for i, im in enumerate(ims):
        im.save(OUT / f"{tag}_{i}.png")
    return {"tag": tag, "endpoint": path, "n": len(ims), "usage": j.get("usage")}


jobs = []
# 1) one Pixen image holding a whole prop sheet (like the bundle's marketing sheets)
jobs.append(("pixen_sheet", "/create-image-pixen", {
    "description": "sprite sheet of stone age camp props evenly spaced on a plain light background: hide tent, stone ring campfire, "
                   "meat drying rack with pelt, mammoth bone hut, clay pots, stone axe, bone spear, fur rug, log pile. " + STYLE,
    "image_size": {"width": 384, "height": 256}, "no_background": False, "view": "low top-down", "seed": 9101}))
# 2) Pro image model, one prop per call (returns a grid of variants)
for k, d in PROPS.items():
    jobs.append((f"pro_{k}", "/generate-image-v2", {
        "description": f"{d}, {STYLE}", "image_size": {"width": 96, "height": 96}, "no_background": True, "seed": 9201}))
# 3) Pro Flash, one native image per prop
for k, d in list(PROPS.items())[:2]:
    jobs.append((f"flash_{k}", "/create-image-pro-flash", {
        "description": f"{d}, {STYLE}", "image_size": {"width": 96, "height": 96}, "no_background": True, "seed": 9301}))
# 4) Pixen per prop at 96px (cheap baseline)
for k, d in PROPS.items():
    jobs.append((f"pixen_{k}", "/create-image-pixen", {
        "description": f"{d}, {STYLE}", "image_size": {"width": 96, "height": 96}, "no_background": True,
        "view": "low top-down", "outline": "single color black outline", "seed": 9401}))

results = []
with ThreadPoolExecutor(6) as ex:
    for res in ex.map(lambda j: _safe(*j), jobs) if False else []:
        pass


def _safe(tag, path, body):
    try:
        return run(tag, path, body)
    except Exception as e:  # keep going; record the failure
        return {"tag": tag, "endpoint": path, "error": str(e)[:300]}


with ThreadPoolExecutor(6) as ex:
    results = list(ex.map(lambda j: _safe(*j), jobs))
(OUT / "results.json").write_text(json.dumps(results, indent=1))
for r in results:
    print(r)
print("balance", api.balance()["subscription"]["generations"])
