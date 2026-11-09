"""Snapshot the species design sheet into the repo.

Usage: python scripts/sync_species.py

Downloads the public CSV export of every tab listed in TABS and writes
data/<tab>.csv (raw snapshot) plus data/species.json (cleaned rows with their
sheet row number, used by the website's config pages). Re-run after editing
the sheet.
"""
import csv
import io
import json
import pathlib
import urllib.parse

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHEET_ID = "1NQ9TBRseSb1iqrrHwrV7DRQFJxaTeaqc93uk4QEYcfY"
TABS = {"生物": "creatures", "人类": "humans"}


def fetch(tab):
    url = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet="
           + urllib.parse.quote(tab))
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content.decode("utf-8")


def main():
    out = {"sheet_url": f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit", "tabs": {}}
    for tab, slug in TABS.items():
        text = fetch(tab)
        (ROOT / "data" / f"{slug}.csv").write_text(text)
        rows = list(csv.reader(io.StringIO(text)))
        header = [h.strip() for h in rows[0]]
        items = []
        for i, r in enumerate(rows[1:], start=2):
            rec = {h: (r[j].strip() if j < len(r) else "") for j, h in enumerate(header) if h}
            if not any(v for k, v in rec.items() if k not in ("时代", "是否已生成")):
                continue
            items.append({"row": i, **rec})
        out["tabs"][tab] = {"header": [h for h in header if h], "rows": items}
        print(f"{tab}: {len(items)} rows")
    (ROOT / "data" / "species.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
