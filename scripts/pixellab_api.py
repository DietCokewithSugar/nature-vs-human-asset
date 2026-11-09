"""Minimal PixelLab v2 REST client.

The API token is read from the PIXELLAB_API_KEY environment variable and is
never written to disk by these scripts.
"""
import os
import time

import requests

BASE = "https://api.pixellab.ai/v2"


class PixelLab:
    def __init__(self, token=None):
        token = token or os.environ.get("PIXELLAB_API_KEY")
        if not token:
            raise SystemExit("Set PIXELLAB_API_KEY first.")
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"

    def _req(self, method, path, **kw):
        r = self.s.request(method, BASE + path, timeout=120, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:800]}")
        return r

    def get(self, path, **kw):
        return self._req("GET", path, **kw).json()

    def post(self, path, body):
        return self._req("POST", path, json=body).json()

    def download(self, path):
        return self._req("GET", path).content

    def balance(self):
        return self.get("/balance")

    def wait_job(self, job_id, every=8, timeout=1200):
        t0 = time.time()
        while True:
            j = self.get(f"/background-jobs/{job_id}")
            st = j.get("status")
            if st == "completed":
                return j
            if st == "failed":
                raise RuntimeError(f"job {job_id} failed: {str(j)[:800]}")
            if time.time() - t0 > timeout:
                raise TimeoutError(job_id)
            time.sleep(every)
