export const DIRS = [
  "south", "south-east", "east", "north-east", "north", "north-west", "west", "south-west",
] as const;
export type Dir = (typeof DIRS)[number];
export const DIR_LABEL: Record<Dir, string> = {
  south: "下", "south-east": "右下", east: "右", "north-east": "右上",
  north: "上", "north-west": "左上", west: "左", "south-west": "左下",
};
export const DIR_ARROW: Record<Dir, string> = {
  south: "↓", "south-east": "↘", east: "→", "north-east": "↗",
  north: "↑", "north-west": "↖", west: "←", "south-west": "↙",
};
export type AnimName = "idle" | "walk" | "attack" | "rest" | "death" | "rotation";
export const ANIM_LABEL: Record<AnimName, string> = {
  idle: "待机", walk: "行走", attack: "攻击", rest: "休息", death: "死亡", rotation: "静态",
};
export const SIZE_LABEL: Record<string, string> = { micro: "微型", small: "小型", medium: "中型", medium_large: "中大型", large: "大型" };
export const FACTION_LABEL: Record<string, string> = { nature: "自然", human: "人类" };
export const ERA_LABEL: Record<string, string> = { ice_age: "冰河时代", modern: "现代" };

export interface Unit {
  id: string;
  displayName: string;
  englishName: string;
  faction: "nature" | "human";
  era: string;
  sizeClass: string;
  habitat: "land" | "water" | "air";
  demo: boolean;
  canvas: number;
  cell: number;
  anchor: { x: number; y: number };
  fps: Record<string, number>;
  generatedAnimations: string[];
  sheet: { tab: string; row: number; name: string; data: Record<string, string> | null } | null;
  prompt: Record<string, string | number | null>;
  animations: { name: string; action: string; frames: number; generated: boolean }[];
  drawnDirections: string[];
  mirrored: Record<string, string>;
  provenance: Record<string, string | number | null>;
  yaml: string;
  files: { png: string; atlas: string; normal?: string; candidates?: string };
  variants: Record<string, string>;
}
export interface Species { row: number; name: string; era: string; type: string; unitId: string | null }
export interface Tileset { id: string; png: string; json: string; normal?: string; lower: string; upper: string }
export interface MapInfo {
  id: string; layout: string; terrain: string; terrainPng: string; terrainNormal?: string;
  objects: string; objectBase: string; overview?: string;
}
export interface Manifest {
  builtAt: string;
  sheetUrl: string;
  sheetHeader: string[];
  units: Unit[];
  species: Species[];
  tilesets: Tileset[];
  props?: { id: string; name_zh: string; png: string; normal?: string; size: number; emissive?: boolean }[];
  maps?: MapInfo[];
}
export interface Atlas {
  frames: Record<string, { frame: { x: number; y: number; w: number; h: number }; duration?: number }>;
  animations: Record<string, string[]>;
  meta: {
    unit: {
      cell: number; cells?: Record<string, number>; foot?: number; anchor: { x: number; y: number };
      hit?: Record<string, number>; variants?: Record<string, string>; fps?: Record<string, number>;
    };
  };
}
export interface Sheet { img: HTMLImageElement; atlas: Atlas }

let manifestP: Promise<Manifest> | null = null;
export function loadManifest(): Promise<Manifest> {
  manifestP ??= fetch("data/manifest.json").then((r) => r.json());
  return manifestP;
}

const sheetCache = new Map<string, Promise<Sheet>>();
export function loadSheet(u: Unit): Promise<Sheet> {
  if (!sheetCache.has(u.id)) {
    sheetCache.set(u.id, (async () => {
      const [atlas, img] = await Promise.all([
        fetch(u.files.atlas).then((r) => r.json() as Promise<Atlas>),
        new Promise<HTMLImageElement>((res, rej) => {
          const i = new Image();
          i.onload = () => res(i);
          i.onerror = rej;
          i.src = u.files.png;
        }),
      ]);
      return { img, atlas };
    })());
  }
  return sheetCache.get(u.id)!;
}

/** Frame names for an animation+direction, with the fallbacks the game uses:
 *  rest = idle played slowly; attack uses the selected attack version when that
 *  direction exists; anything missing falls back to idle, then the static pose. */
export function framesFor(atlas: Atlas, anim: AnimName, dir: Dir, attack: AttackVersion = "attack"): string[] {
  return resolve(atlas, anim, dir, attack).frames;
}

