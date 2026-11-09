"""Experiment B: same species at a bigger canvas (and Pro character mode) to see
how much detail the size buys. Creates characters, a walk facing east, and
saves the east rotation + walk frames. Does not touch units/."""
import io, json, pathlib, sys, zipfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
from concurrent.futures import ThreadPoolExecutor
import yaml
from pixellab_api import PixelLab

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path(__file__).resolve().parent / "units"
api = PixelLab()


def cfg(uid):
    return yaml.safe_load((ROOT / "prompts/units" / f"{uid}.yaml").read_text())


def make(tag, uid, size, mode, seed, walk):
    c = cfg(uid)
    if mode == "v3":
        body = {"description": c["description"], "image_size": {"width": size, "height": size}, "view": "low top-down",
                "template_id": c["template_id"], "outline": "single color black outline", "detail": "highly detailed",
                "no_background": True, "seed": seed, "name": f"exp_{tag}"}
        r = api.post_when_free("/create-character-v3", body)
    else:
        body = {"description": c["description"], "image_size": {"width": size, "height": size}, "view": "low top-down",
                "template_id": c["template_id"], "no_background": True, "seed": seed}
        r = api.post_when_free("/create-character-pro", body)
    cid = r["character_id"]
    spent = (api.wait_job(r["background_job_id"]).get("usage") or {}).get("generations", 0)
    a = api.post_when_free("/characters/animations", {"character_id": cid, "mode": "v3", "animation_name": "walk",
                                                      "action_description": walk, "frame_count": 6, "keep_first_frame": False,
                                                      "directions": ["east"]})
    for jid in a.get("background_job_ids") or [a["background_job_id"]]:
        spent += (api.wait_job(jid).get("usage") or {}).get("generations", 0)
    z = zipfile.ZipFile(io.BytesIO(api.download(f"/characters/{cid}/zip")))
    d = OUT / tag
    z.extractall(d)
    return {"tag": tag, "uid": uid, "size": size, "mode": mode, "character_id": cid, "generations": spent}


runs = [
    ("hyena_64_v3_a", "nature_ice_cave_hyena", 64, "v3", 7311, "loping walk with a sloping back, seamless loop"),
    ("hyena_64_v3_b", "nature_ice_cave_hyena", 64, "v3", 7312, "loping walk with a sloping back, seamless loop"),
    ("hyena_64_pro", "nature_ice_cave_hyena", 64, "pro", 7313, "loping walk with a sloping back, seamless loop"),
    ("mammoth_128_v3_a", "nature_ice_mammoth", 128, "v3", 2011, "slow heavy walk, trunk swaying"),
    ("mammoth_128_v3_b", "nature_ice_mammoth", 128, "v3", 2012, "slow heavy walk, trunk swaying"),
]


def safe(r):
    try:
        return make(*r)
    except Exception as e:
        return {"tag": r[0], "error": str(e)[:300]}


with ThreadPoolExecutor(5) as ex:
    res = list(ex.map(safe, runs))
(OUT / "results.json").write_text(json.dumps(res, indent=1))
for r in res:
    print(r)
print("balance", api.balance()["subscription"]["generations"])
