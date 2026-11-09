import {
  Application, Assets, Container, Graphics, Rectangle, Sprite, Text, Texture, TextureSource,
} from "pixi.js";
import {
  ANIM_LABEL, ATTACK_LABEL, DIRS, durations, el, fpsFor, frameAt, hitIndex, loadSheet, prefs, resolve, savePrefs,
  type AnimName, type Atlas, type AttackVersion, type Dir, type Manifest, type Unit,
} from "./data";
import { bodyWidth, drawFrame } from "./sprites";
import { Lighting, WEATHER_LABEL, sky, type LightMode, type Weather } from "./lighting";
import { WeatherLayer } from "./weather";
import { drawLevel, loadLevel, territoryLayer } from "./level";

TextureSource.defaultOptions.scaleMode = "nearest";

// Map scale. The fixed ice-age level and the small demo map use 32px tiles;
// the high-detail demo map uses 64px tiles (units 64px / 128px).
let TILE = 32;
let MAP_W = 44;
let MAP_H = 28;
let SET_PREFIX = "ice_snow_";
/** world units per original 32px tile: speeds, reach and lights scale with it */
let K = 1;
type Terrain = "snow" | "tundra" | "water" | "mud" | "block";
const TERRAIN_SET = (): Record<Exclude<Terrain, "snow" | "block">, string> => ({
  tundra: SET_PREFIX + "tundra", water: SET_PREFIX + "water", mud: SET_PREFIX + "mud",
});
const FALLBACK_COLOR: Record<Terrain, number> = { snow: 0xdfe8f2, tundra: 0x7d7a4f, water: 0x1d5fa8, mud: 0x6b4423, block: 0x222222 };
type State = "idle" | "walk" | "attack" | "rest" | "death";
type Mode = "auto" | Exclude<State, "death">;
const STATE_LABEL: Record<Mode, string> = { auto: "自动", idle: "待机", walk: "行走", attack: "攻击", rest: "休息" };
const LIGHT_LABEL: Record<LightMode, string> = { lit: "法线光照", tint: "色调滤镜（旧）", off: "关闭" };

const SIZE_STATS: Record<string, { hp: number; dmg: number; speed: number; radius: number }> = {
  micro: { hp: 30, dmg: 3, speed: 38, radius: 6 },
  small: { hp: 60, dmg: 6, speed: 30, radius: 8 },
  medium: { hp: 120, dmg: 16, speed: 32, radius: 10 },
  medium_large: { hp: 200, dmg: 24, speed: 30, radius: 14 },
  large: { hp: 320, dmg: 34, speed: 20, radius: 22 },
};

function rng(seed: number) {
  return () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}

// ---------------------------------------------------------------- terrain
function buildTerrain(seed: number): Terrain[] {
  const W = MAP_W + 1, H = MAP_H + 1;
  const v: Terrain[] = new Array(W * H).fill("snow");
  const r = rng(seed);
  const at = (x: number, y: number) => (x < 0 || y < 0 || x >= W || y >= H ? "snow" : v[y * W + x]);
  const paint = (cx: number, cy: number, rad: number, t: Terrain) => {
    for (let y = Math.floor(cy - rad - 1); y <= cy + rad + 1; y++)
      for (let x = Math.floor(cx - rad - 1); x <= cx + rad + 1; x++) {
        if (x < 1 || y < 1 || x >= W - 1 || y >= H - 1) continue;
        const d = Math.hypot((x - cx) * 0.9, y - cy) + (r() - 0.5) * 1.4;
        if (d > rad) continue;
        // two different non-snow terrains never touch: each cell needs one tileset
        let ok = true;
        for (let dy = -1; dy <= 1 && ok; dy++) for (let dx = -1; dx <= 1; dx++) {
          const n = at(x + dx, y + dy);
          if (n !== "snow" && n !== t) { ok = false; break; }
        }
        if (ok) v[y * W + x] = t;
      }
  };
  // patch sizes were tuned on the 44-wide classic map: scale them to this map
  const k = Math.max(0.55, W / 45);
  paint(W * 0.5, H * 0.72, 5.5 * k, "water");
  paint(W * 0.56, H * 0.62, 3.5 * k, "water");
  paint(W * 0.5, H * 0.2, 2.5 * k, "water");
  for (let i = 0; i < 6; i++) paint(3 + r() * W * 0.35, 2 + r() * (H - 4), (2.5 + r() * 3.5) * k, "tundra");
  for (let i = 0; i < 4; i++) paint(W * 0.66 + r() * W * 0.28, 3 + r() * (H - 6), (2 + r() * 3) * k, "mud");
  return v;
}

interface TileLookup { color: Map<string, Texture>; normal: Map<string, Texture> }
async function loadTilesets(m: Manifest): Promise<Record<string, TileLookup>> {
  const out: Record<string, TileLookup> = {};
  for (const ts of m.tilesets) {
    try {
      const [meta, tex, ntex] = await Promise.all([
        fetch(ts.json).then((r) => r.json()), Assets.load<Texture>(ts.png),
        ts.normal ? Assets.load<Texture>(ts.normal) : Promise.resolve(null),
      ]);
      const color = new Map<string, Texture>(), normal = new Map<string, Texture>();
      for (const t of meta.tiles as { x: number; y: number; corners: Record<string, string> }[]) {
        const key = ["NW", "NE", "SW", "SE"].map((k) => (t.corners[k] === "lower" ? "L" : "U")).join("");
        if (color.has(key)) continue;
        const fr = new Rectangle(t.x, t.y, TILE, TILE);
        color.set(key, new Texture({ source: tex.source, frame: fr }));
        if (ntex) normal.set(key, new Texture({ source: ntex.source, frame: fr.clone() }));
      }
      out[ts.id] = { color, normal };
    } catch {
      out[ts.id] = { color: new Map(), normal: new Map() };
    }
  }
  return out;
}

