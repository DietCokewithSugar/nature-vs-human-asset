import {
  Application, Assets, Container, Graphics, Rectangle, Sprite, Text, Texture, TextureSource,
} from "pixi.js";
import {
  ANIM_LABEL, DIRS, el, fpsFor, framesFor, loadSheet,
  type AnimName, type Atlas, type Dir, type Manifest, type Unit,
} from "./data";
import { bodyWidth, drawFrame } from "./sprites";

TextureSource.defaultOptions.scaleMode = "nearest";

const TILE = 32;
const MAP_W = 44;
const MAP_H = 28;
type Terrain = "snow" | "tundra" | "water" | "mud";
const TERRAIN_SET: Record<Exclude<Terrain, "snow">, string> = {
  tundra: "ice_snow_tundra", water: "ice_snow_water", mud: "ice_snow_mud",
};
const FALLBACK_COLOR: Record<Terrain, number> = { snow: 0xdfe8f2, tundra: 0x7d7a4f, water: 0x1d5fa8, mud: 0x6b4423 };
type State = "idle" | "walk" | "attack" | "rest";
type Mode = "auto" | State;
const STATE_LABEL: Record<Mode, string> = { auto: "自动", idle: "待机", walk: "行走", attack: "攻击", rest: "休息" };

const SIZE_STATS: Record<string, { hp: number; dmg: number; speed: number; radius: number }> = {
  micro: { hp: 30, dmg: 3, speed: 38, radius: 6 },
  small: { hp: 60, dmg: 6, speed: 30, radius: 8 },
  medium: { hp: 120, dmg: 16, speed: 32, radius: 10 },
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
        // never let two different non-snow terrains touch: each cell needs one tileset
        let ok = true;
        for (let dy = -1; dy <= 1 && ok; dy++) for (let dx = -1; dx <= 1; dx++) {
          const n = at(x + dx, y + dy);
          if (n !== "snow" && n !== t) { ok = false; break; }
        }
        if (ok) v[y * W + x] = t;
      }
  };
  paint(W * 0.5, H * 0.72, 5.5, "water");
  paint(W * 0.56, H * 0.62, 3.5, "water");
  paint(W * 0.5, H * 0.2, 2.5, "water");
  for (let i = 0; i < 6; i++) paint(3 + r() * W * 0.35, 2 + r() * (H - 4), 2.5 + r() * 3.5, "tundra");
  for (let i = 0; i < 4; i++) paint(W * 0.66 + r() * W * 0.28, 3 + r() * (H - 6), 2 + r() * 3, "mud");
  return v;
}

interface TileLookup { textures: Map<string, Texture>; ok: boolean }
async function loadTilesets(m: Manifest): Promise<Record<string, TileLookup>> {
  const out: Record<string, TileLookup> = {};
  for (const ts of m.tilesets) {
    try {
      const [meta, tex] = await Promise.all([fetch(ts.json).then((r) => r.json()), Assets.load<Texture>(ts.png)]);
      const map = new Map<string, Texture>();
      for (const t of meta.tiles as { x: number; y: number; corners: Record<string, string> }[]) {
        const c = t.corners;
        const key = ["NW", "NE", "SW", "SE"].map((k) => (c[k] === "lower" ? "L" : "U")).join("");
        if (!map.has(key)) map.set(key, new Texture({ source: tex.source, frame: new Rectangle(t.x, t.y, TILE, TILE) }));
      }
      out[ts.id] = { textures: map, ok: true };
    } catch {
      out[ts.id] = { textures: new Map(), ok: false };
    }
  }
  return out;
}