export type AttackVersion = "attack" | "attackkf" | "attackhand" | "attackcombo";
export const ATTACK_LABEL: Record<AttackVersion, string> = {
  attack: "PixelLab 原版", attackkf: "PixelLab 关键帧", attackhand: "AI 手改", attackcombo: "结合版",
};
export const ATTACK_NOTE: Record<AttackVersion, string> = {
  attack: "PixelLab v3 按文字一次生成，匀速播放",
  attackkf: "先用 Pixen 编辑出「蓄力」和「出击」两个关键姿势，再由 v3 补中间帧，按蓄力-出击-停顿-收招重排节奏",
  attackhand: "在 PixelLab 原图上逐像素改出关键姿势（aseprite-ai-artist 的文本网格方法 + 攻击规则），5 个方向，不消耗生成次数",
  attackcombo: "AI 画蓄力和出击两个关键姿势，AI 手改负责统一配色、对齐、残影、过渡和节奏；背面沿用手改（当前默认，没有结合版的单位自动用 AI 手改）",
};

export interface Resolved { key: string; frames: string[]; fallback: boolean }
export function resolve(atlas: Atlas, anim: AnimName, dir: Dir, attack: AttackVersion = "attack"): Resolved {
  const order: string[] = anim === "rest" ? ["idle", "rotation"]
    : anim === "death" ? ["death", "rotation"]
    : anim === "attack" ? [attack, "attackcombo", "attackhand", "attackkf", "attack", "idle", "rotation"] : [anim, "idle", "rotation"];
  for (const a of order) {
    const f = atlas.animations[`${a}_${dir}`];
    if (f?.length) return { key: a, frames: f, fallback: a !== order[0] };
  }
  return { key: "rotation", frames: [], fallback: true };
}

/** Per-frame durations (ms). With `feel` off everything plays evenly (the old
 *  behaviour). With it on, authored variant timings are used, and the original
 *  attack is re-timed around its hit frame: held wind-up, fast strike, held hit. */
export function durations(atlas: Atlas, key: string, dir: Dir, frames: string[], fps: number, feel: boolean): number[] {
  return timed(atlas, key, dir, frames, fps, feel);
}

const AUTHORED = new Set(["attackkf", "attackhand", "attackcombo", "death"]);
function timed(atlas: Atlas, key: string, dir: Dir, frames: string[], fps: number, feel: boolean): number[] {
  const even = frames.map(() => 1000 / fps);
  if (key === "death") return frames.map((f) => atlas.frames[f]?.duration ?? 1000 / fps);   // always authored
  if (!feel) return even;
  if (AUTHORED.has(key)) return frames.map((f) => atlas.frames[f]?.duration ?? 1000 / fps);
  if (key === "attack") {
    const h = hitIndex(atlas, key, dir, frames.length);
    return frames.map((_, i) => (i === 0 ? 120 : i < h - 1 ? 110 : i === h - 1 ? 50 : i === h ? 160 : i === frames.length - 1 ? 120 : 90));
  }
  return even;
}

export function hitIndex(atlas: Atlas, key: string, dir: Dir, n: number): number {
  const h = atlas.meta?.unit?.hit?.[`${key}_${dir}`];
  return h !== undefined && h < n ? h : Math.floor(n / 2);
}

/** Frame index at time t (ms) for given durations; loop or clamp to last. */
export function frameAt(durs: number[], t: number, loop = true): number {
  const total = durs.reduce((a, b) => a + b, 0) || 1;
  let x = loop ? ((t % total) + total) % total : Math.min(t, total - 1);
  for (let i = 0; i < durs.length; i++) {
    if (x < durs[i]) return i;
    x -= durs[i];
  }
  return durs.length - 1;
}

/** Viewer preferences shared by the gallery, unit page and lab. */
export const prefs = (() => {
  const def = { attack: "attackcombo" as AttackVersion, feel: true, labMap: "hd" as "ice_age" | "hd" | "demo" };
  try {
    // key bumped: the default attack version changed to the hand-edited one
    return { ...def, ...JSON.parse(localStorage.getItem("nvh-prefs-v3") || "{}") } as typeof def;
  } catch {
    return def;
  }
})();
export function savePrefs() {
  try { localStorage.setItem("nvh-prefs-v3", JSON.stringify(prefs)); } catch { /* private mode */ }
}

export function fpsFor(u: Unit, anim: AnimName): number {
  if (anim === "rest") return Math.max(1, (u.fps.idle ?? 4) * 0.35);
  return u.fps[anim] ?? u.fps.idle ?? 6;
}

/** "已生成" means a real animation exists, not only the fallback. */
export function hasAnim(u: Unit, anim: AnimName): boolean {
  if (anim === "rest") return u.generatedAnimations.includes("idle");
  if (anim === "attack") return ["attack", "attackhand", "attackkf", "attackcombo"].some((a) => u.generatedAnimations.includes(a));
  return u.generatedAnimations.includes(anim);
}

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K, props: Record<string, unknown> = {}, ...children: (Node | string | null | undefined)[]
): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") e.className = String(v);
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v as EventListener);
    else if (k === "html") e.innerHTML = String(v);
    else e.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children) if (c !== null && c !== undefined) e.append(c);
  return e;
}
