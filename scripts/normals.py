"""Normal maps for dynamic lighting, via Sprite Fusion Sprite Normals (MIT).

  cargo install --git https://github.com/Hugo-Dz/spritefusion-sprite-normals --locked
  python scripts/normals.py [unit_id ...]        (default: every unit + every tileset)

Writes units/<id>/<id>_n.png (same layout as the spritesheet, one map per
frame cell) and tilesets/<id>_n.png. Tiles are processed one 32px tile at a
time with silhouette volume off, so tile borders do not turn into bevels.
postprocess.py calls this automatically when the CLI is installed.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BIN = os.environ.get("SPRITE_NORMALS_BIN") or shutil.which("spritefusion-sprite-normals")


def run(src, dst, *args):
    subprocess.run([BIN, str(src), "-o", str(dst), "--force", *args], check=True, capture_output=True)
    for extra in (dst.with_suffix(".color.png"), dst.with_suffix(".frames.json")):
        extra.unlink(missing_ok=True)


def unit(uid):
    """Frames come in a few cell sizes (base animations vs. wider attack
    variants): run each size as its own uniform sheet, then put the maps back
    at the frames' positions so the normal sheet matches the colour sheet."""
    from PIL import Image
    import tempfile
    d = ROOT / "units" / uid
    atlas = json.loads((d / f"{uid}.json").read_text())
    sheet = Image.open(d / f"{uid}.png").convert("RGBA")
    out = Image.new("RGBA", sheet.size)
    groups = {}
    for name, f in atlas["frames"].items():
        r = f["frame"]
        groups.setdefault(r["w"], []).append(r)
    with tempfile.TemporaryDirectory() as tmp:
        # the CLI caps one input at ~4.19M px (incl. padding): process big cells in chunks
        chunks = []
        for cell, rects in groups.items():
            per = max(1, 2_500_000 // (cell * cell))
            chunks += [(cell, rects[i:i + per]) for i in range(0, len(rects), per)]
        for k, (cell, rects) in enumerate(chunks):
            cols = max(1, min(len(rects), 2048 // cell))
            rows_ = (len(rects) + cols - 1) // cols
            tile = Image.new("RGBA", (cols * cell, rows_ * cell))
            for i, r in enumerate(rects):
                tile.paste(sheet.crop((r["x"], r["y"], r["x"] + cell, r["y"] + cell)), ((i % cols) * cell, (i // cols) * cell))
            src, dst = pathlib.Path(tmp) / f"s{cell}_{k}.png", pathlib.Path(tmp) / f"s{cell}_{k}_n.png"
            tile.save(src)
            run(src, dst, "--frame-size", f"{cell}x{cell}")
            nm = Image.open(dst).convert("RGBA")
            for i, r in enumerate(rects):
                x, y = (i % cols) * cell, (i // cols) * cell
                out.paste(nm.crop((x, y, x + cell, y + cell)), (r["x"], r["y"]))
    out.save(d / f"{uid}_n.png", optimize=True)
    print("normals:", uid)


def tilesets():
    for png in sorted((ROOT / "tilesets").glob("*.png")):
        if png.stem.endswith("_n"):
            continue
        meta = json.loads(png.with_suffix(".json").read_text())
        s = meta["tile_size"]
        run(png, png.with_name(f"{png.stem}_n.png"), "--frame-size", f"{s}x{s}",
            "--shape-strength", "0", "--normal-strength", "1")
        print("normals:", png.stem)


def available():
    return bool(BIN)


def main():
    if not BIN:
        sys.exit("spritefusion-sprite-normals not found (see the install line at the top of this file)")
    ids = sys.argv[1:]
    if not ids:
        ids = sorted(p.name for p in (ROOT / "units").iterdir() if (p / f"{p.name}.json").exists())
        tilesets()
    for uid in ids:
        unit(uid)


if __name__ == "__main__":
    main()
