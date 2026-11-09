import {
  ANIM_LABEL, ATTACK_LABEL, ATTACK_NOTE, DIRS, DIR_ARROW, DIR_LABEL, ERA_LABEL, FACTION_LABEL, SIZE_LABEL,
  durations, el, fpsFor, frameAt, hasAnim, loadSheet, prefs, resolve, savePrefs,
  type AnimName, type AttackVersion, type Dir, type Manifest, type Sheet, type Unit,
} from "./data";
import { bodyWidth, drawFrameAt, drawGroundMarks, drawZzz } from "./sprites";

interface Card { u: Unit; canvas: HTMLCanvasElement; sheet: Sheet | null; note: HTMLElement; box: number }

const state = {
  anim: "attack" as AnimName,
  dir: "east" as Dir,
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
  const attackSeg = el("div", { class: "seg" });
  const feelBox = el("input", { type: "checkbox" }) as HTMLInputElement;
  const attackNote = el("p", { class: "muted small attack-note" });
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
      el("div", { class: "toolbar-row" },
        el("label", {}, "攻击版本", attackSeg),
        el("label", { class: "check inline", title: "关闭：所有帧匀速循环（旧效果）。开启：蓄力停顿、快速出击、命中停顿、收招。" },
          feelBox, "攻击节奏优化"),
      ),
      attackNote,
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
    const c: Card = { u, canvas, sheet: null, note, box: u.cell };
    cards.push(c);
    loadSheet(u).then((s) => { c.sheet = s; apply(); });
  }
  sheetUnits.forEach((u) => makeCard(u, grid));
  demoUnits.forEach((u) => makeCard(u, demoGrid));

  function sizeCanvas(c: Card) {
    // attack variants lunge outside the base cell: give the canvas room for them
    const cells = c.sheet?.atlas.meta.unit.cells ?? {};
    c.box = state.anim === "attack" && prefs.attack !== "attack" && cells[prefs.attack] ? cells[prefs.attack] : c.u.cell;
    const s = c.box * state.scale;
    if (c.canvas.width !== s) {
      c.canvas.width = s;
      c.canvas.height = s;
      c.canvas.style.width = `${s}px`;
    }
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
  function apply() {
    cards.forEach(sizeCanvas);
    grid.style.display = state.filter === "todo" ? "none" : "";
    todo.style.display = state.filter === "done" ? "none" : "";
    demoGrid.style.display = state.filter === "todo" ? "none" : "";
    attackNote.textContent = ATTACK_NOTE[prefs.attack];
    cards.forEach((c) => {
      let note = hasAnim(c.u, state.anim) ? "" : `尚未生成「${ANIM_LABEL[state.anim]}」，显示替代帧`;
      if (!note && c.sheet && state.anim === "attack" && prefs.attack !== "attack") {
        const r = resolve(c.sheet.atlas, "attack", state.dir, prefs.attack);
        if (r.key !== prefs.attack) note = c.u.variants?.[prefs.attack] ? "这个方向没有该版本，显示原版" : "该素材没有这个攻击版本，显示原版";
      }
      c.note.textContent = note;
    });
  }
  seg(animTabs, (["idle", "walk", "attack", "rest"] as AnimName[]).map((a) => [a, ANIM_LABEL[a]]),
    () => state.anim, (v) => (state.anim = v as AnimName));
  seg(dirPad, DIRS.map((d) => [d, DIR_ARROW[d]]), () => state.dir, (v) => (state.dir = v as Dir));
  dirPad.querySelectorAll("button").forEach((b, i) => b.setAttribute("title", DIR_LABEL[DIRS[i]]));
  seg(scaleSeg, [["2", "2×"], ["3", "3×"], ["4", "4×"]], () => String(state.scale), (v) => (state.scale = +v));
  seg(filterSeg, [["all", "全部"], ["done", "已生成"], ["todo", "待生成"]], () => state.filter,
    (v) => (state.filter = v as typeof state.filter));
  seg(attackSeg, (Object.keys(ATTACK_LABEL) as AttackVersion[]).map((a) => [a, ATTACK_LABEL[a]]),
    () => prefs.attack, (v) => { prefs.attack = v as AttackVersion; savePrefs(); if (state.anim !== "attack") state.anim = "attack"; seg(animTabs, (["idle", "walk", "attack", "rest"] as AnimName[]).map((a) => [a, ANIM_LABEL[a]]), () => state.anim, (x) => (state.anim = x as AnimName)); });
  feelBox.checked = prefs.feel;
  feelBox.addEventListener("change", () => { prefs.feel = feelBox.checked; savePrefs(); });
  renderTodo();
  apply();

  let raf = 0;
  const t0 = performance.now();
  const tick = () => {
    const t = performance.now() - t0;
    for (const c of cards) {
      if (!c.sheet) continue;
      const ctx = c.canvas.getContext("2d")!;
      const { img, atlas } = c.sheet;
      const r = resolve(atlas, state.anim, state.dir, prefs.attack);
      if (!r.frames.length) continue;
      const durs = durations(atlas, r.key, state.dir, r.frames, fpsFor(c.u, state.anim), prefs.feel);
      const name = r.frames[frameAt(durs, t)];
      const s = state.scale;
      ctx.clearRect(0, 0, c.canvas.width, c.canvas.height);
      const cx = c.canvas.width / 2, cy = c.canvas.height / 2;
      const foot = (atlas.meta.unit.foot ?? c.u.cell * (c.u.anchor.y - 0.5)) * s;
      if (state.marks) drawGroundMarks(ctx, cx, cy + foot, bodyWidth(img, atlas, atlas.animations[`rotation_${state.dir}`]?.[0] ?? r.frames[0]), s, c.u.faction);
      drawFrameAt(ctx, img, atlas, name, cx, cy, s);
      if (state.anim === "rest") drawZzz(ctx, cx + c.u.cell * s * 0.12, cy - c.u.cell * s * 0.22, t / 1000, s);
    }
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}
