// The fixed ice-age level (maps/ice_age_layout.json) drawn with the layered
// dual-grid terrain atlas (terrain/ice_age.png). Same algorithm as
// scripts/terrainlib.py, so a game client (Phaser or PixiJS) can copy it:
//   - logic: one terrain per 32px cell
//   - display tile (i, j) sits at (i*32-16, j*32-16) and reads the 4 cells
//     around its centre (NW, NE, SW, SE)
//   - draw the lowest-priority corner terrain as a full tile, then every
//     higher terrain with mask = corners whose priority >= its own
//   - flipping one cell only changes the 4 display tiles around it
import { Assets, Container, Graphics, Rectangle, Sprite, Text, Texture, type Renderer } from "pixi.js";
import type { Manifest, MapInfo } from "./data";

const TILE = 32;

export interface TerrainDef {
  index: number; id: string; name: string; owner: "human" | "nature" | "neutral" | "volcano";
  contestable: boolean; kind: "land" | "water"; priority: number; row: number; full: number[];
}
export interface LevelObject {
  class: string; name?: string; type?: string; kind?: string; site?: string;
  cell?: [number, number]; size?: [number, number]; sprite?: string; nest?: [number, number]; c?: [number, number];
}
export interface Level {
  info: MapInfo; w: number; h: number; grid: Int32Array; terrains: TerrainDef[]; columns: number;
  objects: LevelObject[]; camps: [number, number][];
  cellAt(px: number, py: number): TerrainDef | null;
}

export async function loadLevel(m: Manifest, id = "ice_age"): Promise<Level | null> {
  const info = m.maps?.find((x) => x.id === id);
  if (!info) return null;
  const [layout, meta] = await Promise.all([fetch(info.layout).then((r) => r.json()), fetch(info.terrain).then((r) => r.json())]);
  const w = layout.width as number, h = layout.height as number;
  const grid = new Int32Array(w * h);
  (layout.terrain as string[]).forEach((row, y) => { for (let x = 0; x < w; x++) grid[y * w + x] = row.charCodeAt(x) - 65; });
  const terrains = meta.terrains as TerrainDef[];
  const objects = layout.objects as LevelObject[];
  const camps = objects
    .filter((o) => o.class === "human_building" && o.type === "篝火营地" && o.cell && o.size)
    .map((o) => [(o.cell![0] + o.size![0] / 2) * TILE, (o.cell![1] + o.size![1] / 2) * TILE] as [number, number]);
  return {
    info, w, h, grid, terrains, columns: meta.columns, objects, camps,
    cellAt(px, py) {
      const x = Math.floor(px / TILE), y = Math.floor(py / TILE);
      if (x < 0 || y < 0 || x >= w || y >= h) return null;
      return terrains[grid[y * w + x]];
    },
  };
}

/** Bottom-up [terrain index, corner mask] pairs for one display tile. */
export function layersFor(corners: number[], prio: (t: number) => number): [number, number][] {
  const uniq = [...new Set(corners)].sort((a, b) => prio(a) - prio(b));
  return uniq.map((t, k) => {
    if (k === 0) return [t, 15];
    let m = 0;
    corners.forEach((c, i) => { if (prio(c) >= prio(t)) m |= 8 >> i; });
    return [t, m];
  });
}

function fullVariant(i: number, j: number) {
  const r = (((Math.imul(i, 73856093) ^ Math.imul(j, 19349663)) >>> 0) & 0xffff) / 65536;
  return r < 0.55 ? 15 : 16 + Math.min(2, Math.floor((r - 0.55) / 0.15));
}

