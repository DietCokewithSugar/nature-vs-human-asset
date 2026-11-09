import type { Atlas } from "./data";

/** Per-pixel normal-map lighting on a 2D canvas (small frames, so plain JS is fast enough).
 *  Normal maps are OpenGL style: R = +x right, G = +y up, B = +z toward the viewer. */
export interface Light2D { x: number; y: number; z: number; color: [number, number, number]; ambient: [number, number, number]; bands: number }

export type ViewMode = "color" | "lit" | "normal";

export class LitFrames {
  private cache = new Map<string, { w: number; h: number; c: Uint8ClampedArray; n: Uint8ClampedArray }>();
  private out = document.createElement("canvas");
  constructor(private img: HTMLImageElement, private nimg: HTMLImageElement, private atlas: Atlas) {}

  private data(name: string) {
    let d = this.cache.get(name);
    if (d) return d;
    const f = this.atlas.frames[name].frame;
    const cv = document.createElement("canvas");
    cv.width = f.w; cv.height = f.h;
    const x = cv.getContext("2d", { willReadFrequently: true })!;
    x.drawImage(this.img, f.x, f.y, f.w, f.h, 0, 0, f.w, f.h);
    const c = x.getImageData(0, 0, f.w, f.h).data;
    x.clearRect(0, 0, f.w, f.h);
    x.drawImage(this.nimg, f.x, f.y, f.w, f.h, 0, 0, f.w, f.h);
    const n = x.getImageData(0, 0, f.w, f.h).data;
    d = { w: f.w, h: f.h, c, n };
    this.cache.set(name, d);
    return d;
  }

  /** Draw `name` centred at (cx, cy). Light position is in frame pixels from the frame centre. */
  draw(ctx: CanvasRenderingContext2D, name: string, cx: number, cy: number, scale: number, mode: ViewMode, L: Light2D) {
    const d = this.data(name);
    this.out.width = d.w; this.out.height = d.h;
    const o = this.out.getContext("2d")!;
    const img = o.createImageData(d.w, d.h);
    const p = img.data;
    const lx = L.x + d.w / 2, ly = L.y + d.h / 2;
    for (let i = 0, y = 0; y < d.h; y++) {
      for (let x = 0; x < d.w; x++, i += 4) {
        const a = d.c[i + 3];
        if (!a) continue;
        if (mode === "normal") {
          p[i] = d.n[i]; p[i + 1] = d.n[i + 1]; p[i + 2] = d.n[i + 2]; p[i + 3] = a;
          continue;
        }
        if (mode === "color") {
          p[i] = d.c[i]; p[i + 1] = d.c[i + 1]; p[i + 2] = d.c[i + 2]; p[i + 3] = a;
          continue;
        }
        const nx = d.n[i] / 127.5 - 1, ny = d.n[i + 1] / 127.5 - 1, nz = d.n[i + 2] / 127.5 - 1;
        let vx = lx - x, vy = -(ly - y), vz = L.z;
        const len = Math.hypot(vx, vy, vz) || 1;
        vx /= len; vy /= len; vz /= len;
        let diff = Math.max(0, nx * vx + ny * vy + nz * vz);
        if (L.bands > 0) diff = Math.round(diff * L.bands) / L.bands;
        p[i] = Math.min(255, d.c[i] * (L.ambient[0] + diff * L.color[0]));
        p[i + 1] = Math.min(255, d.c[i + 1] * (L.ambient[1] + diff * L.color[1]));
        p[i + 2] = Math.min(255, d.c[i + 2] * (L.ambient[2] + diff * L.color[2]));
        p[i + 3] = a;
      }
    }
    o.putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(this.out, Math.round(cx - (d.w * scale) / 2), Math.round(cy - (d.h * scale) / 2), d.w * scale, d.h * scale);
  }
}

export function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((res, rej) => {
    const i = new Image();
    i.onload = () => res(i);
    i.onerror = rej;
    i.src = src;
  });
}
