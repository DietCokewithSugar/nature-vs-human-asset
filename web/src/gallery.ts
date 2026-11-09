import {
  ANIM_LABEL, DIRS, DIR_ARROW, DIR_LABEL, ERA_LABEL, FACTION_LABEL, SIZE_LABEL,
  el, fpsFor, framesFor, hasAnim, loadSheet,
  type AnimName, type Dir, type Manifest, type Sheet, type Unit,
} from "./data";
import { bodyWidth, drawFrame, drawGroundMarks, drawZzz } from "./sprites";

interface Card { u: Unit; canvas: HTMLCanvasElement; sheet: Sheet | null; note: HTMLElement }

const state = {
  anim: "walk" as AnimName,
  dir: "south-east" as Dir,
  scale: 3,
  filter: "all" as "all" | "done" | "todo",
  marks: true,
};

export function renderGallery(root: HTMLElement, m: Manifest): () => void {
  const sheetUnits = m.units.filter((u) => !u.demo);
  const demoUnits = m.units.filter((u) => u.demo);
  const done = m.species.filter((s) => s.unitId).length;

  const animTabs = el("div", { class: "seg" });
  const dirPad = el("div", { class: "seg dirs" });
  const scaleSeg = el("div", { class: "seg" });
  const filterSeg = el("div", { class: "seg" });
  const grid = el("div", { class: "grid" });
  const demoGrid = el("div", { class: "grid" });
  const todo = el("div", { class: "todo-list" });

  root.append(
    el("section", { class: "hero" },
      el("div", {},
        el("h1", {}, "素材图鉴"),
        el("p", { class: "muted" },
          `表格物种 ${done} / ${m.species.length} 已生成 · 同一像素比例显示，大小即游戏内真实比例 · 阴影和阵营圈由代码绘制`),
      ),
      el("div", { class: "progress" },
        el("div", { class: "bar" }, el("span", { style: `width:${(done / Math.max(1, m.species.length)) * 100}%` })),
        m.sheetUrl ? el("a", { href: m.sheetUrl, target: "_blank", rel: "noopener" }, "打开物种表 ↗") : null,
      ),
    ),
    el("div", { class: "toolbar" },
      el("label", {}, "动作", animTabs),
      el("label", {}, "方向", dirPad),
      el("label", {}, "放大", scaleSeg),
      el("label", {}, "显示", filterSeg),
    ),
    grid,
    todo,
    demoUnits.length ? el("h2", { class: "section-title" }, "演示单位（不在物种表中）") : "",
    demoGrid,
  );

  const cards: Card[] = [];
  function makeCard(u: Unit, into: HTMLElement) {
    const canvas = el("canvas", { class: "sprite" });
    const note = el("span", { class: "note" });
    const card = el("a", { class: `card ${u.faction}`, href: `#/unit/${u.id}` },
      el("div", { class: "stage" }, canvas),
      el("div", { class: "meta" },
        el("div", { class: "title" }, el("strong", {}, u.displayName), el("span", { class: "en" }, u.englishName)),
        el("div", { class: "chips" },
          el("span", { class: `chip f-${u.faction}` }, FACTION_LABEL[u.faction] ?? u.faction),
          el("span", { class: "chip" }, SIZE_LABEL[u.sizeClass] ?? u.sizeClass),
          el("span", { class: "chip" }, `${u.canvas}px`),
          u.sheet ? el("span", { class: "chip" }, `表第 ${u.sheet.data?.row ?? u.sheet.row} 行`) : null,
        ),
        note,
      ),
    );
    into.append(card);
    const c: Card = { u, canvas, sheet: null, note };
    cards.push(c);
    loadSheet(u).then((s) => { c.sheet = s; sizeCanvas(c); });
  }
  sheetUnits.forEach((u) => makeCard(u, grid));
  demoUnits.forEach((u) => makeCard(u, demoGrid));

  function sizeCanvas(c: Card) {
    const s = c.u.cell * state.scale;
    c.canvas.width = s;
    c.canvas.height = s;
    c.canvas.style.width = `${s}px`;
    c.canvas.style.height = `${s}px`;
  }

  function renderTodo() {
    const pending = m.species.filter((s) => !s.unitId);
    todo.replaceChildren(
      el("h2", { class: "section-title" }, `待生成（${pending.length}）`),
      el("div", { class: "todo-grid" }, ...pending.map((s) =>
        el("div", { class: "todo-item" },
          el("strong", {}, s.name.split(" - ")[0]),
          el("span", { class: "en" }, s.name.split(" - ")[1] ?? ""),
          el("span", { class: "muted small" }, `${ERA_LABEL[s.era] ?? s.era} · ${s.type.split(/[（(]/)[0].trim()} · 第 ${s.row} 行`),
        ))),
    );
  }

  function seg(container: HTMLElement, items: [string, string][], get: () => string, set: (v: string) => void) {
    container.replaceChildren(...items.map(([v, label]) =>
      el("button", {
        class: get() === v ? "on" : "", type: "button", title: label,
        onclick: () => { set(v); seg(container, items, get, set); apply(); },
      }, label)));
  }
  const apply = () => {
    cards.forEach(sizeCanvas);
    grid.style.display = state.filter === "todo" ? "none" : "";
    todo.style.display = state.filter === "done" ? "none" : "";
    demoGrid.style.display = state.filter === "todo" ? "none" : "";
    cards.forEach((c) => {
      c.note.textContent = hasAnim(c.u, state.anim) ? "" : `尚未生成「${ANIM_LABEL[state.anim]}」，显示替代帧`;
    });
  };
  seg(animTabs, (["idle", "walk", "attack", "rest"] as AnimName[]).map((a) => [a, ANIM_LABEL[a]]),
    () => state.anim, (v) => (state.anim = v as AnimName));
  seg(dirPad, DIRS.map((d) => [d, DIR_ARROW[d]]), () => state.dir, (v) => (state.dir = v as Dir));
  dirPad.querySelectorAll("button").forEach((b, i) => b.setAttribute("title", DIR_LABEL[DIRS[i]]));
  seg(scaleSeg, [["2", "2×"], ["3", "3×"], ["4", "4×"]], () => String(state.scale), (v) => (state.scale = +v));
  seg(filterSeg, [["all", "全部"], ["done", "已生成"], ["todo", "待生成"]], () => state.filter,
    (v) => (state.filter = v as typeof state.filter));
  renderTodo();
  apply();

  let raf = 0;
  const t0 = performance.now();
  const tick = () => {
    const t = (performance.now() - t0) / 1000;
    for (const c of cards) {
      if (!c.sheet) continue;
      const ctx = c.canvas.getContext("2d")!;
      const { img, atlas } = c.sheet;
      const frames = framesFor(atlas, state.anim, state.dir);
      if (!frames.length) continue;
      const name = frames[Math.floor(t * fpsFor(c.u, state.anim)) % frames.length];
      const s = state.scale, cell = c.u.cell;
      ctx.clearRect(0, 0, c.canvas.width, c.canvas.height);
      const fx = c.u.anchor.x * cell * s, fy = c.u.anchor.y * cell * s;
      if (state.marks) drawGroundMarks(ctx, fx, fy, bodyWidth(img, atlas, frames[0]), s, c.u.faction);
      drawFrame(ctx, img, atlas, name, 0, 0, s);
      if (state.anim === "rest") drawZzz(ctx, cell * s * 0.62, cell * s * 0.28, t, s);
    }
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}