function drawTerrain(layer: Container, nlayer: Container, v: Terrain[], sets: Record<string, TileLookup>) {
  const W = MAP_W + 1;
  const anySet = Object.values(sets).find((s) => s.color.size);
  for (let y = 0; y < MAP_H; y++)
    for (let x = 0; x < MAP_W; x++) {
      const c = [v[y * W + x], v[y * W + x + 1], v[(y + 1) * W + x], v[(y + 1) * W + x + 1]];
      const other = c.find((t) => t !== "snow") as Exclude<Terrain, "snow" | "block"> | undefined;
      const set = other ? sets[TERRAIN_SET()[other]] : anySet;
      const key = c.map((t) => (other && t === other ? "L" : "U")).join("");
      const tex = set?.color.get(key);
      if (tex) {
        const s = new Sprite(tex);
        s.position.set(x * TILE, y * TILE);
        layer.addChild(s);
        const nt = set?.normal.get(key);
        if (nt) {
          const ns = new Sprite(nt);
          ns.position.set(x * TILE, y * TILE);
          nlayer.addChild(ns);
        }
      } else {
        layer.addChild(new Graphics().rect(x * TILE, y * TILE, TILE, TILE).fill(FALLBACK_COLOR[other ?? "snow"]));
      }
    }
}

/** Centres of the mud patches = human camps; they get campfires at night. */
function campSpots(v: Terrain[]): [number, number][] {
  const W = MAP_W + 1;
  const seen = new Set<number>();
  const out: [number, number][] = [];
  for (let i = 0; i < v.length; i++) {
    if (v[i] !== "mud" || seen.has(i)) continue;
    const stack = [i];
    let sx = 0, sy = 0, n = 0;
    seen.add(i);
    while (stack.length) {
      const j = stack.pop()!;
      const x = j % W, y = Math.floor(j / W);
      sx += x; sy += y; n++;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const k = (y + dy) * W + x + dx;
        if (x + dx >= 0 && x + dx < W && v[k] === "mud" && !seen.has(k)) { seen.add(k); stack.push(k); }
      }
    }
    if (n > 6) out.push([(sx / n) * TILE, (sy / n) * TILE]);
  }
  return out;
}

// ---------------------------------------------------------------- units
interface UnitTex {
  unit: Unit; atlas: Atlas; frames: Map<string, Texture>; nframes: Map<string, Texture>;
  bodyW: number; thumb: string; foot: number;
}

async function loadUnitTex(u: Unit): Promise<UnitTex> {
  const [sheet, base, nbase] = await Promise.all([
    loadSheet(u), Assets.load<Texture>(u.files.png),
    u.files.normal ? Assets.load<Texture>(u.files.normal) : Promise.resolve(null),
  ]);
  const frames = new Map<string, Texture>(), nframes = new Map<string, Texture>();
  for (const [name, f] of Object.entries(sheet.atlas.frames)) {
    const r = new Rectangle(f.frame.x, f.frame.y, f.frame.w, f.frame.h);
    frames.set(name, new Texture({ source: base.source, frame: r }));
    if (nbase) nframes.set(name, new Texture({ source: nbase.source, frame: r.clone() }));
  }
  const rot = sheet.atlas.animations["rotation_south-east"]?.[0] ?? Object.keys(sheet.atlas.frames)[0];
  const c = document.createElement("canvas");
  const s = Math.max(1, Math.floor(48 / u.cell)) || 1;
  c.width = c.height = u.cell * s;
  drawFrame(c.getContext("2d")!, sheet.img, sheet.atlas, rot, 0, 0, s);
  const foot = sheet.atlas.meta.unit.foot ?? (u.anchor.y - 0.5) * u.cell;
  return { unit: u, atlas: sheet.atlas, frames, nframes, bodyW: bodyWidth(sheet.img, sheet.atlas, rot), thumb: c.toDataURL(), foot };
}

const DIRV: Record<Dir, [number, number]> = {
  south: [0, 1], "south-east": [0.7071, 0.7071], east: [1, 0], "north-east": [0.7071, -0.7071],
  north: [0, -1], "north-west": [-0.7071, -0.7071], west: [-1, 0], "south-west": [-0.7071, 0.7071],
};
function dirFromVec(dx: number, dy: number): Dir {
  const order: Dir[] = ["east", "south-east", "south", "south-west", "west", "north-west", "north", "north-east"];
  const i = Math.round(Math.atan2(dy, dx) / (Math.PI / 4));
  return order[(i + 8) % 8];
}

/** Sleep period from the species sheet ("夜晚/长", "白天/中", "全天候随机/中"). */
function sleepPeriod(u: Unit): "night" | "day" | "random" {
  const s = u.sheet?.data?.["休眠时段/时长"] ?? "";
  if (s.startsWith("白天")) return "day";
  if (s.startsWith("全天候")) return "random";
  return "night";
}

interface Ent {
  ut: UnitTex;
  root: Container; sprite: Sprite; flashS: Sprite;          // colour pass
  nsprite: Sprite;                                            // normal pass
  fx: Container; ring: Graphics; hp: Graphics; zzz: Sprite;  // unlit overlay
  x: number; y: number; dir: Dir; state: State; force: Mode; animT: number;
  tx: number; ty: number; wait: number; target: Ent | null; hpNow: number; hpMax: number;
  cooldown: number; flash: number; dead: number; restRoll: number;
  atk: { t: number; hitDone: boolean } | null;   // one attack in progress (timing on)
  freeze: number;                                  // hitstop
  push: { x: number; y: number; t: number } | null;
}

