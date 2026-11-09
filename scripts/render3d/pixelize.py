"""256px 3D renders -> 64px pixel sprites: block-mode downsample, shared palette, 1px dark outline.
python pixelize.py <render_dir> <out_dir> [--factor 4] [--colors 20] [--palette ref.png]"""
import sys, pathlib, argparse
import numpy as np
from PIL import Image

ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("dst")
ap.add_argument("--factor", type=int, default=4); ap.add_argument("--colors", type=int, default=20)
ap.add_argument("--palette"); a = ap.parse_args()
src, dst, f = pathlib.Path(a.src), pathlib.Path(a.dst), a.factor
files = sorted(src.rglob("frame_*.png"))

def down(im):
    x = np.array(im.convert("RGBA")); h, w = x.shape[0] // f, x.shape[1] // f
    b = x[:h * f, :w * f].reshape(h, f, w, f, 4).transpose(0, 2, 1, 3, 4).reshape(h, w, f * f, 4)
    op = b[..., 3] > 127
    out = np.zeros((h, w, 4), np.uint8)
    keep = op.sum(-1) >= (f * f) * 0.4
    for y, xx in zip(*np.nonzero(keep)):
        px = b[y, xx][op[y, xx]][:, :3]
        out[y, xx, :3] = np.median(px, axis=0)   # median keeps edges crisp, no colour blending across bands
        out[y, xx, 3] = 255
    return out

smalls = [down(Image.open(p)) for p in files]
# one palette for the whole unit (all frames, all directions) so colours never flicker
allpx = np.concatenate([s[s[..., 3] > 0][:, :3] for s in smalls])
if a.palette:
    r = np.array(Image.open(a.palette).convert("RGBA")); pal = np.unique(r[r[..., 3] > 127][:, :3], axis=0)
else:
    pal = np.array(Image.fromarray(allpx[None].astype(np.uint8)).quantize(a.colors, method=Image.Quantize.MEDIANCUT).convert("RGB")).reshape(-1, 3)
    pal = np.unique(pal, axis=0)
pal = pal.astype(float)
lum = pal @ [0.299, 0.587, 0.114]
outline = (pal[lum.argmin()] * 0.6).astype(np.uint8)   # darker than the darkest body colour
for p, s in zip(files, smalls):
    m = s[..., 3] > 0
    px = s[..., :3][m].astype(float)
    s[..., :3][m] = pal[((px[:, None] - pal[None]) ** 2).sum(-1).argmin(1)].astype(np.uint8)
    pm = np.pad(m, 1)
    ring = ~m & (pm[:-2, 1:-1] | pm[2:, 1:-1] | pm[1:-1, :-2] | pm[1:-1, 2:])
    s[ring, :3] = outline; s[ring, 3] = 255
    o = dst / p.relative_to(src); o.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(s).save(o)
print(len(files), "frames, palette", len(pal))
