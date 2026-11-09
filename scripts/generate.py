"""Generate units with PixelLab from their prompt YAML.

  export PIXELLAB_API_KEY=...
  python scripts/generate.py candidates prompts/units/<id>.yaml [--n 3]
      Create N 8-direction characters (seeds seed, seed+1, ...) and write a
      contact sheet to units/<id>/candidates.png so the best one can be picked.
  python scripts/generate.py pick prompts/units/<id>.yaml <character_id>
  python scripts/generate.py animate prompts/units/<id>.yaml [--anims idle,walk] [--dirs south,east]
      Queue every missing animation x drawn-direction (concurrently, as far as
      the plan allows) and download the result.
  python scripts/generate.py redo prompts/units/<id>.yaml walk/east [attack/south ...]
      Delete those directions and generate them again.
  python scripts/generate.py download prompts/units/<id>.yaml

Every step is recorded in units/<id>/source.json (ids, requests, cost), which is
also the provenance record. Re-running never pays twice for finished work.
"""
import argparse
import datetime as dt
import io
import json
import pathlib
import time
import zipfile

import requests
import yaml
from PIL import Image, ImageDraw

from pixellab_api import PixelLab

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIRS8 = ["south", "south-east", "east", "north-east", "north", "north-west", "west", "south-west"]


def load_unit(path):
    style = yaml.safe_load((ROOT / "prompts/style.yaml").read_text())
    unit = yaml.safe_load(pathlib.Path(path).read_text())
    u = {**style, **unit}
    # animation list: style defaults, overridden / extended per unit
    anims = {a["name"]: dict(a) for a in style.get("default_animations", [])}
    for a in unit.get("animations", []):
        anims[a["name"]] = {**anims.get(a["name"], {}), **a}
    u["animations"] = [a for a in anims.values() if not a.get("skip")]
    return u