function drawTerrain(layer: Container, v: Terrain[], sets: Record<string, TileLookup>) {
  const W = MAP_W + 1;
  const anySet = Object.values(sets).find((s) => s.ok);
  for (let y = 0; y < MAP_H; y++)
    for (let x = 0; x < MAP_W; x++) {
      const c = [v[y * W + x], v[y * W + x + 1], v[(y + 1) * W + x], v[(y + 1) * W + x + 1]];
      const other = c.find((t) => t !== "snow") as Exclude<Terrain, "snow"> | undefined;
      const set = other ? sets[TERRAIN_SET[other]] : anySet;
      const key = c.map((t) => (other && t === other ? "L" : "U")).join("");
      const tex = set?.textures.get(key);
      if (tex) {
        const s = new Sprite(tex);
        s.position.set(x * TILE, y * TILE);
        layer.addChild(s);
      } else {
        const g = new Graphics().rect(x * TILE, y * TILE, TILE, TILE).fill(FALLBACK_COLOR[other ?? "snow"]);
        layer.addChild(g);
      }
    }
}

// ---------------------------------------------------------------- units
interface UnitTex { unit: Unit; atlas: Atlas; frames: Map<string, Texture>; bodyW: number; thumb: string }

async function loadUnitTex(u: Unit): Promise<UnitTex> {
  const [sheet, base] = await Promise.all([loadSheet(u), Assets.load<Texture>(u.files.png)]);
  const frames = new Map<string, Texture>();
  for (const [name, f] of Object.entries(sheet.atlas.frames)) {
    frames.set(name, new Texture({ source: base.source, frame: new Rectangle(f.frame.x, f.frame.y, f.frame.w, f.frame.h) }));
  }
  const rot = sheet.atlas.animations["rotation_south-east"]?.[0] ?? Object.keys(sheet.atlas.frames)[0];
  const c = document.createElement("canvas");
  const s = Math.max(1, Math.floor(48 / u.cell)) || 1;
  c.width = c.height = u.cell * s;
  drawFrame(c.getContext("2d")!, sheet.img, sheet.atlas, rot, 0, 0, s);
  return { unit: u, atlas: sheet.atlas, frames, bodyW: bodyWidth(sheet.img, sheet.atlas, rot), thumb: c.toDataURL() };
}

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
  ut: UnitTex; root: Container; sprite: Sprite; ring: Graphics; hp: Graphics; zzz: Sprite;
  x: number; y: number; dir: Dir; state: State; force: Mode; t: number; animT: number;
  tx: number; ty: number; wait: number; target: Ent | null; hpNow: number; hpMax: number;
  cooldown: number; flash: number; dead: number; restRoll: number;
}

