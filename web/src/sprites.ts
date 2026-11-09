import type { Atlas } from "./data";

export function drawFrame(
  ctx: CanvasRenderingContext2D, img: HTMLImageElement, atlas: Atlas, name: string,
  dx: number, dy: number, scale: number,
) {
  const f = atlas.frames[name]?.frame;
  if (!f) return;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(img, f.x, f.y, f.w, f.h, Math.round(dx), Math.round(dy), f.w * scale, f.h * scale);
}

/** Code-drawn shadow + faction ring, as in the game. (cx, cy) = feet, in canvas px. */
export function drawGroundMarks(
  ctx: CanvasRenderingContext2D, cx: number, cy: number, bodyW: number, scale: number,
  faction: "nature" | "human" | null,
) {
  const rx = Math.max(5, bodyW * 0.42) * scale;
  const ry = Math.max(2, bodyW * 0.16) * scale;
  ctx.save();
  ctx.fillStyle = "rgba(25,25,45,0.32)";
  ctx.beginPath();
  ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
  ctx.fill();
  if (faction) {
    ctx.strokeStyle = faction === "nature" ? "#63c74d" : "#f77622";
    ctx.lineWidth = Math.max(1, scale * 0.75);
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx + scale, ry + scale * 0.6, 0, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}

export function drawZzz(ctx: CanvasRenderingContext2D, x: number, y: number, t: number, scale: number) {
  ctx.save();
  ctx.font = `${Math.round(5 * scale)}px Silkscreen, monospace`;
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "#1b1f2a";
  ctx.lineWidth = Math.max(2, scale * 0.8);
  const bob = Math.sin(t * 2) * 1.5 * scale;
  ctx.strokeText("z", x, y + bob);
  ctx.fillText("z", x, y + bob);
  ctx.font = `${Math.round(7 * scale)}px Silkscreen, monospace`;
  ctx.strokeText("Z", x + 4 * scale, y - 5 * scale + bob);
  ctx.fillText("Z", x + 4 * scale, y - 5 * scale + bob);
  ctx.restore();
}

/** Opaque width of a frame in source pixels (for shadow sizing); cached per frame. */
const widthCache = new Map<string, number>();
export function bodyWidth(img: HTMLImageElement, atlas: Atlas, name: string): number {
  const key = img.src + "|" + name;
  const hit = widthCache.get(key);
  if (hit !== undefined) return hit;
  const f = atlas.frames[name]?.frame;
  if (!f) return 16;
  const c = document.createElement("canvas");
  c.width = f.w; c.height = f.h;
  const x = c.getContext("2d")!;
  x.drawImage(img, f.x, f.y, f.w, f.h, 0, 0, f.w, f.h);
  const d = x.getImageData(0, 0, f.w, f.h).data;
  let lo = f.w, hi = -1;
  for (let yy = 0; yy < f.h; yy++) for (let xx = 0; xx < f.w; xx++) {
    if (d[(yy * f.w + xx) * 4 + 3] > 127) { if (xx < lo) lo = xx; if (xx > hi) hi = xx; }
  }
  const w = hi >= lo ? hi - lo + 1 : 16;
  widthCache.set(key, w);
  return w;
}
