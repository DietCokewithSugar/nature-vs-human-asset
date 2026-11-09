import { Container, Graphics, Texture, TilingSprite } from "pixi.js";
import type { Weather } from "./lighting";

/** Screen-space weather: pixel snowflakes (wind for a blizzard) and drifting
 *  pixel fog. Drawn above the lit scene and tinted by the ambient light. */
export class WeatherLayer {
  view = new Container();
  private flakes: { x: number; y: number; vy: number; vx: number; s: number }[] = [];
  private g = new Graphics();
  private fog: TilingSprite;
  private veil = new Graphics();
  private kind: Weather = "clear";
  private w = 0;
  private h = 0;

  constructor() {
    this.fog = new TilingSprite({ texture: fogTexture(), width: 10, height: 10 });
    this.fog.tileScale.set(4);
    this.fog.alpha = 0;
    this.view.addChild(this.veil, this.fog, this.g);
  }

  resize(w: number, h: number) {
    this.w = w;
    this.h = h;
    this.fog.width = w;
    this.fog.height = h;
    this.veil.clear().rect(0, 0, w, h).fill(0xffffff);
    this.setKind(this.kind, true);
  }

  setKind(kind: Weather, force = false) {
    if (kind === this.kind && !force) return;
    this.kind = kind;
    const n = kind === "snow" ? 220 : kind === "blizzard" ? 750 : 0;
    this.flakes = Array.from({ length: n }, () => this.flake(true));
    this.fog.alpha = kind === "fog" ? 0.55 : kind === "blizzard" ? 0.32 : 0;
    this.veil.alpha = kind === "blizzard" ? 0.14 : kind === "fog" ? 0.1 : 0;
  }

  private flake(anywhere: boolean) {
    const bl = this.kind === "blizzard";
    return {
      x: Math.random() * (this.w + 200) - 100,
      y: anywhere ? Math.random() * this.h : -4,
      vy: (bl ? 90 : 26) + Math.random() * (bl ? 80 : 30),
      vx: bl ? 160 + Math.random() * 120 : (Math.random() - 0.5) * 14,
      s: Math.random() < 0.25 ? 3 : 2,
    };
  }

  update(dt: number, tint: number, zoom: number) {
    this.fog.tilePosition.x -= dt * (this.kind === "blizzard" ? 60 : 8);
    this.fog.tilePosition.y += dt * (this.kind === "blizzard" ? 12 : 2);
    this.fog.tint = tint;
    this.veil.tint = tint;
    const g = this.g;
    g.clear();
    if (!this.flakes.length) return;
    const sz = Math.max(1, Math.round(zoom * 0.8));
    for (const f of this.flakes) {
      f.x += f.vx * dt + Math.sin((f.y + f.x) * 0.02) * 6 * dt;
      f.y += f.vy * dt;
      if (f.y > this.h + 4 || f.x > this.w + 120) Object.assign(f, this.flake(false));
      g.rect(Math.round(f.x), Math.round(f.y), f.s * sz * 0.5 + 1, f.s * sz * 0.5 + 1);
    }
    g.fill({ color: 0xffffff, alpha: 0.9 });
    g.tint = tint;
  }
}

/** Low-res, tileable fog blobs; upscaled with nearest filtering for a pixel look. */
function fogTexture(): Texture {
  const N = 96;
  const c = document.createElement("canvas");
  c.width = c.height = N;
  const x = c.getContext("2d")!;
  const img = x.createImageData(N, N);
  const blobs = Array.from({ length: 14 }, () => [Math.random() * N, Math.random() * N, 10 + Math.random() * 22]);
  for (let y = 0; y < N; y++)
    for (let i = 0; i < N; i++) {
      let v = 0;
      for (const [bx, by, r] of blobs)
        for (const ox of [-N, 0, N]) for (const oy of [-N, 0, N]) {
          const d = Math.hypot(i - bx - ox, y - by - oy) / r;
          if (d < 1) v += (1 - d) * (1 - d);
        }
      // ordered dither into 3 alpha steps
      const bayer = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]][y % 4][i % 4] / 16;
      const a = Math.min(1, v * 0.9);
      const q = Math.floor(a * 3 + bayer) / 3;
      const p = (y * N + i) * 4;
      img.data[p] = img.data[p + 1] = img.data[p + 2] = 240;
      img.data[p + 3] = Math.round(q * 150);
    }
  x.putImageData(img, 0, 0);
  const t = Texture.from(c);
  t.source.scaleMode = "nearest";
  return t;
}
