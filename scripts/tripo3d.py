"""Tripo 3D pipeline for one unit: image -> 3D model -> quadruped rig -> walk animation.

  python scripts/tripo3d.py <unit_id> [--image path.png] [--rig-type quadruped]

The API key is never read or stored here: in the cloud environment the network
proxy adds it to requests for api.tripo3d.ai. Elsewhere set TRIPO_API_KEY.
Each step's task id is saved in units/<id>/tripo/state.json, so a rerun resumes
instead of paying twice. Outputs: units/<id>/tripo/{model,rigged,walk}.glb
"""
import argparse
import json
import os
import pathlib
import sys
import time

import requests
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://api.tripo3d.ai/v2/openapi"
S = requests.Session()
if os.environ.get("TRIPO_API_KEY"):
    S.headers["Authorization"] = f"Bearer {os.environ['TRIPO_API_KEY']}"


def call(method, path, **kw):
    for i in range(20):
        try:
            r = S.request(method, API + path, timeout=120, **kw)
            break
        except requests.exceptions.ConnectionError:
            time.sleep(15)
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError(f"{method} {path} -> {j}")
    return j["data"]


def balance():
    return call("GET", "/user/balance")


def wait(task_id, every=8):
    while True:
        d = call("GET", f"/task/{task_id}")
        st = d.get("status")
        if st == "success":
            return d
        if st in ("failed", "banned", "expired", "cancelled", "unknown"):
            raise RuntimeError(f"task {task_id} {st}: {json.dumps(d)[:600]}")
        print(f"  {d.get('type')} {st} {d.get('progress', '')}%", flush=True)
        time.sleep(every)


def concept_image(uid):
    """The approved PixelLab sprite (three-quarter view), cropped and scaled up 8x on white."""
    src = ROOT / "units" / uid / "raw" / "Idle" / "rotations" / "south-east.png"
    im = Image.open(src).convert("RGBA")
    im = im.crop(im.getbbox())
    s = max(im.size) + 8
    c = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    c.paste(im, ((s - im.width) // 2, (s - im.height) // 2))
    c = c.resize((s * 8, s * 8), Image.NEAREST)
    bg = Image.new("RGBA", c.size, (255, 255, 255, 255))
    bg.alpha_composite(c)
    out = ROOT / "units" / uid / "tripo" / "input.png"
    bg.convert("RGB").save(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("unit")
    ap.add_argument("--image")
    ap.add_argument("--rig-type", default="quadruped")
    ap.add_argument("--animations", default="preset:quadruped:walk")
    a = ap.parse_args()
    d = ROOT / "units" / a.unit / "tripo"
    d.mkdir(parents=True, exist_ok=True)
    sp = d / "state.json"
    st = json.loads(sp.read_text()) if sp.exists() else {"unit": a.unit}
    save = lambda: sp.write_text(json.dumps(st, indent=2) + "\n")
    print("balance", balance())

    def step(name, body, out_key="model", out_file=None):
        if st.get(name, {}).get("status") != "success":
            if not st.get(name, {}).get("task_id"):
                st[name] = {"task_id": call("POST", "/task", json=body)["task_id"], "request": body}
                save()
            print(name, st[name]["task_id"], flush=True)
            res = wait(st[name]["task_id"])
            st[name].update(status="success", output=res.get("output"), consumed=res.get("consumed_credit"))
            save()
        out = st[name].get("output") or {}
        url = out.get(out_key) or out.get("pbr_model") or out.get("model")
        if out_file and url and not (d / out_file).exists():
            (d / out_file).write_bytes(requests.get(url, timeout=300).content)
        return st[name]

    if "image_token" not in st:
        img = pathlib.Path(a.image) if a.image else concept_image(a.unit)
        with open(img, "rb") as f:
            st["image_token"] = call("POST", "/upload", files={"file": (img.name, f, "image/png")})["image_token"]
        save()
    m = step("model", {"type": "image_to_model", "model_version": "v2.5-20250123",
                       "file": {"type": "png", "file_token": st["image_token"]},
                       "texture": True, "pbr": True, "face_limit": 20000}, out_file="model.glb")
    chk = step("rigcheck", {"type": "animate_prerigcheck", "original_model_task_id": m["task_id"]})
    print("rig check:", chk.get("output"))
    r = step("rig", {"type": "animate_rig", "original_model_task_id": m["task_id"], "out_format": "glb",
                     "rig_type": a.rig_type, "spec": "tripo"}, out_file="rigged.glb")
    step("walk", {"type": "animate_retarget", "original_model_task_id": r["task_id"], "out_format": "glb",
                  "animation": a.animations, "bake_animation": True, "animate_in_place": True}, out_file="walk.glb")
    print("done; credits left:", balance())


if __name__ == "__main__":
    sys.exit(main())