class Unit:
    def __init__(self, path):
        self.cfg = load_unit(path)
        self.dir = ROOT / "units" / self.cfg["id"]
        self.dir.mkdir(parents=True, exist_ok=True)
        self.src_path = self.dir / "source.json"
        self.src = json.loads(self.src_path.read_text()) if self.src_path.exists() else {
            "id": self.cfg["id"], "tool": "PixelLab API v2",
            "license": "PixelLab Terms of Service - commercial use allowed on paid plans",
            "created": dt.date.today().isoformat(), "generations_spent": 0, "animations": {},
        }
        self.api = PixelLab()

    def save(self):
        self.src["updated"] = dt.date.today().isoformat()
        self.src_path.write_text(json.dumps(self.src, indent=2, ensure_ascii=False) + "\n")

    def spend(self, job):
        g = (job.get("usage") or {}).get("generations") or 0
        self.src["generations_spent"] = round(self.src["generations_spent"] + g, 3)

    # ---- generic concurrent runner -------------------------------------
    def run_jobs(self, tasks):
        """tasks: list of (label, submit_fn, on_done_fn). submit_fn returns job ids."""
        pending, inflight = list(tasks), []
        while pending or inflight:
            while pending:
                label, submit, done = pending[0]
                try:
                    jobs = submit()
                except RuntimeError as e:
                    if "429" in str(e):
                        break  # concurrency cap reached: wait for something to finish
                    raise
                pending.pop(0)
                print("queued", label, flush=True)
                inflight.append([label, list(jobs), done])
            time.sleep(6)
            for item in list(inflight):
                label, jobs, done = item
                for jid in list(jobs):
                    j = self.api.get(f"/background-jobs/{jid}")
                    if j.get("status") == "completed":
                        self.spend(j)
                        jobs.remove(jid)
                    elif j.get("status") == "failed":
                        print("FAILED", label, str(j)[:400], flush=True)
                        jobs.remove(jid)
                        item.append("failed")
                if not jobs:
                    inflight.remove(item)
                    if "failed" not in item:
                        done()
                        print("done", label, flush=True)
                    self.save()

    # ---- steps -----------------------------------------------------------
    def create_body(self, seed):
        u = self.cfg
        body = {k: u[k] for k in ("description", "view", "template_id", "outline", "detail", "no_background")}
        body.update(seed=seed, name=u["id"], image_size={"width": u["canvas"], "height": u["canvas"]})
        return body

    def candidates(self, n):
        cands = self.src.setdefault("candidates", [])
        have = {c["seed"] for c in cands}
        tasks = []
        for i in range(n):
            seed = self.cfg["seed"] + i
            if seed in have:
                continue
            body = self.create_body(seed)
            rec = {"seed": seed}

            def submit(body=body, rec=rec):
                r = self.api.post("/create-character-v3", body)
                rec["character_id"] = r["character_id"]
                return [r["background_job_id"]]

            def done(rec=rec):
                cands.append(rec)

            tasks.append((f"candidate seed={seed}", submit, done))
        self.src["create_request"] = self.create_body(self.cfg["seed"])
        self.run_jobs(tasks)
        self.save()
        self.contact_sheet()

    def contact_sheet(self, scale=4):
        cands = self.src.get("candidates", [])
        rows = []
        for c in cands:
            info = self.api.get(f"/characters/{c['character_id']}")
            urls = info.get("rotation_urls") or info.get("rotations") or {}
            ims = []
            for d in DIRS8:
                url = urls.get(d) if isinstance(urls, dict) else None
                if isinstance(url, dict):
                    url = url.get("url")
                if not url:
                    continue
                ims.append(Image.open(io.BytesIO(requests.get(url, timeout=60).content)).convert("RGBA"))
            rows.append((c, ims))
        if not rows or not rows[0][1]:
            print("no rotation urls found; keys:", list(info))
            return
        s = self.cfg["canvas"]
        sheet = Image.new("RGBA", (s * 8 * scale + 120, s * scale * len(rows)), (196, 206, 214, 255))
        dr = ImageDraw.Draw(sheet)
        for r, (c, ims) in enumerate(rows):
            dr.text((4, r * s * scale + 4), f"seed {c['seed']}\n{c['character_id'][:8]}", fill=(0, 0, 0, 255))
            for i, im in enumerate(ims):
                sheet.alpha_composite(im.resize((im.width * scale, im.height * scale), Image.NEAREST),
                                      (120 + i * s * scale, r * s * scale))
        sheet.save(self.dir / "candidates.png")
        print("contact sheet:", self.dir / "candidates.png")

    def pick(self, cid):
        self.src["character_id"] = cid
        for c in self.src.get("candidates", []):
            c["picked"] = c["character_id"] == cid
            if c["picked"]:
                self.src["create_request"] = self.create_body(c["seed"])
        self.save()

    def animate(self, anims=None, dirs=None):
        cid = self.src["character_id"]
        dirs = dirs or self.cfg["drawn_directions"]
        tasks = []
        for a in self.cfg["animations"]:
            if anims and a["name"] not in anims:
                continue
            rec = self.src["animations"].setdefault(a["name"], {"directions": {}})
            rec["request"] = {"action": a["action"], "frames": a["frames"]}
            for d in dirs:
                if rec["directions"].get(d) == "done":
                    continue
                body = {"character_id": cid, "mode": "v3", "animation_name": a["name"],
                        "action_description": a["action"], "frame_count": a["frames"],
                        "keep_first_frame": False, "directions": [d]}

                def submit(body=body, rec=rec):
                    if rec.get("animation_group_id"):
                        body["animation_group_id"] = rec["animation_group_id"]
                    r = self.api.post("/characters/animations", body)
                    rec["animation_group_id"] = r.get("animation_group_id") or rec.get("animation_group_id")
                    return r.get("background_job_ids") or [r["background_job_id"]]

                def done(rec=rec, d=d):
                    rec["directions"][d] = "done"

                tasks.append((f"{a['name']}/{d}", submit, done))
        # the first direction of each animation creates its group; run those first
        firsts, rest, seen = [], [], set()
        for t in tasks:
            name = t[0].split("/")[0]
            (rest if name in seen or self.src["animations"][name].get("animation_group_id") else firsts).append(t)
            seen.add(name)
        self.run_jobs(firsts)
        self.run_jobs(rest)
        self.save()
        self.download()

    def redo(self, items):
        cid = self.src["character_id"]
        by_anim = {}
        for it in items:
            name, d = it.split("/")
            rec = self.src["animations"][name]
            self.api._req("DELETE", f"/characters/{cid}/animations/{rec['animation_group_id']}/directions/{d}")
            rec["directions"].pop(d, None)
            if not rec["directions"]:
                # PixelLab drops a group once its last direction is deleted
                rec.pop("animation_group_id", None)
            by_anim.setdefault(name, []).append(d)
        self.save()
        for name, ds in by_anim.items():
            self.animate([name], ds)

    def download(self):
        z = zipfile.ZipFile(io.BytesIO(self.api.download(f"/characters/{self.src['character_id']}/zip")))
        raw = self.dir / "raw"
        if raw.exists():
            for p in sorted(raw.rglob("*"), reverse=True):
                p.unlink() if p.is_file() else p.rmdir()
        z.extractall(raw)
        self.save()
        print("saved", raw, "| unit generations:", self.src["generations_spent"],
              "| balance:", self.api.balance()["subscription"]["generations"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["candidates", "pick", "animate", "redo", "download", "sheet"])
    ap.add_argument("unit")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--anims")
    ap.add_argument("--dirs")
    a = ap.parse_args()
    u = Unit(a.unit)
    if a.cmd == "candidates":
        u.candidates(a.n)
    elif a.cmd == "sheet":
        u.contact_sheet()
    elif a.cmd == "pick":
        u.pick(a.args[0])
    elif a.cmd == "animate":
        u.animate(a.anims.split(",") if a.anims else None, a.dirs.split(",") if a.dirs else None)
    elif a.cmd == "redo":
        u.redo(a.args)
    elif a.cmd == "download":
        u.download()


if __name__ == "__main__":
    main()
