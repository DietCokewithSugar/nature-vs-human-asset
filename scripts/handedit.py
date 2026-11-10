"""Hand-edit pixel frames the way an artist works in Aseprite, from text.

This is the "grid loop" method from aseprite-ai-artist (MIT): the frame is read
as a palette-indexed character grid, edited as text / with select-and-move
style operations, and written back. No Aseprite needed - the canvas is a PNG.

  python scripts/handedit.py dump <png> [out.png]      grid text + zoomed coordinate view
  python scripts/handedit.py build <unit_id> [...]      attack + death for the 5 drawn directions

Selections (head, front legs) are found automatically from the silhouette; the
unit YAML's `handedit: {kind: lunge|swarm, heavy, mag}` sets the style. An
optional prompts/handedit/<unit>.py (DIRS = {dir: [(ms, [ops])]}, HIT = {dir: i})
overrides individual directions with hand-tuned selections.
"""
import importlib.util
import json
import math
import pathlib
import string
import sys

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHARS = string.ascii_letters + string.digits + "#$%&*+=?@^~<>"


class Frame:
    def __init__(self, im):
        self.im = im.convert("RGBA")

    @property
    def w(self):
        return self.im.width

    def copy(self):
        return Frame(self.im.copy())

    # --- selection-style edits -------------------------------------------
    def move(self, rect, dx, dy, heal=True):
        """Cut the opaque pixels inside rect=(x0,y0,x1,y1) and paste them offset."""
        x0, y0, x1, y1 = rect
        before = self.im.copy()
        part = self.im.crop((x0, y0, x1, y1))
        self.im.paste((0, 0, 0, 0), (x0, y0, x1, y1))
        self.im.alpha_composite(part, (x0 + dx, y0 + dy))
        if heal:
            self._heal(before, (x0, y0, x1, y1), abs(dx) + abs(dy) + 1)
        return self

    def _heal(self, before, rect, reach):
        """Close the seam a moved selection leaves behind (like stretching the
        neck): a vacated pixel is filled from the nearest body pixel when the
        body now encloses it horizontally or vertically."""
        px, bp = self.im.load(), before.load()
        w, h = self.im.size
        x0, y0, x1, y1 = rect
        todo = []
        for y in range(max(0, y0 - 1), min(h, y1 + 1)):
            for x in range(max(0, x0 - 1), min(w, x1 + 1)):
                if px[x, y][3] or not bp[x, y][3]:
                    continue

                def hit(dx_, dy_):
                    for k in range(1, reach + 1):
                        xx, yy = x + dx_ * k, y + dy_ * k
                        if not (0 <= xx < w and 0 <= yy < h):
                            return None
                        if px[xx, yy][3]:
                            return k, px[xx, yy]
                    return None
                l, r_, u, d = hit(-1, 0), hit(1, 0), hit(0, -1), hit(0, 1)
                if (l and r_) or (u and d):
                    cands = [c for c in (l, r_, u, d) if c]
                    todo.append((x, y, min(cands, key=lambda c: c[0])[1]))
        for x, y, c in todo:
            px[x, y] = c

    def offset(self, dx, dy):
        """Move the whole sprite (body lean / lunge)."""
        return self.move((0, 0, self.w, self.im.height), dx, dy, heal=False)

    def shear(self, y0, y1, dx_top, dx_bottom=0):
        """Shift each row in [y0,y1) horizontally, linearly from dx_top to dx_bottom (lean)."""
        src = self.im.copy()
        for y in range(y0, y1):
            t = (y - y0) / max(1, y1 - 1 - y0)
            dx = round(dx_top + (dx_bottom - dx_top) * t)
            row = src.crop((0, y, self.w, y + 1))
            self.im.paste((0, 0, 0, 0), (0, y, self.w, y + 1))
            self.im.alpha_composite(row, (dx, y))
        return self

    def scale(self, sx, sy, anchor="bottom"):
        """Squash/stretch around the feet (nearest neighbour keeps the pixel grid)."""
        bb = self.im.getbbox()
        if not bb:
            return self
        part = self.im.crop(bb)
        nw, nh = max(1, round(part.width * sx)), max(1, round(part.height * sy))
        part = part.resize((nw, nh), Image.NEAREST)
        cx = (bb[0] + bb[2]) / 2
        nx = round(cx - nw / 2)
        ny = bb[3] - nh if anchor == "bottom" else round((bb[1] + bb[3]) / 2 - nh / 2)
        self.im = Image.new("RGBA", self.im.size)
        self.im.alpha_composite(part, (nx, ny))
        return self

    def cleanup(self):
        """Tidy what selection moves leave behind: drop 1px stubs sticking out of
        the silhouette, and recolour old outline pixels now buried inside the body."""
        px = self.im.load()
        w, h = self.im.size
        lum = lambda c: 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]

        def dark_run(x0, y0, cap=6):
            """Size (capped) of the 8-connected dark patch at x0,y0. Buried outline
            is a long line; a 1-4px spot (cheetah, hyena, leopard) is a coat
            marking, not outline, and must survive the cleanup."""
            seen, stack = {(x0, y0)}, [(x0, y0)]
            while stack and len(seen) < cap:
                x, y = stack.pop()
                for i in (-1, 0, 1):
                    for j in (-1, 0, 1):
                        q = (x + i, y + j)
                        if q not in seen and 0 <= q[0] < w and 0 <= q[1] < h:
                            c2 = px[q]
                            if c2[3] and lum(c2) < 45:
                                seen.add(q)
                                stack.append(q)
            return len(seen)

        for _ in range(2):
            drop, recolor = [], []
            for y in range(1, h - 1):
                for x in range(1, w - 1):
                    c = px[x, y]
                    if not c[3]:
                        continue
                    n4 = [px[x - 1, y], px[x + 1, y], px[x, y - 1], px[x, y + 1]]
                    op = [n for n in n4 if n[3]]
                    if len(op) <= 1:
                        drop.append((x, y))
                    elif lum(c) < 45 and len(op) == 4:
                        light = [n for n in n4 if lum(n) >= 45]
                        n8 = [px[x + i, y + j] for i in (-1, 0, 1) for j in (-1, 0, 1) if (i or j)]
                        if len(light) >= 3 and all(n[3] for n in n8) and dark_run(x, y) >= 6:
                            recolor.append((x, y, max(set(light), key=light.count)))
            for x, y in drop:
                px[x, y] = (0, 0, 0, 0)
            for x, y, c in recolor:
                px[x, y] = c
        return self

    def warp(self, dx, dy, region, lo=0.3, hi=1.0):
        """Puppet-warp style move with no seams: pixels in `region` of the
        silhouette (front along x for side views, the top for front/back views)
        shift by up to (dx, dy), easing to zero towards the rest of the body,
        so the neck/body stretches instead of tearing. Nearest sampling keeps
        the pixel grid."""
        import numpy as np
        a = np.array(self.im)
        bb = self.im.getbbox()
        if not bb or (dx == 0 and dy == 0):
            return self
        h, w = a.shape[:2]
        ys, xs = np.mgrid[0:h, 0:w]
        x0, y0, x1, y1 = bb
        if region == "x+":
            u = (xs - x0) / max(1, x1 - x0)
        elif region == "x-":
            u = (x1 - xs) / max(1, x1 - x0)
        else:  # "top"
            u = (y1 - ys) / max(1, y1 - y0)
        t = np.clip((u - lo) / (hi - lo), 0, 1)
        t = t * t * (3 - 2 * t)
        sx = np.rint(xs - dx * t).astype(int)
        sy = np.rint(ys - dy * t).astype(int)
        ok = (sx >= 0) & (sx < w) & (sy >= 0) & (sy < h)
        out = np.zeros_like(a)
        out[ok] = a[sy[ok], sx[ok]]
        self.im = Image.fromarray(out, "RGBA").copy()
        return self

    def fill_holes(self):
        """After moves: fill 1px gaps that have opaque neighbours on 3+ sides."""
        px = self.im.load()
        w, h = self.im.size
        fills = []
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if px[x, y][3]:
                    continue
                n = [px[x - 1, y], px[x + 1, y], px[x, y - 1], px[x, y + 1]]
                op = [c for c in n if c[3]]
                if len(op) >= 3:
                    fills.append((x, y, op[0]))
        for x, y, c in fills:
            px[x, y] = c
        return self

    def smear(self, pts, colors, width=1):
        """Opaque smear arc through pts with the given colours (outer -> inner)."""
        d = ImageDraw.Draw(self.im)
        for i, col in enumerate(colors):
            off = i * width
            d.line([(x, y + off) for x, y in pts], fill=col, width=width)
        return self

    def paint(self, x, y, grid, palette):
        """Paste a text grid at (x, y). '.' leaves a pixel, '_' erases, others index palette."""
        px = self.im.load()
        for j, row in enumerate(grid.strip("\n").split("\n")):
            for i, ch in enumerate(row):
                if ch == ".":
                    continue
                if ch == "_":
                    px[x + i, y + j] = (0, 0, 0, 0)
                else:
                    px[x + i, y + j] = palette[ch]
        return self

    def flash(self, color=(255, 255, 255, 255)):
        """Contrast frame: the silhouette in one colour (heavy hits)."""
        a = self.im.split()[3]
        self.im = Image.new("RGBA", self.im.size, color)
        self.im.putalpha(a)
        return self


