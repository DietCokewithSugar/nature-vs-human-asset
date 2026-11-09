import {
  ANIM_LABEL, ATTACK_LABEL, ATTACK_NOTE, DIRS, DIR_ARROW, DIR_LABEL, ERA_LABEL, FACTION_LABEL, SIZE_LABEL,
  durations, el, fpsFor, frameAt, hasAnim, hitIndex, loadSheet, prefs, resolve, savePrefs,
  type AnimName, type AttackVersion, type Dir, type Manifest, type Sheet,
} from "./data";
import { bodyWidth, drawFrame, drawFrameAt, drawGroundMarks, drawZzz } from "./sprites";
import { LitFrames, loadImage, type ViewMode } from "./light2d";

const HABITAT: Record<string, string> = { land: "陆地", water: "水域", air: "空中" };

export function renderUnit(root: HTMLElement, m: Manifest, id: string): () => void {
  const u = m.units.find((x) => x.id === id);
  if (!u) {
    root.append(el("p", {}, "找不到这个素材。"), el("a", { href: "#/" }, "← 返回图鉴"));
    return () => {};
  }
  const st = {
    anim: (hasAnim(u, "attack") ? "attack" : "idle") as AnimName, dir: "east" as Dir, speed: 1, marks: true,
    view: "color" as ViewMode, lightZ: 18, mouse: null as null | { x: number; y: number },
  };
  const maxCell = u.cell;
  let box = u.cell;
  const SCALE = Math.max(3, Math.min(8, Math.floor(360 / u.cell)));

  const big = el("canvas", { class: "sprite big" });
  const sizeBig = () => {
    const cells = sheet?.atlas.meta.unit.cells ?? {};
    box = Math.max(u.cell, cells.attackkf ?? 0, cells.attackhand ?? 0, maxCell);
    big.width = big.height = box * SCALE;
    big.style.width = `${box * SCALE}px`;
  };
  big.width = big.height = u.cell * SCALE;
  big.style.width = `${u.cell * SCALE}px`;
  big.addEventListener("pointermove", (e) => {
    const r = big.getBoundingClientRect();
    const k = big.width / r.width;
    st.mouse = { x: ((e.clientX - r.left) * k - big.width / 2) / SCALE, y: ((e.clientY - r.top) * k - big.height / 2) / SCALE };
  });
  big.addEventListener("pointerleave", () => (st.mouse = null));
  const attackSeg = el("div", { class: "seg wrap" });
  const attackNote = el("p", { class: "muted small" });
  const viewSeg = el("div", { class: "seg wrap" });

  const animSeg = el("div", { class: "seg" });
  const dirGrid = el("div", { class: "dirgrid" });
  const strip = el("div", { class: "strip" });
  const rotations = el("div", { class: "strip" });

  // 3x3 compass: NW N NE / W . E / SW S SE
  const layout: (Dir | null)[] = ["north-west", "north", "north-east", "west", null, "east", "south-west", "south", "south-east"];
  function drawDirs() {
    dirGrid.replaceChildren(...layout.map((d) => d
      ? el("button", {
          type: "button", class: st.dir === d ? "on" : "",
          title: `${DIR_LABEL[d]}${u!.mirrored[d] ? "（镜像）" : ""}`,
          onclick: () => { st.dir = d; drawDirs(); drawStrip(); },
        }, DIR_ARROW[d])
      : el("span", { class: "center" }, DIR_LABEL[st.dir])));
  }
  function drawAttack() {
    attackSeg.replaceChildren(...(Object.keys(ATTACK_LABEL) as AttackVersion[]).map((a) =>
      el("button", {
        type: "button", class: `${prefs.attack === a ? "on" : ""} ${a === "attack" || u!.variants?.[a] ? "" : "missing"}`,
        onclick: () => { prefs.attack = a; savePrefs(); st.anim = "attack"; drawAttack(); drawAnims(); drawStrip(); },
      }, ATTACK_LABEL[a])));
    attackNote.textContent = ATTACK_NOTE[prefs.attack];
  }
  function drawView() {
    const items: [ViewMode, string][] = [["color", "原图"], ["lit", "法线光照"], ["normal", "法线贴图"]];
    viewSeg.replaceChildren(...items.map(([v, l]) => el("button", {
      type: "button", class: `${st.view === v ? "on" : ""} ${u!.files.normal ? "" : "missing"}`,
      onclick: () => { st.view = v; drawView(); },
    }, l)));
  }
  function drawAnims() {
    animSeg.replaceChildren(...(["idle", "walk", "attack", "rest", "death"] as AnimName[]).map((a) =>
      el("button", {
        type: "button", class: `${st.anim === a ? "on" : ""} ${hasAnim(u!, a) ? "" : "missing"}`,
        title: hasAnim(u!, a) ? "" : "尚未生成，显示替代帧",
        onclick: () => { st.anim = a; drawAnims(); drawStrip(); },
      }, ANIM_LABEL[a])));
  }

  let sheet: Sheet | null = null;
  function frameCanvas(name: string, scale: number, label?: string) {
    const c = el("canvas", { class: "sprite" });
    const fw = sheet?.atlas.frames[name]?.frame.w ?? u!.cell;
    c.width = c.height = fw * scale;
    c.style.width = c.style.height = `${fw * scale}px`;
    if (sheet) drawFrame(c.getContext("2d")!, sheet.img, sheet.atlas, name, 0, 0, scale);
    return el("figure", {}, c, label ? el("figcaption", {}, label) : null);
  }
  function drawStrip() {
    if (!sheet) return;
    const r = resolve(sheet.atlas, st.anim, st.dir, prefs.attack);
    const durs = durations(sheet.atlas, r.key, st.dir, r.frames, fpsFor(u!, st.anim), true);
    const hit = st.anim === "attack" ? hitIndex(sheet.atlas, r.key, st.dir, r.frames.length) : -1;
    strip.replaceChildren(...r.frames.map((f, i) => frameCanvas(f, 2, `#${i + 1} · ${Math.round(durs[i])}ms${i === hit ? " · 命中" : ""}`)));
  }

  const sheetRow = u.sheet?.data;
  const cfgTable = (rows: [string, unknown][]) =>
    el("table", { class: "kv" }, ...rows.filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) =>
      el("tr", {}, el("th", {}, k), el("td", {}, String(v)))));

  root.append(
    el("a", { class: "back", href: "#/" }, "← 返回图鉴"),
    el("section", { class: "unit-head" },
      el("div", {},
        el("h1", {}, u.displayName, el("span", { class: "en" }, u.englishName)),
        el("div", { class: "chips" },
          el("span", { class: `chip f-${u.faction}` }, FACTION_LABEL[u.faction]),
          el("span", { class: "chip" }, ERA_LABEL[u.era] ?? u.era),
          el("span", { class: "chip" }, `${SIZE_LABEL[u.sizeClass] ?? u.sizeClass} · ${u.canvas}px 画布`),
          el("span", { class: "chip" }, HABITAT[u.habitat] ?? u.habitat),
          u.demo ? el("span", { class: "chip warn" }, "演示单位") : null,
        ),
      ),
      el("a", { class: "button", href: `#/lab` }, "在实验室中查看 →"),
    ),
    el("section", { class: "viewer" },
      el("div", { class: "stage big-stage" }, big),
      el("div", { class: "controls" },
        el("h3", {}, "动作"), animSeg,
        el("h3", {}, "攻击版本"), attackSeg, attackNote,
        el("label", { class: "check", title: "关闭：匀速循环（旧效果）" },
          el("input", { type: "checkbox", checked: prefs.feel, onchange: (e: Event) => { prefs.feel = (e.target as HTMLInputElement).checked; savePrefs(); } }),
          "攻击节奏优化"),
        el("h3", {}, "光照预览"), viewSeg,
        el("p", { class: "muted small" }, "法线光照：把鼠标移到左侧画面上移动光源。"),
        el("input", { type: "range", min: "4", max: "60", step: "1", value: "18", title: "光源高度",
          oninput: (e: Event) => { st.lightZ = +(e.target as HTMLInputElement).value; } }),
        el("h3", {}, "方向"), dirGrid,
        el("p", { class: "muted small" }, `实际绘制 ${u.drawnDirections.length} 个方向；左、左上、左下由右侧镜像。`),
        el("h3", {}, "速度"),
        el("input", { type: "range", min: "0.25", max: "2", step: "0.25", value: "1",
          oninput: (e: Event) => { st.speed = +(e.target as HTMLInputElement).value; } }),
        el("label", { class: "check" },
          el("input", { type: "checkbox", checked: true, onchange: (e: Event) => { st.marks = (e.target as HTMLInputElement).checked; } }),
          "显示阴影和阵营圈"),
      ),
    ),
    el("h2", { class: "section-title" }, "当前动作的全部帧"), strip,
    el("h2", { class: "section-title" }, "8 方向静态图"), rotations,
    el("section", { class: "config" },
      el("div", { class: "panel" },
        el("h2", {}, "物种设定（来自物种表）"),
        sheetRow
          ? cfgTable(m.sheetHeader.filter((h) => h !== "是否已生成" && h !== "时代").map((h) => [h, sheetRow[h]]))
          : el("p", { class: "muted" }, u.demo ? "演示单位，不在物种表中。" : "物种表中没有找到对应行。"),
        m.sheetUrl && u.sheet ? el("a", { href: m.sheetUrl, target: "_blank", rel: "noopener", class: "small" }, `物种表第 ${sheetRow?.row ?? u.sheet.row} 行 ↗`) : null,
      ),
      el("div", { class: "panel" },
        el("h2", {}, "生成配置"),
        cfgTable([
          ["模型", u.prompt.model], ["描述（提示词）", u.prompt.description], ["视角", u.prompt.view],
          ["描边", u.prompt.outline], ["细节", u.prompt.detail], ["骨骼模板", u.prompt.templateId],
          ["画布", `${u.canvas}×${u.canvas}px（动画帧 ${u.cell}×${u.cell}px）`], ["种子", u.prompt.seed],
          ...(u.prompt.styleCharacterId ? [["风格参考", u.prompt.styleCharacterId === "bd11b67a-1165-495e-96cf-b40403d116cb" ? "冰河斑鬣狗（高清标准）" : String(u.prompt.styleCharacterId)] as [string, string]] : []),
          ["概念图", u.prompt.reference ? `${String(u.prompt.reference).split("/").pop()}（${u.prompt.referenceLicense ?? ""}）` : "无（文字 + 风格参考）"],
        ]),
        el("h3", {}, "动作提示词"),
        el("table", { class: "grid-table" },
          el("tr", {}, el("th", {}, "动作"), el("th", {}, "描述"), el("th", {}, "帧数"), el("th", {}, "状态")),
          ...u.animations.map((a) => el("tr", {},
            el("td", {}, ANIM_LABEL[a.name as AnimName] ?? a.name), el("td", {}, a.action), el("td", {}, String(a.frames)),
            el("td", {}, a.generated ? "已生成" : "未生成"))),
          el("tr", {}, el("td", {}, "休息"), el("td", {}, "不单独生成：待机动作放慢播放 + 头顶 Zzz（代码实现）"), el("td", {}, "—"), el("td", {}, hasAnim(u, "rest") ? "可用" : "—")),
        ),
      ),
      el("div", { class: "panel" },
        el("h2", {}, "来源登记"),
        cfgTable([
          ["工具", u.provenance.tool], ["授权", u.provenance.license], ["创建", u.provenance.created],
          ["更新", u.provenance.updated], ["PixelLab 角色 ID", u.provenance.characterId],
          ["候选数", u.provenance.candidates || "—"], ["选中种子", u.prompt.seed], ["消耗生成次数", u.provenance.generationsSpent],
        ]),
        u.files.candidates ? el("details", { class: "cands" },
          el("summary", {}, "候选对比（每行一个候选的 8 个方向，选中的种子见上表；不满意可以告诉我换一个）"),
          el("img", { src: u.files.candidates, class: "cand-img", alt: "candidates" })) : null,
        el("div", { class: "downloads" },
          el("a", { class: "button", href: u.files.png, download: `${u.id}.png` }, "精灵图集 PNG"),
          el("a", { class: "button", href: u.files.atlas, download: `${u.id}.json` }, "图集 JSON"),
        ),
        el("details", {}, el("summary", {}, `配置文件 prompts/units/${u.id}.yaml`), el("pre", {}, u.yaml)),
      ),
    ),
  );
  drawAnims();
  drawDirs();
  drawAttack();
  drawView();
  let lit: LitFrames | null = null;

  loadSheet(u).then((s) => {
    sheet = s;
    sizeBig();
    if (u.files.normal) loadImage(u.files.normal).then((n) => (lit = new LitFrames(s.img, n, s.atlas)));
    drawStrip();
    rotations.replaceChildren(...DIRS.map((d) => {
      const f = s.atlas.animations[`rotation_${d}`]?.[0];
      return f ? frameCanvas(f, 2, `${DIR_LABEL[d]}${u.mirrored[d] ? "·镜像" : ""}`) : el("span");
    }));
  });

  let raf = 0, t = 0, last = performance.now();
  const tick = (now: number) => {
    t += (now - last) * st.speed;
    last = now;
    if (sheet) {
      const ctx = big.getContext("2d")!;
      const r = resolve(sheet.atlas, st.anim, st.dir, prefs.attack);
      ctx.clearRect(0, 0, big.width, big.height);
      if (r.frames.length) {
        const durs = durations(sheet.atlas, r.key, st.dir, r.frames, fpsFor(u, st.anim), prefs.feel);
        const name = r.frames[frameAt(durs, t)];
        const cx = big.width / 2, cy = big.height / 2;
        const foot = (sheet.atlas.meta.unit.foot ?? 0) * SCALE;
        const rot = sheet.atlas.animations[`rotation_${st.dir}`]?.[0] ?? r.frames[0];
        if (st.marks && st.view !== "normal") drawGroundMarks(ctx, cx, cy + foot, bodyWidth(sheet.img, sheet.atlas, rot), SCALE, u.faction);
        if (st.view !== "color" && lit) {
          const a = t / 1400;
          const L = st.mouse ?? { x: Math.cos(a) * u.cell * 0.6, y: Math.sin(a) * u.cell * 0.45 };
          lit.draw(ctx, name, cx, cy, SCALE, st.view, { x: L.x, y: L.y, z: st.lightZ, color: [1.15, 1.05, 0.9], ambient: [0.32, 0.34, 0.42], bands: 0 });
          if (st.view === "lit") {
            ctx.fillStyle = "#ffd36b";
            ctx.beginPath();
            ctx.arc(cx + L.x * SCALE, cy + L.y * SCALE, 5, 0, Math.PI * 2);
            ctx.fill();
          }
        } else {
          drawFrameAt(ctx, sheet.img, sheet.atlas, name, cx, cy, SCALE);
        }
        if (st.anim === "rest") drawZzz(ctx, cx + u.cell * SCALE * 0.12, cy - u.cell * SCALE * 0.22, t / 1000, SCALE / 1.5);
      }
    }
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}