export async function renderLab(root: HTMLElement, m: Manifest, classic = false): Promise<() => void> {
  const mapMode = classic ? "demo" : prefs.labMap;
  const hd = mapMode === "hd" && m.tilesets.some((t) => t.id.startsWith("hd_snow_"));
  TILE = hd ? 64 : 32; SET_PREFIX = hd ? "hd_snow_" : "ice_snow_"; K = TILE / 32;
  const host = el("div", { class: "lab-canvas" });
  const side = el("aside", { class: "lab-side" });
  const hud = el("div", { class: "lab-hud" });
  root.append(el("section", { class: "lab" }, el("div", { class: "lab-main" }, host, hud), side));
  host.append(el("p", { class: "muted pad" }, "加载中…"));

  const app = new Application();
  await app.init({
    resizeTo: host, background: "#11151c", antialias: false, roundPixels: true, autoDensity: true,
    resolution: window.devicePixelRatio || 1, preference: "webgl",
  });
  host.replaceChildren(app.canvas);

  // colour world + normal world are rendered off-screen and combined by the lighting quad
  const world = new Container();
  const ground = new Container();
  const actors = new Container();
  actors.sortableChildren = true;
  world.addChild(ground, actors);
  const nworld = new Container();
  const nground = new Container();
  const nactors = new Container();
  nactors.sortableChildren = true;
  nworld.addChild(nground, nactors);
  // unlit overlay in world space: rings, HP bars, Zzz, hit sparks, campfire flames
  const fxWorld = new Container();
  const fxUnder = new Container();
  const fxOver = new Container();
  fxOver.sortableChildren = true;
  const sparks = new Graphics();
  fxWorld.addChild(fxUnder, fxOver, sparks);

  const lighting = new Lighting(app.renderer, app.screen.width, app.screen.height);
  const weatherLayer = new WeatherLayer();
  weatherLayer.resize(app.screen.width, app.screen.height);
  app.stage.addChild(lighting.quad, fxWorld, weatherLayer.view);

  const level = mapMode === "ice_age" ? await loadLevel(m) : null;
  MAP_W = level ? level.w : hd ? 30 : 44;
  MAP_H = level ? level.h : hd ? 18 : 28;
  const terrain = level ? [] : buildTerrain(7);
  const [sets, uts] = await Promise.all([level ? Promise.resolve({}) : loadTilesets(m), Promise.all(m.units.map(loadUnitTex))]);
  const territory = new Container();
  if (level) {
    await drawLevel(app.renderer, level, ground, nground, actors, fxUnder);
    territory.addChild(territoryLayer(level));
    territory.visible = false;
    fxUnder.addChildAt(territory, 0);
  } else drawTerrain(ground, nground, terrain, sets);
  const camps = level ? level.camps : campSpots(terrain);
  // HD map: dress each human camp with props (tent, campfire, drying rack, bone hut)
  if (hd && m.props?.length) {
    const tex = new Map<string, { c: Texture; n: Texture | null }>();
    await Promise.all(m.props.map(async (p) => tex.set(p.id, {
      c: await Assets.load<Texture>(p.png), n: p.normal ? await Assets.load<Texture>(p.normal) : null })));
    const layout: [string, number, number][] = [["campfire", 0, 0.35], ["hide_tent", -1.4, -0.5], ["drying_rack", 1.3, -0.3], ["bone_hut", 0.2, 1.4]];
    for (const [cx, cy] of camps)
      for (const [id, dx, dy] of layout) {
        const t = tex.get(id);
        const x = cx + dx * TILE, y = cy + dy * TILE;
        const vx = Math.round(x / TILE), vy = Math.round(y / TILE);
        if (!t || vx < 1 || vy < 1 || vx >= MAP_W || vy >= MAP_H || terrain[vy * (MAP_W + 1) + vx] === "water") continue;
        const sp = new Sprite(t.c);
        sp.anchor.set(0.5, 1);
        sp.position.set(Math.round(x), Math.round(y));
        sp.zIndex = y;
        actors.addChild(sp);
        if (t.n) {
          const ns = new Sprite(t.n);
          ns.anchor.set(0.5, 1);
          ns.position.copyFrom(sp.position);
          ns.zIndex = y;
          nactors.addChild(ns);
        }
      }
  }
  const flames = new Graphics();
  fxUnder.addChild(flames);

  const zText = new Text({ text: "Zz", style: { fontFamily: "Silkscreen, monospace", fontSize: 24, fill: "#ffffff", stroke: { color: "#1b1f2a", width: 6 } } });
  const zTex = app.renderer.generateTexture(zText);

  const terrainAt = (px: number, py: number): Terrain => {
    if (level) {
      const t = level.cellAt(px, py);
      if (!t) return "block";
      return t.owner === "volcano" ? "block" : t.kind === "water" ? "water" : t.id === "h_camp" ? "mud" : "snow";
    }
    const x = Math.round(px / TILE), y = Math.round(py / TILE);
    if (x < 0 || y < 0 || x > MAP_W || y > MAP_H) return "snow";
    return terrain[y * (MAP_W + 1) + x];
  };
  const walkable = (u: Unit, px: number, py: number) => {
    if (px < 8 || py < 12 || px > MAP_W * TILE - 8 || py > MAP_H * TILE - 4) return false;
    if (u.habitat === "air") return true;
    const t = terrainAt(px, py);
    if (t === "block") return false;
    return u.habitat === "water" ? t === "water" : t !== "water";
  };

  // ---------------- state / controls
  const ui = {
    mode: "auto" as Mode, spawnId: uts.find((x) => !x.unit.demo)?.unit.id ?? uts[0]?.unit.id,
    hour: 9.5, autoTime: true, immortal: false, rings: true, bars: true, speed: 1,
    selected: null as Ent | null, zoom: 2, light: "lit" as LightMode, weather: "clear" as Weather, bands: false,
  };
  const ents: Ent[] = [];
  let shake = 0;

  function spawn(ut: UnitTex, x: number, y: number): Ent | null {
    const u = ut.unit;
    for (let i = 0; i < 30 && !walkable(u, x, y); i++) { x += (Math.random() - 0.5) * 60 * K; y += (Math.random() - 0.5) * 60 * K; }
    if (!walkable(u, x, y)) return null;
    const st = SIZE_STATS[u.sizeClass] ?? SIZE_STATS.medium;
    const air = u.habitat === "air";
    const rx = Math.max(5, ut.bodyW * 0.42), ry = Math.max(2, ut.bodyW * 0.16);
    const rootC = new Container();
    const shadow = new Graphics().ellipse(0, 0, air ? rx * 0.7 : rx, air ? ry * 0.7 : ry).fill({ color: 0x19192d, alpha: air ? 0.24 : 0.4 });
    const sprite = new Sprite();
    sprite.anchor.set(0.5);
    const flashS = new Sprite();
    flashS.anchor.set(0.5);
    flashS.blendMode = "add";
    flashS.visible = false;
    rootC.addChild(shadow, sprite, flashS);
    actors.addChild(rootC);
    const nsprite = new Sprite();
    nsprite.anchor.set(0.5);
    nactors.addChild(nsprite);
    const fx = new Container();
    const ring = new Graphics().ellipse(0, 0, rx + 1, ry + 0.6).stroke({ color: u.faction === "nature" ? 0x63c74d : 0xf77622, width: 1 });
    const hp = new Graphics();
    const zzz = new Sprite(zTex);
    zzz.scale.set(0.25);
    zzz.visible = false;
    fx.addChild(ring, hp, zzz);
    fxOver.addChild(fx);
    const e: Ent = {
      ut, root: rootC, sprite, flashS, nsprite, fx, ring, hp, zzz, x, y,
      dir: DIRS[Math.floor(Math.random() * 8)], state: "idle", force: "auto", animT: Math.random() * 3000,
      tx: x, ty: y, wait: Math.random() * 2, target: null, hpNow: st.hp, hpMax: st.hp, cooldown: Math.random(),
      flash: 0, dead: 0, restRoll: Math.random(), atk: null, freeze: 0, push: null,
    };
    rootC.eventMode = "static";
    rootC.cursor = "pointer";
    ents.push(e);
    return e;
  }
  function removeEnt(e: Ent) {
    e.root.destroy({ children: true });
    e.nsprite.destroy();
    e.fx.destroy({ children: true });
  }
  function clearAll() {
    for (const e of ents) removeEnt(e);
    ents.length = 0;
    select(null);
  }
  function randomSpot(u: Unit, faction?: "nature" | "human") {
    for (let i = 0; i < 200; i++) {
      const fx = faction === "nature" ? 0.05 + Math.random() * 0.45 : faction === "human" ? 0.5 + Math.random() * 0.45 : Math.random();
      const x = fx * MAP_W * TILE, y = (0.06 + Math.random() * 0.9) * MAP_H * TILE;
      if (walkable(u, x, y)) return [x, y];
    }
    return [MAP_W * TILE / 2, MAP_H * TILE / 2];
  }
  function battle(n = 100) {
    clearAll();
    const nature = uts.filter((x) => x.unit.faction === "nature");
    const human = uts.filter((x) => x.unit.faction === "human");
    const weight = (ut: UnitTex) => (ut.unit.sizeClass === "large" ? 1 : ut.unit.sizeClass === "micro" ? 2 : 3);
    const pick = (list: UnitTex[]) => {
      const tot = list.reduce((a, b) => a + weight(b), 0);
      let r = Math.random() * tot;
      for (const ut of list) { r -= weight(ut); if (r <= 0) return ut; }
      return list[0];
    };
    for (let i = 0; i < n; i++) {
      const isHuman = human.length && (i % 5 < 2 || !nature.length);
      const ut = isHuman ? pick(human) : pick(nature);
      const [x, y] = randomSpot(ut.unit, ut.unit.faction);
      spawn(ut, x, y);
    }
  }

  // ---------------- simulation
  const isNight = () => ui.hour < 6 || ui.hour >= 19;
  function wantsRest(e: Ent) {
    const p = sleepPeriod(e.ut.unit);
    if (p === "night") return isNight();
    if (p === "day") return !isNight() && ui.hour > 11 && ui.hour < 15;
    return Math.floor(ui.hour / 3) % 4 === Math.floor(e.restRoll * 4);
  }
  /** half the drawn body width: reach works for any canvas size */
  const bodyR = (e: Ent) => Math.max(4, e.ut.bodyW * 0.45);
  function enemyNear(e: Ent, radius: number): Ent | null {
    let best: Ent | null = null, bd = radius;
    for (const o of ents) {
      if (o === e || o.dead || o.ut.unit.faction === e.ut.unit.faction) continue;
      const d = Math.hypot(o.x - e.x, o.y - e.y);
      if (d < bd) { bd = d; best = o; }
    }
    return best;
  }
  function pickWander(e: Ent) {
    for (let i = 0; i < 12; i++) {
      const a = Math.random() * Math.PI * 2, d = (40 + Math.random() * 140) * K;
      const x = e.x + Math.cos(a) * d, y = e.y + Math.sin(a) * d;
      if (walkable(e.ut.unit, x, y)) { e.tx = x; e.ty = y; return; }
    }
    e.tx = e.x; e.ty = e.y;
  }
  function moveToward(e: Ent, x: number, y: number, dt: number, speed: number) {
    const dx = x - e.x, dy = y - e.y, d = Math.hypot(dx, dy);
    if (d < 2) return true;
    const step = Math.min(d, speed * dt);
    const nx = e.x + (dx / d) * step, ny = e.y + (dy / d) * step;
    e.dir = dirFromVec(dx, dy);
    if (walkable(e.ut.unit, nx, ny)) { e.x = nx; e.y = ny; return false; }
    pickWander(e);
    return true;
  }

  /** Frames, durations and hit index for an entity's current animation. */
  function anim(e: Ent) {
    const r = resolve(e.ut.atlas, e.state as AnimName, e.dir, prefs.attack);
    const fps = fpsFor(e.ut.unit, e.state as AnimName);
    const durs = durations(e.ut.atlas, r.key, e.dir, r.frames, fps, e.state === "attack" && prefs.feel);
    return { ...r, durs, hit: hitIndex(e.ut.atlas, r.key, e.dir, r.frames.length), total: durs.reduce((a, b) => a + b, 0) };
  }

  /** Attack against `t` (may be null when forced): with timing on, one timed
   *  swing whose damage lands on the hit frame; with it off, the old loop. */
  function attack(e: Ent, t: Ent | null, dt: number) {
    const st = SIZE_STATS[e.ut.unit.sizeClass] ?? SIZE_STATS.medium;
    e.state = "attack";
    if (t) e.dir = dirFromVec(t.x - e.x, t.y - e.y);
    if (!prefs.feel) {
      if (t && e.cooldown <= 0) { hit(e, t, st.dmg); e.cooldown = 0.9; }
      return;
    }
    if (!e.atk) {
      if (e.cooldown > 0) { e.state = "idle"; return; }
      e.atk = { t: 0, hitDone: false };
      e.animT = 0;
    }
    const a = anim(e);
    const hitAt = a.durs.slice(0, a.hit).reduce((x, y) => x + y, 0);
    if (!e.atk.hitDone && e.animT >= hitAt) {
      e.atk.hitDone = true;
      const heavy = e.ut.unit.sizeClass === "large";
      e.freeze = heavy ? 0.11 : 0.07;                  // hitstop
      if (t && !t.dead) hit(e, t, st.dmg, heavy);
      if (heavy) shake = 0.14;
    }
    if (e.animT >= a.total) {
      e.atk = null;
      e.cooldown = 0.45 + Math.random() * 0.3;
      e.state = "idle";
    }
  }

  function step(e: Ent, dt: number) {
    const u = e.ut.unit;
    const st = SIZE_STATS[u.sizeClass] ?? SIZE_STATS.medium;
    if (e.dead) {
      e.state = "death";
      const total = anim(e).key === "death" ? anim(e).total : 0;
      const fade = Math.max(0, e.animT - total) / 800;   // body fades after the last frame
      e.root.alpha = e.nsprite.alpha = Math.max(0, 1 - fade);
      e.fx.alpha = 0;
      e.dead = fade >= 1 ? 2 : 0.5;
      return;
    }
    e.cooldown -= dt;
    e.flash = Math.max(0, e.flash - dt);
    if (e.push) {
      e.push.t -= dt;
      const k = Math.max(0, e.push.t) / 0.12;
      if (walkable(u, e.x + e.push.x * dt * 50 * k, e.y + e.push.y * dt * 50 * k)) {
        e.x += e.push.x * dt * 50 * k;
        e.y += e.push.y * dt * 50 * k;
      }
      if (e.push.t <= 0) e.push = null;
    }
    const mode = e.force !== "auto" ? e.force : ui.mode;
    if (mode !== "attack") e.atk = e.atk && e.state === "attack" ? e.atk : null;

    if (e.atk) { attack(e, e.target, dt); return; }        // finish a swing once started
    if (mode === "idle" || mode === "rest") { e.state = mode; return; }
    if (mode === "walk") {
      e.state = "walk";
      if (moveToward(e, e.tx, e.ty, dt, st.speed * K)) pickWander(e);
      return;
    }
    if (mode === "attack") {
      const t = enemyNear(e, bodyR(e) + 18 * K);
      e.target = t;
      attack(e, t, dt);
      return;
    }
    // ---- auto
    if (wantsRest(e) && !(e.target && !e.target.dead)) { e.state = "rest"; return; }
    if (!e.target || e.target.dead || Math.hypot(e.target.x - e.x, e.target.y - e.y) > 220 * K) e.target = enemyNear(e, 150 * K);
    if (e.target) {
      const t = e.target;
      const reach = bodyR(e) + bodyR(t) + 4;
      if (Math.hypot(t.x - e.x, t.y - e.y) > reach) {
        e.state = "walk";
        moveToward(e, t.x, t.y, dt, st.speed * 1.25 * K);
      } else {
        attack(e, t, dt);
      }
      return;
    }
    if (e.wait > 0) { e.state = "idle"; e.wait -= dt; return; }
    e.state = "walk";
    if (e.tx === e.x && e.ty === e.y) pickWander(e);
    if (moveToward(e, e.tx, e.ty, dt, st.speed * K)) { e.wait = 1 + Math.random() * 3; e.tx = e.x; e.ty = e.y; }
  }

  /** Killed: play the death animation (if the unit has one), then fade out. */
  function kill(e: Ent) {
    if (e.dead) return;
    e.hpNow = 0;
    e.dead = 0.001;
    e.state = "death";
    e.animT = 0;
    e.atk = null;
    e.freeze = 0;
    if (ui.selected === e) select(null);
  }

  const sparkList: { x: number; y: number; t: number; big: boolean }[] = [];
  function hit(a: Ent, b: Ent, dmg: number, heavy = false) {
    b.flash = prefs.feel ? 0.1 : 0.18;
    if (prefs.feel) {
      b.freeze = Math.max(b.freeze, heavy ? 0.11 : 0.07);
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1;
      b.push = { x: dx / d, y: dy / d, t: 0.12 };
      sparkList.push({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 - b.ut.unit.cell * 0.25, t: 0, big: heavy });
    }
    if (ui.immortal) return;
    b.hpNow -= dmg * (0.75 + Math.random() * 0.5);
    if (b.hpNow <= 0) kill(b);
    if (!b.target) b.target = a;
  }

  function draw(e: Ent) {
    const u = e.ut.unit;
    const a = anim(e);
    const loop = !((e.state === "attack" && prefs.feel) || e.state === "death");
    if (a.frames.length) {
      const name = a.frames[frameAt(a.durs, e.animT, loop)];
      const tex = e.ut.frames.get(name);
      if (tex && e.sprite.texture !== tex) {
        e.sprite.texture = tex;
        e.flashS.texture = tex;
        const nt = e.ut.nframes.get(name);
        if (nt) e.nsprite.texture = nt;
      }
    }
    // the original attack has no lunge drawn in: nudge it toward the target on the hit
    let lx = 0, ly = 0;
    if (prefs.feel && e.state === "attack" && a.key === "attack" && e.atk) {
      const hitAt = a.durs.slice(0, a.hit).reduce((x, y) => x + y, 0);
      const k = Math.max(0, 1 - Math.abs(e.animT - hitAt) / 140);
      [lx, ly] = DIRV[e.dir].map((v) => v * 4 * k) as [number, number];
    }
    const shakeX = e.flash > 0 ? (Math.random() - 0.5) * 2 : 0;
    const px = Math.round(e.x + lx + shakeX), py = Math.round(e.y + ly);
    const hover = u.habitat === "air" ? -7 + Math.round(Math.sin(e.animT / 330) * 1.5) : 0;
    e.root.position.set(px, py);
    e.root.zIndex = e.y;
    e.sprite.position.set(0, -e.ut.foot + hover);
    e.flashS.position.copyFrom(e.sprite.position);
    e.flashS.visible = e.flash > 0;
    e.flashS.alpha = Math.min(1, e.flash * 10);
    e.sprite.tint = !prefs.feel && e.flash > 0 ? 0xff9a9a : 0xffffff;
    e.nsprite.position.set(px, py - e.ut.foot + hover);
    e.nsprite.zIndex = e.y;
    e.fx.position.set(px, py);
    e.fx.zIndex = e.y;
    e.ring.visible = ui.rings;
    const top = -e.ut.foot - u.canvas / 2 + 2;
    e.zzz.visible = e.state === "rest";
    if (e.zzz.visible) e.zzz.position.set(4, top - 6 + Math.sin(e.animT / 500) * 1.5);
    e.hp.clear();
    if (ui.bars && (e.hpNow < e.hpMax || ui.selected === e)) {
      const w = Math.max(12, Math.min(28, u.canvas * 0.45));
      e.hp.rect(-w / 2, top - 3, w, 2).fill(0x26162a).rect(-w / 2, top - 3, (w * e.hpNow) / e.hpMax, 2).fill(0xe43b44);
    }
    if (ui.selected === e) e.hp.ellipse(0, 0, 16, 6).stroke({ color: 0xffffff, width: 1, alpha: 0.9 });
  }

  function drawSparks(dt: number) {
    sparks.clear();
    for (let i = sparkList.length - 1; i >= 0; i--) {
      const s = sparkList[i];
      s.t += dt;
      const life = s.big ? 0.22 : 0.16;
      if (s.t > life) { sparkList.splice(i, 1); continue; }
      const k = s.t / life, r = (s.big ? 9 : 6) * (0.4 + k);
      const col = k < 0.35 ? 0xffffff : 0xffd36b;
      for (let j = 0; j < 8; j++) {
        const ang = (j / 8) * Math.PI * 2 + (j % 2) * 0.2;
        const len = j % 2 ? r * 0.55 : r;
        sparks.moveTo(Math.round(s.x + Math.cos(ang) * r * 0.3), Math.round(s.y + Math.sin(ang) * r * 0.3))
          .lineTo(Math.round(s.x + Math.cos(ang) * len), Math.round(s.y + Math.sin(ang) * len));
      }
      sparks.stroke({ color: col, width: s.big ? 2 : 1, alpha: 1 - k * 0.6 });
    }
  }

  // ---------------- camera
  const view = { x: 0, y: 0 };
  function applyCamera() {
    const vw = app.screen.width, vh = app.screen.height;
    const mw = MAP_W * TILE * ui.zoom, mh = MAP_H * TILE * ui.zoom;
    view.x = mw < vw ? (vw - mw) / 2 : Math.min(0, Math.max(vw - mw, view.x));
    view.y = mh < vh ? (vh - mh) / 2 : Math.min(0, Math.max(vh - mh, view.y));
  }
  function syncCamera() {
    const sx = shake > 0 ? Math.round((Math.random() - 0.5) * 4) : 0;
    const sy = shake > 0 ? Math.round((Math.random() - 0.5) * 4) : 0;
    for (const c of [world, nworld, fxWorld]) {
      c.scale.set(ui.zoom);
      c.position.set(Math.round(view.x) + sx, Math.round(view.y) + sy);
    }
  }
  function centerOn(wx: number, wy: number) {
    view.x = app.screen.width / 2 - wx * ui.zoom;
    view.y = app.screen.height / 2 - wy * ui.zoom;
    applyCamera();
  }
  const toWorld = (gx: number, gy: number) => [(gx - view.x) / ui.zoom, (gy - view.y) / ui.zoom];
  function entAt(wx: number, wy: number): Ent | null {
    let best: Ent | null = null, bd = 18;
    for (const e of ents) {
      if (e.dead) continue;
      const d = Math.hypot(e.x - wx, e.y - e.ut.foot * 0.6 - wy);
      if (d < bd + e.ut.unit.cell * 0.15) { bd = d; best = e; }
    }
    return best;
  }
  app.stage.eventMode = "static";
  app.stage.hitArea = app.screen;
  let drag: { x: number; y: number; vx: number; vy: number; moved: boolean } | null = null;
  app.stage.on("pointerdown", (ev) => { drag = { x: ev.global.x, y: ev.global.y, vx: view.x, vy: view.y, moved: false }; });
  app.stage.on("pointermove", (ev) => {
    if (!drag) return;
    const dx = ev.global.x - drag.x, dy = ev.global.y - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
    if (drag.moved) { view.x = drag.vx + dx; view.y = drag.vy + dy; applyCamera(); }
  });
  app.stage.on("pointerup", (ev) => {
    if (drag && !drag.moved) {
      const [wx, wy] = toWorld(ev.global.x, ev.global.y);
      const hitE = entAt(wx, wy);
      if (hitE) select(hitE);
      else {
        const ut = uts.find((x) => x.unit.id === ui.spawnId);
        if (ut) select(spawn(ut, wx, wy));
      }
    }
    drag = null;
  });
  app.stage.on("pointerupoutside", () => (drag = null));
  const onWheel = (ev: WheelEvent) => {
    ev.preventDefault();
    const old = ui.zoom;
    ui.zoom = Math.max(1, Math.min(5, ui.zoom + (ev.deltaY < 0 ? 1 : -1)));
    if (old === ui.zoom) return;
    const r = app.canvas.getBoundingClientRect();
    const mx = ev.clientX - r.left, my = ev.clientY - r.top;
    view.x = mx - ((mx - view.x) / old) * ui.zoom;
    view.y = my - ((my - view.y) / old) * ui.zoom;
    applyCamera();
    renderSide();
  };
  app.canvas.addEventListener("wheel", onWheel, { passive: false });
  const onResize = () => {
    lighting.resize(app.screen.width, app.screen.height);
    weatherLayer.resize(app.screen.width, app.screen.height);
    app.stage.hitArea = app.screen;
    applyCamera();
  };
  app.renderer.on("resize", onResize);

  // ---------------- side panel
  function select(e: Ent | null) { ui.selected = e; renderSelected(); }
  const selBox = el("div", { class: "panel sel" });
  function renderSelected() {
    const e = ui.selected;
    if (!e) { selBox.replaceChildren(el("p", { class: "muted small" }, "点击地图上的单位查看并单独控制它。")); return; }
    const u = e.ut.unit;
    selBox.replaceChildren(
      el("div", { class: "sel-head" }, el("img", { src: e.ut.thumb, class: "thumb" }),
        el("div", {}, el("strong", {}, u.displayName), el("div", { class: "muted small" }, u.englishName))),
      el("div", { class: "seg wrap" }, ...(["auto", "idle", "walk", "attack", "rest"] as Mode[]).map((s) =>
        el("button", { type: "button", class: e.force === s ? "on" : "", onclick: () => { e.force = s; e.atk = null; renderSelected(); } }, STATE_LABEL[s]))),
      el("div", { class: "row" },
        el("a", { href: `#/unit/${u.id}`, class: "small" }, "查看素材与配置 →"),
        el("button", { type: "button", class: "ghost small", onclick: () => kill(e) }, "击杀（播放死亡）")),
    );
  }
  const clock = el("span", { class: "clock" });
  const renderClock = () => {
    const h = Math.floor(ui.hour), mm = Math.floor((ui.hour - h) * 60);
    const phase = ui.hour < 5 ? "夜" : ui.hour < 8 ? "清晨" : ui.hour < 16.5 ? "白天" : ui.hour < 19 ? "黄昏" : "夜";
    clock.textContent = `${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")} ${phase}`;
  };
  function renderSide() {
    const seg = (items: [string, string][], cur: string, set: (v: string) => void, cls = "seg wrap") =>
      el("div", { class: cls }, ...items.map(([v, l]) => el("button", { type: "button", class: cur === v ? "on" : "", onclick: () => { set(v); renderSide(); } }, l)));
    const check = (label: string, get: boolean, set: (v: boolean) => void) =>
      el("label", { class: "check" }, el("input", { type: "checkbox", checked: get, onchange: (ev: Event) => set((ev.target as HTMLInputElement).checked) }), label);
    side.replaceChildren(
      el("div", { class: "panel" },
        el("h3", {}, "地图"),
        seg([["ice_age", "冰河关卡 96×64"], ["hd", "高清试点 64px"], ["demo", "演示小图"]], level ? "ice_age" : hd ? "hd" : "demo", (v) => {
          prefs.labMap = v as "ice_age" | "hd" | "demo"; savePrefs();
          window.dispatchEvent(new HashChangeEvent("hashchange"));
        }, "seg"),
        ...(level ? [
          check("领地与区块（PRD 4.3）", territory.visible, (v) => (territory.visible = v)),
          el("p", { class: "muted small" }, "冰河时代固定地图：分层地块（dual grid）、火山、资源点、森林边缘的树。橙框是人类开局建筑的占地（还没有美术）。区块边框：橙=人类，绿=自然，白=争夺中。"),
        ] : []),
        ...(hd ? [el("p", { class: "muted small" }, "高清标准试点：64px 地块、64px/128px 单位（冰河斑鬣狗、猛犸象已升级，其余仍是旧 32px，会显得偏小）、营地道具。")] : []),
      ),
      el("div", { class: "panel" },
        el("h3", {}, "全体状态"),
        seg((["auto", "idle", "walk", "attack", "rest"] as Mode[]).map((s) => [s, STATE_LABEL[s]]), ui.mode, (v) => { ui.mode = v as Mode; ents.forEach((e) => (e.atk = null)); }),
        el("p", { class: "muted small" }, "自动：闲逛、追击并攻击敌对阵营、按物种表的休眠时段休息。其他选项强制所有单位播放该动作。"),
      ),
      el("div", { class: "panel" },
        el("h3", {}, "攻击"),
        seg((Object.keys(ATTACK_LABEL) as AttackVersion[]).map((a) => [a, ATTACK_LABEL[a]]), prefs.attack, (v) => { prefs.attack = v as AttackVersion; savePrefs(); }),
        check("攻击节奏 + 打击感", prefs.feel, (v) => { prefs.feel = v; savePrefs(); ents.forEach((e) => (e.atk = null)); }),
        el("p", { class: "muted small" }, "打击感：每次攻击单独播放（蓄力、出击、命中停顿、收招），伤害落在命中帧；命中瞬间短暂定格、火花、被击方后退闪白，大型单位震屏。关闭则为旧的匀速循环。"),
      ),
      el("div", { class: "panel" },
        el("h3", {}, "光照与天气"),
        seg((Object.keys(LIGHT_LABEL) as LightMode[]).map((l) => [l, LIGHT_LABEL[l]]), ui.light, (v) => (ui.light = v as LightMode)),
        check("像素风分级光照", ui.bands, (v) => (ui.bands = v)),
        seg((Object.keys(WEATHER_LABEL) as Weather[]).map((w) => [w, WEATHER_LABEL[w]]), ui.weather, (v) => { ui.weather = v as Weather; weatherLayer.setKind(ui.weather); }),
        el("input", { type: "range", min: "0", max: "23.9", step: "0.1", value: String(ui.hour),
          oninput: (ev: Event) => { ui.hour = +(ev.target as HTMLInputElement).value; ui.autoTime = false; renderClock(); } }),
        el("div", { class: "row" },
          clock,
          seg([["6.3", "清晨"], ["12", "正午"], ["17.8", "黄昏"], ["22", "夜"]], "", (v) => { ui.hour = +v; ui.autoTime = false; renderClock(); }, "seg")),
        check("时间自动流逝", ui.autoTime, (v) => (ui.autoTime = v)),
      ),
      el("div", { class: "panel" },
        el("h3", {}, "放置单位"),
        el("p", { class: "muted small" }, "选中后点击空地放置；点击单位选中它；拖动平移，滚轮缩放。"),
        el("div", { class: "spawn-list" }, ...uts.map((ut) =>
          el("button", {
            type: "button", class: `spawn ${ui.spawnId === ut.unit.id ? "on" : ""} f-${ut.unit.faction}`,
            title: ut.unit.englishName, onclick: () => { ui.spawnId = ut.unit.id; renderSide(); },
          }, el("img", { src: ut.thumb }), el("span", {}, ut.unit.displayName)))),
        el("div", { class: "row" },
          el("button", { type: "button", onclick: () => {
            const ut = uts.find((x) => x.unit.id === ui.spawnId);
            if (ut) for (let i = 0; i < 10; i++) { const [x, y] = randomSpot(ut.unit, ut.unit.faction); spawn(ut, x, y); }
          } }, "+10 个"),
          el("button", { type: "button", onclick: () => battle(100) }, "百人混战"),
          el("button", { type: "button", class: "ghost", onclick: clearAll }, "清空"),
        ),
      ),
      el("div", { class: "panel" },
        el("h3", {}, "显示"),
        check("阵营圈", ui.rings, (v) => (ui.rings = v)),
        check("血条", ui.bars, (v) => (ui.bars = v)),
        check("单位不会死亡", ui.immortal, (v) => (ui.immortal = v)),
        el("div", { class: "row" }, el("span", { class: "small muted" }, "缩放"),
          seg([["1", "1×"], ["2", "2×"], ["3", "3×"], ["4", "4×"]], String(ui.zoom), (v) => { ui.zoom = +v; centerOn(MAP_W * TILE / 2, MAP_H * TILE / 2); }, "seg")),
        el("div", { class: "row" }, el("span", { class: "small muted" }, "速度"),
          seg([["0.25", "0.25×"], ["0.5", "0.5×"], ["1", "1×"], ["2", "2×"]], String(ui.speed), (v) => (ui.speed = +v), "seg")),
      ),
      selBox,
    );
    renderSelected();
    renderClock();
  }

  renderSide();
  battle(60);
  ui.zoom = app.screen.width < 700 || level || hd ? 1 : 2;   // level and HD map open at 1x
  // level: open on the west side (outposts, volcano, two nature start zones)
  if (level) centerOn(22 * TILE, 34 * TILE);
  else centerOn(MAP_W * TILE / 2, MAP_H * TILE / 2);

  let fpsAvg = 60, hudT = 0;
  const ticker = (tk: { deltaMS: number }) => {
    const rdt = Math.min(0.05, tk.deltaMS / 1000);
    const dt = rdt * ui.speed;
    if (ui.autoTime) ui.hour = (ui.hour + dt * 0.2) % 24;
    shake = Math.max(0, shake - rdt);
    for (const e of ents) {
      if (e.freeze > 0 && !e.dead) { e.freeze -= dt; draw(e); continue; }   // hitstop: hold the pose
      e.animT += dt * 1000;
      step(e, dt);
      draw(e);
    }
    for (let i = ents.length - 1; i >= 0; i--) if (ents[i].dead >= 2) { removeEnt(ents[i]); ents.splice(i, 1); }
    drawSparks(dt);

    // lighting: sun / moon / ambient from time + weather; torches & campfires at night
    const S = sky(ui.hour, ui.weather);
    lighting.lights = [];
    if (ui.light === "lit") {
      const flick = () => 0.85 + Math.random() * 0.15;
      const nightK = S.night ? 1 : ui.hour > 17.5 || ui.hour < 7 ? 0.5 : 0;
      if (nightK > 0) {
        for (const [cx, cy] of camps)
          lighting.lights.push({ x: view.x + cx * ui.zoom, y: view.y + cy * ui.zoom, radius: 120 * K * ui.zoom, height: 26 * K * ui.zoom, color: [1, 0.58, 0.26], intensity: 0.85 * nightK * flick() });
        for (const e of ents) {
          if (lighting.lights.length >= 16) break;
          if (e.ut.unit.faction !== "human" || e.dead) continue;
          lighting.lights.push({ x: view.x + e.x * ui.zoom, y: view.y + (e.y - 12) * ui.zoom, radius: 56 * K * ui.zoom, height: 20 * K * ui.zoom, color: [1, 0.66, 0.32], intensity: 0.5 * nightK * flick() });
        }
      }
    }
    lighting.set({ mode: ui.light, tint: S.tint, ambient: S.ambient, sunDir: S.sunDir, sunColor: S.sunColor, bands: ui.bands ? 4 : 0 });
    // campfire flames (unlit pixels) where the camp lights are
    flames.clear();
    if (ui.light === "lit" && (S.night || ui.hour > 17.5 || ui.hour < 7)) {
      for (const [cx, cy] of camps) {
        for (let k = 0; k < 5; k++) {
          const fx = Math.round(cx + (Math.random() - 0.5) * 6), fy = Math.round(cy - Math.random() * 7);
          flames.rect(fx, fy, 2, 2).fill(k % 2 ? 0xffd36b : 0xf77622);
        }
      }
    }
    syncCamera();
    lighting.render(world, nworld);
    const amb = ui.light === "lit" ? S.ambient.map((v, i) => Math.min(1, v + S.sunColor[i] * 0.6)) : ui.light === "tint" ? S.tint : [1, 1, 1];
    const tintHex = (Math.round(amb[0] * 255) << 16) | (Math.round(amb[1] * 255) << 8) | Math.round(amb[2] * 255);
    weatherLayer.update(rdt, tintHex, ui.zoom);

    fpsAvg = fpsAvg * 0.95 + (1000 / Math.max(1, tk.deltaMS)) * 0.05;
    hudT += tk.deltaMS;
    if (hudT > 300) {
      hudT = 0;
      renderClock();
      const live = ents.filter((e) => !e.dead);
      const nat = live.filter((e) => e.ut.unit.faction === "nature").length;
      const counts = (["idle", "walk", "attack", "rest"] as State[]).map((s) => `${ANIM_LABEL[s]} ${live.filter((e) => e.state === s).length}`).join(" · ");
      hud.textContent = `自然 ${nat} · 人类 ${live.length - nat} · ${counts} · ${Math.round(fpsAvg)} FPS`;
    }
  };
  app.ticker.add(ticker);

  return () => {
    app.canvas.removeEventListener("wheel", onWheel);
    lighting.destroy();
    app.destroy(true, { children: true });
  };
}