export async function renderLab(root: HTMLElement, m: Manifest): Promise<() => void> {
  const host = el("div", { class: "lab-canvas" });
  const side = el("aside", { class: "lab-side" });
  const hud = el("div", { class: "lab-hud" });
  root.append(el("section", { class: "lab" }, el("div", { class: "lab-main" }, host, hud), side));
  host.append(el("p", { class: "muted pad" }, "加载中…"));

  const app = new Application();
  await app.init({ resizeTo: host, background: "#11151c", antialias: false, roundPixels: true, autoDensity: true, resolution: window.devicePixelRatio || 1 });
  host.replaceChildren(app.canvas);

  const world = new Container();
  const ground = new Container();
  const actors = new Container();
  actors.sortableChildren = true;
  const night = new Graphics().rect(0, 0, MAP_W * TILE, MAP_H * TILE).fill(0xffffff);
  night.blendMode = "multiply";
  world.addChild(ground, actors, night);
  app.stage.addChild(world);

  const terrain = buildTerrain(7);
  const [sets, uts] = await Promise.all([loadTilesets(m), Promise.all(m.units.map(loadUnitTex))]);
  drawTerrain(ground, terrain, sets);

  const zText = new Text({ text: "Zz", style: { fontFamily: "Silkscreen, monospace", fontSize: 24, fill: "#ffffff", stroke: { color: "#1b1f2a", width: 6 } } });
  const zTex = app.renderer.generateTexture(zText);

  const terrainAt = (px: number, py: number): Terrain => {
    const x = Math.round(px / TILE), y = Math.round(py / TILE);
    if (x < 0 || y < 0 || x > MAP_W || y > MAP_H) return "snow";
    return terrain[y * (MAP_W + 1) + x];
  };
  const walkable = (u: Unit, px: number, py: number) => {
    if (px < 8 || py < 12 || px > MAP_W * TILE - 8 || py > MAP_H * TILE - 4) return false;
    if (u.habitat === "air") return true;
    const t = terrainAt(px, py);
    return u.habitat === "water" ? t === "water" : t !== "water";
  };

  // ---------------- state / controls
  const ui = {
    mode: "auto" as Mode, spawnId: uts.find((x) => !x.unit.demo)?.unit.id ?? uts[0]?.unit.id,
    hour: 10, autoTime: true, immortal: false, rings: true, bars: true, speed: 1,
    selected: null as Ent | null, zoom: 2,
  };
  const ents: Ent[] = [];

  function spawn(ut: UnitTex, x: number, y: number): Ent | null {
    const u = ut.unit;
    for (let i = 0; i < 30 && !walkable(u, x, y); i++) { x += (Math.random() - 0.5) * 60; y += (Math.random() - 0.5) * 60; }
    if (!walkable(u, x, y)) return null;
    const st = SIZE_STATS[u.sizeClass] ?? SIZE_STATS.medium;
    const rootC = new Container();
    const rx = Math.max(5, ut.bodyW * 0.42), ry = Math.max(2, ut.bodyW * 0.16);
    const shadow = new Graphics().ellipse(0, 0, rx, ry).fill({ color: 0x19192d, alpha: 0.32 });
    const ring = new Graphics().ellipse(0, 0, rx + 1, ry + 0.6).stroke({ color: u.faction === "nature" ? 0x63c74d : 0xf77622, width: 1 });
    const sprite = new Sprite();
    sprite.anchor.set(u.anchor.x, u.anchor.y);
    const hp = new Graphics();
    const zzz = new Sprite(zTex);
    zzz.scale.set(0.25);
    zzz.visible = false;
    rootC.addChild(shadow, ring, sprite, hp, zzz);
    actors.addChild(rootC);
    const e: Ent = {
      ut, root: rootC, sprite, ring, hp, zzz, x, y, dir: DIRS[Math.floor(Math.random() * 8)], state: "idle",
      force: "auto", t: 0, animT: Math.random() * 10, tx: x, ty: y, wait: Math.random() * 2,
      target: null, hpNow: st.hp, hpMax: st.hp, cooldown: 0, flash: 0, dead: 0, restRoll: Math.random(),
    };
    rootC.eventMode = "static";
    rootC.cursor = "pointer";
    rootC.on("pointertap", (ev) => { ev.stopPropagation(); select(e); });
    ents.push(e);
    return e;
  }

  function clearAll() {
    for (const e of ents) e.root.destroy({ children: true });
    ents.length = 0;
    select(null);
  }

  function randomSpot(u: Unit, side?: "nature" | "human") {
    for (let i = 0; i < 200; i++) {
      const fx = side === "nature" ? 0.05 + Math.random() * 0.45 : side === "human" ? 0.5 + Math.random() * 0.45 : Math.random();
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
  function enemyNear(e: Ent, radius: number): Ent | null {
    let best: Ent | null = null, bd = radius;
    for (const o of ents) {
      if (o === e || o.dead || o.ut.unit.faction === e.ut.unit.faction) continue;
      if (e.ut.unit.habitat === "water" && o.ut.unit.habitat !== "water" && terrainAt(o.x, o.y) !== "water") continue;
      const d = Math.hypot(o.x - e.x, o.y - e.y);
      if (d < bd) { bd = d; best = o; }
    }
    return best;
  }
  function pickWander(e: Ent) {
    for (let i = 0; i < 12; i++) {
      const a = Math.random() * Math.PI * 2, d = 40 + Math.random() * 140;
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

  function step(e: Ent, dt: number) {
    const u = e.ut.unit;
    const st = SIZE_STATS[u.sizeClass] ?? SIZE_STATS.medium;
    if (e.dead) {
      e.dead += dt;
      e.root.alpha = Math.max(0, 1 - e.dead);
      return;
    }
    e.cooldown -= dt;
    e.flash = Math.max(0, e.flash - dt);
    const mode = e.force !== "auto" ? e.force : ui.mode;

    if (mode === "idle" || mode === "rest") { e.state = mode; return; }
    if (mode === "walk") {
      e.state = "walk";
      if (moveToward(e, e.tx, e.ty, dt, st.speed)) pickWander(e);
      return;
    }
    if (mode === "attack") {
      // show the attack animation; hit whoever happens to be in reach
      e.state = "attack";
      const t = enemyNear(e, st.radius + 18);
      if (t) e.dir = dirFromVec(t.x - e.x, t.y - e.y);
      if (t && e.cooldown <= 0) { hit(e, t, st.dmg); e.cooldown = 0.9; }
      return;
    }
    // ---- auto
    if (wantsRest(e) && !(e.target && !e.target.dead)) { e.state = "rest"; return; }
    if (!e.target || e.target.dead || Math.hypot(e.target.x - e.x, e.target.y - e.y) > 220) e.target = enemyNear(e, 150);
    if (e.target) {
      const t = e.target, tst = SIZE_STATS[t.ut.unit.sizeClass] ?? SIZE_STATS.medium;
      const reach = st.radius + tst.radius + 4;
      if (Math.hypot(t.x - e.x, t.y - e.y) > reach) {
        e.state = "walk";
        moveToward(e, t.x, t.y, dt, st.speed * 1.25);
      } else {
        e.state = "attack";
        e.dir = dirFromVec(t.x - e.x, t.y - e.y);
        if (e.cooldown <= 0) { hit(e, t, st.dmg); e.cooldown = 0.9; }
      }
      return;
    }
    if (e.wait > 0) { e.state = "idle"; e.wait -= dt; return; }
    e.state = "walk";
    if (e.tx === e.x && e.ty === e.y) pickWander(e);
    if (moveToward(e, e.tx, e.ty, dt, st.speed)) { e.wait = 1 + Math.random() * 3; e.tx = e.x; e.ty = e.y; }
  }

  function hit(a: Ent, b: Ent, dmg: number) {
    b.flash = 0.18;
    if (ui.immortal) return;
    b.hpNow -= dmg * (0.75 + Math.random() * 0.5);
    if (b.hpNow <= 0) { b.hpNow = 0; b.dead = 0.001; if (ui.selected === b) select(null); }
    if (!b.target) b.target = a;
  }

  function draw(e: Ent) {
    const u = e.ut.unit;
    const anim: AnimName = e.state;
    const frames = framesFor(e.ut.atlas, anim, e.dir);
    if (frames.length) {
      const name = frames[Math.floor(e.animT * fpsFor(u, anim)) % frames.length];
      const tex = e.ut.frames.get(name);
      if (tex && e.sprite.texture !== tex) e.sprite.texture = tex;
    }
    const shake = e.flash > 0 ? (Math.random() - 0.5) * 2 : 0;
    e.root.position.set(Math.round(e.x + shake), Math.round(e.y));
    e.root.zIndex = e.y;
    e.sprite.tint = e.flash > 0 ? 0xff9a9a : 0xffffff;
    e.ring.visible = ui.rings;
    const top = -u.anchor.y * u.cell + (u.cell - u.canvas) / 2 + 2;
    e.zzz.visible = e.state === "rest";
    if (e.zzz.visible) e.zzz.position.set(4, top - 6 + Math.sin(e.animT * 2) * 1.5);
    e.hp.clear();
    if (ui.bars && (e.hpNow < e.hpMax || ui.selected === e)) {
      const w = Math.max(12, Math.min(28, u.canvas * 0.45));
      e.hp.rect(-w / 2, top - 3, w, 2).fill(0x26162a).rect(-w / 2, top - 3, (w * e.hpNow) / e.hpMax, 2).fill(0xe43b44);
    }
    if (ui.selected === e) e.hp.ellipse(0, 0, 16, 6).stroke({ color: 0xffffff, width: 1, alpha: 0.9 });
  }

  // ---------------- day / night tint (code only; no night art)
  const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
  const mix = (c1: number, c2: number, t: number) => {
    const r = Math.round(lerp((c1 >> 16) & 255, (c2 >> 16) & 255, t));
    const g = Math.round(lerp((c1 >> 8) & 255, (c2 >> 8) & 255, t));
    const b = Math.round(lerp(c1 & 255, c2 & 255, t));
    return (r << 16) | (g << 8) | b;
  };
  function tintFor(h: number) {
    const DAY = 0xffffff, DUSK = 0xffc48f, NIGHT = 0x5664a6;
    if (h >= 7 && h < 17) return DAY;
    if (h >= 17 && h < 19) return mix(DAY, DUSK, (h - 17) / 2);
    if (h >= 19 && h < 20) return mix(DUSK, NIGHT, h - 19);
    if (h >= 5 && h < 7) return mix(NIGHT, DAY, (h - 5) / 2);
    return NIGHT;
  }

  // ---------------- camera
  const view = { x: 0, y: 0 };
  function applyCamera() {
    world.scale.set(ui.zoom);
    const vw = app.screen.width, vh = app.screen.height;
    const mw = MAP_W * TILE * ui.zoom, mh = MAP_H * TILE * ui.zoom;
    view.x = mw < vw ? (vw - mw) / 2 : Math.min(0, Math.max(vw - mw, view.x));
    view.y = mh < vh ? (vh - mh) / 2 : Math.min(0, Math.max(vh - mh, view.y));
    world.position.set(Math.round(view.x), Math.round(view.y));
  }
  function centerOn(wx: number, wy: number) {
    view.x = app.screen.width / 2 - wx * ui.zoom;
    view.y = app.screen.height / 2 - wy * ui.zoom;
    applyCamera();
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
  const endDrag = (ev: { global: { x: number; y: number } }) => {
    if (drag && !drag.moved) {
      const wx = (ev.global.x - view.x) / ui.zoom, wy = (ev.global.y - view.y) / ui.zoom;
      const ut = uts.find((x) => x.unit.id === ui.spawnId);
      if (ut) select(spawn(ut, wx, wy));
    }
    drag = null;
  };
  app.stage.on("pointerup", endDrag);
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
  const onResize = () => applyCamera();
  window.addEventListener("resize", onResize);

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
        el("button", { type: "button", class: e.force === s ? "on" : "", onclick: () => { e.force = s; renderSelected(); } }, STATE_LABEL[s]))),
      el("div", { class: "row" },
        el("a", { href: `#/unit/${u.id}`, class: "small" }, "查看素材与配置 →"),
        el("button", { type: "button", class: "ghost small", onclick: () => { e.dead = 0.001; select(null); } }, "移除")),
    );
  }

  function renderSide() {
    const seg = (items: [string, string][], cur: string, set: (v: string) => void, cls = "seg wrap") =>
      el("div", { class: cls }, ...items.map(([v, l]) => el("button", { type: "button", class: cur === v ? "on" : "", onclick: () => { set(v); renderSide(); } }, l)));
    side.replaceChildren(
      el("div", { class: "panel" },
        el("h3", {}, "全体状态"),
        seg((["auto", "idle", "walk", "attack", "rest"] as Mode[]).map((s) => [s, STATE_LABEL[s]]), ui.mode, (v) => (ui.mode = v as Mode)),
        el("p", { class: "muted small" }, "自动：闲逛、追击并攻击敌对阵营、按物种表的休眠时段休息。其他选项强制所有单位播放该动作。"),
      ),
      el("div", { class: "panel" },
        el("h3", {}, "放置单位"),
        el("p", { class: "muted small" }, "选中后点击地图放置；拖动平移，滚轮缩放。"),
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
        el("h3", {}, "时间"),
        el("input", { type: "range", min: "0", max: "23.9", step: "0.1", value: String(ui.hour),
          oninput: (ev: Event) => { ui.hour = +(ev.target as HTMLInputElement).value; ui.autoTime = false; renderClock(); } }),
        el("div", { class: "row" }, clock,
          el("label", { class: "check" }, el("input", { type: "checkbox", checked: ui.autoTime, onchange: (ev: Event) => { ui.autoTime = (ev.target as HTMLInputElement).checked; } }), "自动流逝")),
      ),
      el("div", { class: "panel" },
        el("h3", {}, "显示"),
        el("label", { class: "check" }, el("input", { type: "checkbox", checked: ui.rings, onchange: (ev: Event) => { ui.rings = (ev.target as HTMLInputElement).checked; } }), "阵营圈"),
        el("label", { class: "check" }, el("input", { type: "checkbox", checked: ui.bars, onchange: (ev: Event) => { ui.bars = (ev.target as HTMLInputElement).checked; } }), "血条"),
        el("label", { class: "check" }, el("input", { type: "checkbox", checked: ui.immortal, onchange: (ev: Event) => { ui.immortal = (ev.target as HTMLInputElement).checked; } }), "单位不会死亡"),
        el("div", { class: "row" }, el("span", { class: "small muted" }, "缩放"),
          seg([["1", "1×"], ["2", "2×"], ["3", "3×"], ["4", "4×"]], String(ui.zoom), (v) => { ui.zoom = +v; centerOn(MAP_W * TILE / 2, MAP_H * TILE / 2); }, "seg")),
        el("div", { class: "row" }, el("span", { class: "small muted" }, "速度"),
          seg([["0.5", "0.5×"], ["1", "1×"], ["2", "2×"]], String(ui.speed), (v) => (ui.speed = +v), "seg")),
      ),
      selBox,
    );
    renderSelected();
  }
  const clock = el("span", { class: "clock" });
  const renderClock = () => {
    const h = Math.floor(ui.hour), mm = Math.floor((ui.hour - h) * 60);
    clock.textContent = `${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")} ${isNight() ? "夜" : "昼"}`;
  };

  renderSide();
  renderClock();
  battle(60);
  ui.zoom = 2;
  centerOn(MAP_W * TILE / 2, MAP_H * TILE / 2);

  let fpsAvg = 60, hudT = 0;
  const ticker = (tk: { deltaMS: number }) => {
    const dt = Math.min(0.05, tk.deltaMS / 1000) * ui.speed;
    if (ui.autoTime) { ui.hour = (ui.hour + dt * 0.25) % 24; }
    night.tint = tintFor(ui.hour);
    for (const e of ents) { e.animT += dt; step(e, dt); draw(e); }
    for (let i = ents.length - 1; i >= 0; i--) if (ents[i].dead > 1) { ents[i].root.destroy({ children: true }); ents.splice(i, 1); }
    fpsAvg = fpsAvg * 0.95 + (1000 / Math.max(1, tk.deltaMS)) * 0.05;
    hudT += tk.deltaMS;
    if (hudT > 300) {
      hudT = 0;
      renderClock();
      const nat = ents.filter((e) => e.ut.unit.faction === "nature" && !e.dead).length;
      const hum = ents.filter((e) => e.ut.unit.faction === "human" && !e.dead).length;
      const counts = (["idle", "walk", "attack", "rest"] as State[]).map((s) => `${ANIM_LABEL[s]} ${ents.filter((e) => e.state === s && !e.dead).length}`).join(" · ");
      hud.textContent = `自然 ${nat} · 人类 ${hum} · ${counts} · ${Math.round(fpsAvg)} FPS`;
    }
  };
  app.ticker.add(ticker);

  return () => {
    window.removeEventListener("resize", onResize);
    app.canvas.removeEventListener("wheel", onWheel);
    app.destroy(true, { children: true });
  };
}