def to_grid(im):
    im = im.convert("RGBA")
    pal = {}
    rows = []
    for y in range(im.height):
        row = ""
        for x in range(im.width):
            c = im.getpixel((x, y))
            if c[3] < 128:
                row += "."
                continue
            c = c[:3]
            if c not in pal:
                pal[c] = CHARS[len(pal) % len(CHARS)]
            row += pal[c]
        rows.append(row)
    return rows, {v: "#%02x%02x%02x" % k for k, v in pal.items()}


def dump(png, out=None, scale=12):
    im = Image.open(png).convert("RGBA")
    rows, pal = to_grid(im)
    print("palette:", " ".join(f"{k}={v}" for k, v in pal.items()))
    print("    " + "".join(str(x % 10) for x in range(im.width)))
    for y, r in enumerate(rows):
        print(f"{y:3d} {r}")
    if out:
        W, H = im.width * scale, im.height * scale
        v = Image.new("RGBA", (W + 30, H + 30), (200, 205, 215, 255))
        v.alpha_composite(im.resize((W, H), Image.NEAREST), (30, 30))
        d = ImageDraw.Draw(v)
        for i in range(0, max(im.width, im.height) + 1):
            col = (120, 120, 140, 255) if i % 4 else (60, 60, 200, 255)
            if i <= im.width:
                d.line([(30 + i * scale, 30), (30 + i * scale, 30 + H)], fill=col if i % 4 == 0 else (175, 180, 195, 255))
                if i % 4 == 0:
                    d.text((30 + i * scale + 2, 2), str(i), fill=(0, 0, 0, 255))
            if i <= im.height:
                d.line([(30, 30 + i * scale), (30 + W, 30 + i * scale)], fill=col if i % 4 == 0 else (175, 180, 195, 255))
                if i % 4 == 0:
                    d.text((2, 30 + i * scale + 2), str(i), fill=(0, 0, 0, 255))
        v.save(out)