/** Draws terrain into `ground` / `nground` (baked to one texture each) and map objects into `actors`. */
export async function drawLevel(
  renderer: Renderer, L: Level, ground: Container, nground: Container, actors: Container, overlay: Container,
) {
  const [tex, ntex, objReg] = await Promise.all([
    Assets.load<Texture>(L.info.terrainPng),
    L.info.terrainNormal ? Assets.load<Texture>(L.info.terrainNormal) : Promise.resolve(null),
    fetch(L.info.objects).then((r) => r.json()) as Promise<Record<string, { png: string; footprint: [number, number] }>>,
  ]);
  const frames = new Map<number, Texture>(), nframes = new Map<number, Texture>();
  const frame = (t: number, col: number, normal: boolean) => {
    const key = t * 64 + col;
    const map = normal ? nframes : frames;
    let f = map.get(key);
    if (!f) {
      const src = normal ? ntex! : tex;
      f = new Texture({ source: src.source, frame: new Rectangle(col * TILE, L.terrains[t].row * TILE, TILE, TILE) });
      map.set(key, f);
    }
    return f;
  };
  const prio = (t: number) => L.terrains[t].priority;
  const cell = (x: number, y: number) => L.grid[Math.min(L.h - 1, Math.max(0, y)) * L.w + Math.min(L.w - 1, Math.max(0, x))];
  const g = new Container(), ng = new Container();
  for (let j = 0; j <= L.h; j++)
    for (let i = 0; i <= L.w; i++) {
      const cs = [cell(i - 1, j - 1), cell(i, j - 1), cell(i - 1, j), cell(i, j)];
      for (const [t, m] of layersFor(cs, prio)) {
        const col = m === 15 ? fullVariant(i, j) : m;
        const s = new Sprite(frame(t, col, false));
        s.position.set(i * TILE - TILE / 2, j * TILE - TILE / 2);
        g.addChild(s);
        if (ntex) {
          const ns = new Sprite(frame(t, col, true));
          ns.position.copyFrom(s.position);
          ng.addChild(ns);
        }
      }
    }
  // bake: ~10k sprites -> one 3072x2048 texture per pass
  const bake = (c: Container) => {
    const rt = renderer.generateTexture({ target: c, frame: new Rectangle(0, 0, L.w * TILE, L.h * TILE) });
    c.destroy({ children: true });
    return new Sprite(rt);
  };
  ground.addChild(bake(g));
  if (ntex) nground.addChild(bake(ng));

  // objects: volcanoes, resource points, trees (depth-sorted with the units by their base line)
  const sprites: Record<string, Texture> = {};
  await Promise.all(Object.entries(objReg).map(async ([k, v]) => { sprites[k] = await Assets.load<Texture>(L.info.objectBase + v.png); }));
  for (const o of L.objects) {
    if (!o.sprite || !o.cell || !sprites[o.sprite]) continue;
    const [fw, fh] = objReg[o.sprite].footprint;
    const s = new Sprite(sprites[o.sprite]);
    s.anchor.set(0.5, 1);
    s.position.set((o.cell[0] + fw / 2) * TILE, (o.cell[1] + fh) * TILE);
    s.zIndex = s.y - 2;
    actors.addChild(s);
  }

  // unlit overlay: human start-building footprints (no art yet) + territory / chunk view
  const fp = new Graphics();
  for (const o of L.objects) {
    if (o.class !== "human_building" || !o.cell || !o.size) continue;
    fp.rect(o.cell[0] * TILE + 2, o.cell[1] * TILE + 2, o.size[0] * TILE - 4, o.size[1] * TILE - 4)
      .stroke({ color: 0xf77622, width: 1.5, alpha: 0.9 });
    const name = o.type ?? "";
    const label = new Text({ text: o.size[0] >= 2 ? name : name.slice(0, 2), style: { fontSize: 24, fill: "#ffe2c0", stroke: { color: "#4a2200", width: 5 } } });
    label.scale.set(0.5);
    label.position.set(o.cell[0] * TILE + 4, o.cell[1] * TILE + 3);
    overlay.addChild(label);
  }
  overlay.addChild(fp);
}

/** Territory tint + 8x8 chunk borders (PRD 4.3). */
export function territoryLayer(L: Level): Container {
  const c = new Container();
  const tint = new Graphics();
  const col: Record<string, number> = { human: 0xf7a23a, nature: 0x3ddc63 };
  for (let y = 0; y < L.h; y++)
    for (let x = 0; x < L.w; x++) {
      const t = L.terrains[L.grid[y * L.w + x]];
      if (col[t.owner]) tint.rect(x * TILE, y * TILE, TILE, TILE).fill({ color: col[t.owner], alpha: 0.22 });
    }
  const lines = new Graphics();
  const C = 8;
  for (let cy = 0; cy < L.h / C; cy++)
    for (let cx = 0; cx < L.w / C; cx++) {
      let tot = 0, hum = 0, nat = 0;
      for (let y = cy * C; y < (cy + 1) * C; y++)
        for (let x = cx * C; x < (cx + 1) * C; x++) {
          const t = L.terrains[L.grid[y * L.w + x]];
          if (!t.contestable) continue;
          tot++;
          if (t.owner === "human") hum++;
          if (t.owner === "nature") nat++;
        }
      const color = !tot ? 0x3a5a9a : hum / tot >= 0.6 ? 0xf77622 : nat / tot >= 0.6 ? 0x2fbf55 : 0xffffff;
      lines.rect(cx * C * TILE + 1, cy * C * TILE + 1, C * TILE - 2, C * TILE - 2).stroke({ color, width: 2, alpha: color === 0xffffff ? 0.5 : 0.85 });
    }
  c.addChild(tint, lines);
  return c;
}
