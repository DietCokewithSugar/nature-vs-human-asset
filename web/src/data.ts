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
export type AnimName = "idle" | "walk" | "attack" | "rest" | "rotation";
export const ANIM_LABEL: Record<AnimName, string> = {
  idle: "待机", walk: "行走", attack: "攻击", rest: "休息", rotation: "静态",
};
export const SIZE_LABEL: Record<string, string> = { micro: "微型", small: "小型", medium: "中型", large: "大型" };
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
  prompt: Record<string, string | number>;
  animations: { name: string; action: string; frames: number; generated: boolean }[];
  drawnDirections: string[];
  mirrored: Record<string, string>;
  provenance: Record<string, string | number | null>;
  yaml: string;
  files: { png: string; atlas: string };
}
export interface Species { row: number; name: string; era: string; type: string; unitId: string | null }
export interface Tileset { id: string; png: string; json: string; lower: string; upper: string }
export interface Manifest {
  builtAt: string;
  sheetUrl: string;
  sheetHeader: string[];
  units: Unit[];
  species: Species[];
  tilesets: Tileset[];
}
export interface Atlas {
  frames: Record<string, { frame: { x: number; y: number; w: number; h: number } }>;
  animations: Record<string, string[]>;
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
 *  rest = idle played slowly; anything missing falls back to idle, then the static pose. */
export function framesFor(atlas: Atlas, anim: AnimName, dir: Dir): string[] {
  const order: string[] = anim === "rest" ? ["idle", "rotation"] : [anim, "idle", "rotation"];
  for (const a of order) {
    const f = atlas.animations[`${a}_${dir}`];
    if (f?.length) return f;
  }
  return [];
}

export function fpsFor(u: Unit, anim: AnimName): number {
  if (anim === "rest") return Math.max(1, (u.fps.idle ?? 4) * 0.35);
  return u.fps[anim] ?? u.fps.idle ?? 6;
}

/** "已生成" means a real animation exists, not only the fallback. */
export function hasAnim(u: Unit, anim: AnimName): boolean {
  if (anim === "rest") return u.generatedAnimations.includes("idle");
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