def base_frame(uid, d, factor=2):
    rot = Image.open(ROOT / "units" / uid / "raw" / "Idle" / "rotations" / f"{d}.png").convert("RGBA")
    size = int(math.ceil(rot.width * factor / 4) * 4)
    c = Image.new("RGBA", (size, size))
    c.paste(rot, ((size - rot.width) // 2, (size - rot.height) // 2))
    return Frame(c)


# ---------------------------------------------------------------- recipes
def _r(rect, pad):
    return tuple(v + pad for v in rect)


def lunge_attack(fx, fy, head, front=None, pad=16, mag=1.0, heavy=False,
                 smear_colors=((246, 245, 236, 255),), smear_from=None, smear_to=None):
    """Attack keyed by hand following aseprite-ai-artist rules/44:
    stance -> wind-up (opposite way, held) -> smear (50 ms) -> hit (held) ->
    follow-through -> recover (longer than the strike) -> 1px overshoot -> stance.

    fx, fy: facing unit vector; head/front: rects in base-pose coordinates
    (before padding) that are moved like an Aseprite selection.
    """
    head = _r(head, pad)
    front = _r(front, pad) if front else None
    m = mag

    def r(v):
        return int(round(v))

    def pose(head_d=(0, 0), front_d=(0, 0), sx=1.0, sy=1.0, lean=0, off=(0, 0), smear=None):
        def op(f):
            if head_d != (0, 0):
                f.move(head, r(head_d[0]), r(head_d[1]))
            if front and front_d != (0, 0):
                f.move(front, r(front_d[0]), r(front_d[1]))
            f.fill_holes()
            f.cleanup()
            if lean:
                bb = f.im.getbbox()
                if bb:
                    f.shear(bb[1], bb[1] + (bb[3] - bb[1]) * 2 // 3, r(lean), 0)
            if (sx, sy) != (1.0, 1.0):
                f.scale(sx, sy)
            if off != (0, 0):
                f.offset(r(off[0]), r(off[1]))
            if smear:
                f.smear(*smear)
        return [op]

    hold = 280 if heavy else 200
    hit_ms = 170 if heavy else 140
    sm = None
    if smear_from and smear_to:
        (ax, ay), (bx, by) = smear_from, smear_to
        mid = ((ax + bx) / 2 + fy * 3, (ay + by) / 2 - fx * 3)
        sm = ([(ax + pad + 3 * fx * m, ay + pad + 3 * fy * m), (mid[0] + pad + 3 * fx * m, mid[1] + pad + 3 * fy * m),
               (bx + pad + 3 * fx * m, by + pad + 3 * fy * m)], list(smear_colors))
    frames = [
        (100, []),                                                                        # stance
        (110, pose((-fx * 1 * m, -1 * m), (0, 0), 1.03, 0.95, -fx * 1 * m, (-fx * 1 * m, -fy * 1 * m))),
        (hold, pose((-fx * 2 * m, -2 * m), (0, 0), 1.05, 0.9, -fx * 2 * m, (-fx * 2 * m, -fy * 2 * m))),  # wind-up held
        (50, pose((fx * 3 * m, fy * 2 * m + 1), (fx * 2 * m, fy * m), 1.14, 0.98, 0, (fx * 3 * m, fy * 3 * m), sm)),  # smear
        (hit_ms, pose((fx * 4 * m, fy * 2 * m + 2), (fx * 3 * m, fy * 2 * m), 1.1, 1.0, fx * 1 * m, (fx * 4 * m, fy * 4 * m))),  # hit
        (80, pose((fx * 3 * m, fy * m + 1), (fx * 2 * m, fy * m), 1.04, 1.0, 0, (fx * 3 * m, fy * 3 * m))),  # follow
        (110 if heavy else 90, pose((fx * 1 * m, 0), (0, 0), 1.0, 1.0, 0, (fx * 1 * m, fy * 1 * m))),    # recover
        (50, pose((0, 0), (0, 0), 1.0, 1.0, 0, (-fx, -fy))),                              # overshoot
        (120, []),                                                                        # stance
    ]
    return frames, 4


def swarm_attack(fx, fy, pad=16, wing=(223, 239, 255, 255)):
    """Swarm sting. The bees overlap too much to select one by one, so the swarm
    moves as one: pull back and bunch (squash), dart (stretch along the attack
    with streaks), hold the sting, drift back with a 1px overshoot."""

    def pose(off, sx=1.0, sy=1.0, streak=False):
        def op(f):
            if (sx, sy) != (1.0, 1.0):
                f.scale(sx, sy, anchor="center")
            f.offset(int(round(off[0])), int(round(off[1])))
            if streak:
                bb = f.im.getbbox()
                if bb:
                    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
                    for k in (-5, 0, 5):
                        x0 = cx - fx * 13 - fy * k
                        y0 = cy - fy * 13 + fx * k
                        f.smear([(x0, y0), (x0 + fx * 6, y0 + fy * 6)], [wing])
        return [op]

    stretch = (1.2 if abs(fx) > abs(fy) else 1.1, 0.9 if abs(fx) > abs(fy) else 1.1)
    frames = [
        (100, []),
        (100, pose((-fx, -fy), 0.95, 0.95)),
        (200, pose((-fx * 2, -fy * 2), 0.88, 0.88)),                  # bunch up, held
        (50, pose((fx * 4, fy * 4), *stretch, streak=True)),         # dart (smear)
        (130, pose((fx * 6, fy * 6), 1.05, 1.05)),                    # sting (hit)
        (80, pose((fx * 4, fy * 4))),
        (90, pose((fx * 1, fy * 1))),
        (50, pose((-fx, -fy))),
        (120, []),
    ]
    return frames, 4

# ---------------------------------------------------------------- v2: automatic recipes
import numpy as np
import yaml

DRAWN = ["south", "south-east", "east", "north-east", "north"]
FACE = {"south": (0, 1), "south-east": (0.7071, 0.7071), "east": (1, 0), "north-east": (0.7071, -0.7071), "north": (0, -1)}


def scale2x(a):
    """EPX/Scale2x on an RGBA array: doubles size while keeping edges crisp."""
    h, w, _ = a.shape
    p = np.pad(a, ((1, 1), (1, 1), (0, 0)), mode="edge")
    A, B, C, D, E = p[:-2, 1:-1], p[1:-1, :-2], p[1:-1, 2:], p[2:, 1:-1], p[1:-1, 1:-1]
    eq = lambda x, y: np.all(x == y, axis=2)
    out = np.zeros((h * 2, w * 2, 4), a.dtype)
    c_bd, c_ac = ~eq(B, C) & ~eq(A, D), None
    e0 = np.where((eq(A, B) & c_bd)[..., None], A, E)
    e1 = np.where((eq(A, C) & c_bd)[..., None], C, E)
    e2 = np.where((eq(D, B) & c_bd)[..., None], B, E)
    e3 = np.where((eq(D, C) & c_bd)[..., None], D, E)
    out[0::2, 0::2], out[0::2, 1::2], out[1::2, 0::2], out[1::2, 1::2] = e0, e1, e2, e3
    return out


def rotsprite(im, angle, pivot):
    """Rotate pixel art without mush (RotSprite-lite): Scale2x x3, rotate with
    nearest sampling, sample back down at block centres."""
    if abs(angle) < 0.5:
        return im
    a = np.array(im.convert("RGBA"))
    for _ in range(3):
        a = scale2x(a)
    big = Image.fromarray(a, "RGBA").rotate(angle, resample=Image.NEAREST, center=(pivot[0] * 8, pivot[1] * 8))
    small = np.array(big)[4::8, 4::8]
    return Image.fromarray(np.ascontiguousarray(small), "RGBA").copy()


def regions(frame, d):
    """Automatic selections for a direction: the head (front/upper part of the
    silhouette, moved like an Aseprite selection) and the front legs."""
    bb = frame.im.getbbox()
    x0, y0, x1, y1 = bb
    W, H = x1 - x0, y1 - y0
    fx, fy = FACE[d]
    if abs(fx) > 0.1:   # side / diagonal views: the head leads along x
        xc = int(x0 + W * 0.5)
        head = (xc, y0, x1, int(y0 + H * 0.7))
        front = (int(xc - W * 0.08), int(y0 + H * 0.7), x1, y1)
    elif fy > 0:        # facing the viewer: head is the upper middle, over the body
        head = (int(x0 + W * 0.12), y0, int(x1 - W * 0.12), int(y0 + H * 0.58))
        front = (x0, int(y0 + H * 0.72), x1, y1)
    else:               # facing away: head is the top of the silhouette
        head = (int(x0 + W * 0.15), y0, int(x1 - W * 0.15), int(y0 + H * 0.45))
        front = None
    return head, front


def bright_colors(frame, rect, n=2):
    a = np.array(frame.im.crop(rect))
    px = a[a[..., 3] > 127][:, :3]
    if not len(px):
        return [(246, 245, 236, 255)]
    lum = px @ np.array([0.3, 0.59, 0.11])
    order = np.argsort(-lum)
    out = []
    for i in order:
        c = tuple(int(v) for v in px[i]) + (255,)
        if c not in out:
            out.append(c)
        if len(out) == n:
            break
    return out


def auto_lunge(frame, d, mag, heavy, warp=False):
    """Lunge attack for any direction (aseprite-ai-artist rules/44 phases).
    Side views lunge along x; the front view rears back then fills toward the
    camera (grows + drops), the back view dips then stretches away (up)."""
    fx, fy = FACE[d]
    head, front = regions(frame, d)
    m = mag
    hold = 280 if heavy else 200
    hit_ms = 170 if heavy else 140
    cols = bright_colors(frame, head)
    hx0, hy0, hx1, hy1 = head

    region = "x+" if fx > 0.1 else "top"

    def pose(head_d=(0, 0), front_d=(0, 0), sx=1.0, sy=1.0, lean=0, off=(0, 0), smear=False, center=False):
        def op(f):
            if warp:   # HD: seamless warp of the front/top of the body instead of cut-and-move
                if head_d != (0, 0):
                    f.warp(head_d[0] * 1.3, head_d[1] * 1.3, region)
            else:
                if head_d != (0, 0):
                    f.move(head, round(head_d[0]), round(head_d[1]))
                if front and front_d != (0, 0):
                    f.move(front, round(front_d[0]), round(front_d[1]))
            f.fill_holes()
            f.cleanup()
            if lean:
                bb = f.im.getbbox()
                if bb:
                    f.shear(bb[1], bb[1] + (bb[3] - bb[1]) * 2 // 3, round(lean), 0)
            if (sx, sy) != (1.0, 1.0):
                f.scale(sx, sy, anchor="center" if center else "bottom")
            if off != (0, 0):
                f.offset(round(off[0]), round(off[1]))
            if smear:
                if abs(fx) > 0.1:   # vertical arc just ahead of the head
                    xa = hx1 + 2 * m + off[0]
                    pts = [(xa, hy0 + (hy1 - hy0) * 0.25 + off[1]), (xa + 2 * m, (hy0 + hy1) / 2 + off[1]),
                           (xa, hy1 + off[1] + fy * 2 * m)]
                else:               # horizontal arc in front of / behind the head
                    ya = (hy1 + 2 * m if fy > 0 else hy0 - 2 * m) + off[1]
                    pts = [(hx0 + (hx1 - hx0) * 0.2, ya), ((hx0 + hx1) / 2, ya + fy * 2 * m), (hx1 - (hx1 - hx0) * 0.2, ya)]
                f.smear(pts, cols, width=1)
        return [op]

    if abs(fx) > 0.1:
        st = 0.14 * abs(fx)
        frames = [
            (100, []),
            (110, pose((-fx * m, -m), (0, 0), 1.03, 0.95, -fx * m, (-fx * m, -fy * m))),
            (hold, pose((-fx * 2 * m, -2 * m), (0, 0), 1.05, 0.9, -fx * 2 * m, (-fx * 2 * m, -fy * 2 * m))),
            (50, pose((fx * 3 * m, fy * 2 * m + 1), (fx * 2 * m, fy * m), 1 + st, 0.98 + 0.06 * abs(fy), 0, (fx * 3 * m, fy * 3 * m), True)),
            (hit_ms, pose((fx * 4 * m, fy * 2 * m + 2), (fx * 3 * m, fy * 2 * m), 1 + st * 0.7, 1.0, fx * m, (fx * 4 * m, fy * 4 * m))),
            (80, pose((fx * 3 * m, fy * m + 1), (fx * 2 * m, fy * m), 1.04, 1.0, 0, (fx * 3 * m, fy * 3 * m))),
            (110 if heavy else 90, pose((fx * m, 0), (0, 0), 1.0, 1.0, 0, (fx * m, fy * m))),
            (50, pose((0, 0), (0, 0), 1.0, 1.0, 0, (-fx, -fy))),
            (120, []),
        ]
    elif fy > 0:   # facing the viewer
        frames = [
            (100, []),
            (110, pose((0, -m), (0, 0), 0.98, 0.95, 0, (0, -m))),
            (hold, pose((0, -2 * m), (0, 0), 0.96, 0.9, 0, (0, -2 * m))),
            (50, pose((0, 3 * m), (0, m), 1.1, 1.08, 0, (0, 2 * m), False, True)),   # no smear: it would cross the face
            (hit_ms, pose((0, 3 * m), (0, 2 * m), 1.08, 1.06, 0, (0, 3 * m), False, True)),
            (80, pose((0, 2 * m), (0, m), 1.04, 1.03, 0, (0, 2 * m), False, True)),
            (110 if heavy else 90, pose((0, m), (0, 0), 1.0, 1.0, 0, (0, m))),
            (50, pose((0, 0), (0, 0), 1.0, 1.0, 0, (0, -1))),
            (120, []),
        ]
    else:          # facing away
        frames = [
            (100, []),
            (110, pose((0, m), (0, 0), 1.02, 0.95, 0, (0, m))),
            (hold, pose((0, 2 * m), (0, 0), 1.04, 0.9, 0, (0, 2 * m))),
            (50, pose((0, -3 * m), (0, 0), 0.96, 1.1, 0, (0, -2 * m), True)),
            (hit_ms, pose((0, -3 * m), (0, 0), 0.97, 1.06, 0, (0, -3 * m))),
            (80, pose((0, -2 * m), (0, 0), 0.99, 1.03, 0, (0, -2 * m))),
            (110 if heavy else 90, pose((0, -m), (0, 0), 1.0, 1.0, 0, (0, -m))),
            (50, pose((0, 0), (0, 0), 1.0, 1.0, 0, (0, 1))),
            (120, []),
        ]
    return frames, 4


def auto_death(frame, d, mag, kind):
    """Collapse: recoil, legs buckle (squash), tip over (clean rotation), bounce,
    rest. The game fades the body out after the last frame."""
    fx, fy = FACE[d]
    m = mag
    tilt = 1 if fx > 0.1 else -1   # tip backwards on side views, to the right otherwise

    def pose(sx, sy, ang, off=(0, 0)):
        def op(f):
            if (sx, sy) != (1.0, 1.0):
                f.scale(sx, sy)
            bb = f.im.getbbox()
            if bb and ang:
                f.im = rotsprite(f.im, ang * tilt, ((bb[0] + bb[2]) / 2, bb[3] - 1))
            if off != (0, 0):
                f.offset(round(off[0]), round(off[1]))
            f.cleanup()
        return [op]

    if kind == "swarm":   # bees drop out of the air and lie still
        return [
            (90, pose(1.0, 1.0, 0, (-fx * 2, -fy * 2 - 1))),
            (100, pose(0.95, 0.95, 10, (0, 2))),
            (90, pose(0.9, 0.85, 25, (0, 5))),
            (80, pose(0.85, 0.7, 40, (0, 8))),
            (70, pose(0.85, 0.62, 45, (0, 9))),
            (500, pose(0.85, 0.6, 45, (0, 9))),
        ]
    back = (-fx * 2 * m, -fy * m)
    return [
        (90, pose(1.0, 1.0, 0, back)),                    # recoil from the killing blow
        (110, pose(1.0, 0.95, 6, back)),                  # stagger
        (100, pose(1.04, 0.85, 12, back)),                # legs buckle
        (80, pose(1.1, 0.72, 18, back)),                  # collapse
        (70, pose(1.16, 0.6, 22, (back[0], back[1] + 1))),  # hit the ground
        (70, pose(1.12, 0.65, 20, back)),                 # one bounce
        (500, pose(1.15, 0.62, 22, (back[0], back[1] + 1))),  # rest; the game fades it out
    ]


def unit_cfg(uid):
    return yaml.safe_load((ROOT / "prompts" / "units" / f"{uid}.yaml").read_text())


def mag_for(cfg):
    c = cfg.get("canvas", 32)
    base = {32: 1.0, 48: 1.3, 64: 1.6, 128: 2.6}.get(c, c / 40)
    return base * (1.2 if cfg.get("size_class") in ("small", "micro") else 1.0)


def write_seq(out, base, frames, hit, method):
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    seq = []
    for i, (ms, ops) in enumerate(frames):
        f = base.copy()
        for op in ops:
            op(f)
        f.im.save(out / f"frame_{i:02d}.png")
        seq.append({"file": f"frame_{i:02d}.png", "ms": ms})
    (out / "sequence.json").write_text(json.dumps({"frames": seq, "hit": hit, "method": method}, indent=1) + "\n")


def build(uid, dirs=None):
    cfg = unit_cfg(uid)
    he = cfg.get("handedit") or {}
    kind, heavy = he.get("kind", "lunge"), bool(he.get("heavy", False))
    mag = he.get("mag", mag_for(cfg))
    over = {}
    rp = ROOT / "prompts" / "handedit" / f"{uid}.py"
    if rp.exists():   # hand-tuned selections for some directions
        spec = importlib.util.spec_from_file_location("recipe", rp)
        rec = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rec)
        over = {d: (rec.DIRS[d], rec.HIT[d]) for d in rec.DIRS}
    done = []
    for d in dirs or DRAWN:
        base = base_frame(uid, d)
        root = ROOT / "units" / uid / "variants"
        if d in over:
            frames, hit = over[d]
        elif kind == "swarm":
            frames, hit = swarm_attack(*FACE[d], pad=(base.w - base.w // 2) // 2)
        else:
            frames, hit = auto_lunge(base, d, mag, heavy, warp=he.get("style", "warp" if cfg.get("canvas", 32) >= 64 else "cut") == "warp")
        write_seq(root / "attackhand" / d, base, frames, hit, "AI hand-edited attack (text-grid method)")
        write_seq(root / "death" / d, base, auto_death(base, d, mag, kind), 0, "AI hand-edited death")
        done.append(d)
    src = ROOT / "units" / uid / "source.json"
    rec_ = json.loads(src.read_text())
    v = rec_.setdefault("variants", {})
    v["attackhand"] = {
        "method": "AI hand-edited: select-and-move / squash-stretch / smear edits on the PixelLab base pose, "
                  "text-grid method from aseprite-ai-artist (MIT), timing from its rules/44",
        "kind": kind, "heavy": heavy, "mag": mag, "directions": done,
        "hand_tuned": sorted(over), "generations": 0}
    v["death"] = {"method": "AI hand-edited collapse (squash + RotSprite-style tilt)", "directions": done, "generations": 0}
    src.write_text(json.dumps(rec_, indent=2, ensure_ascii=False) + "\n")
    print(uid, "attack+death:", ", ".join(done))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "dump":
        dump(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif cmd == "build":
        for u in sys.argv[2:]:
            build(u)
