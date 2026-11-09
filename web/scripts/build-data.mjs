// Collects everything the site shows into web/public/data/:
//   manifest.json            units (prompt config + sheet row + provenance), sheet species, tilesets
//   units/<id>.png|.json     processed spritesheets and atlases
//   tilesets/<id>.png|.json  Wang tilesets
// Runs before `vite` / `vite build`, so Vercel always deploys what is in the repo.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import YAML from "yaml";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "../..");
const OUT = path.resolve(here, "../public/data");

const read = (p) => fs.readFileSync(p, "utf8");
const readJson = (p) => JSON.parse(read(p));
const exists = (p) => fs.existsSync(p);

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(path.join(OUT, "units"), { recursive: true });
fs.mkdirSync(path.join(OUT, "tilesets"), { recursive: true });

const style = YAML.parse(read(path.join(ROOT, "prompts/style.yaml")));
const sheet = exists(path.join(ROOT, "data/species.json"))
  ? readJson(path.join(ROOT, "data/species.json"))
  : { tabs: {} };
const creatureRows = sheet.tabs?.["生物"]?.rows ?? [];
const speciesKey = "物种名称";

function sheetRowFor(cfg) {
  if (!cfg.sheet) return null;
  const want = cfg.sheet.name;
  return creatureRows.find((r) => r[speciesKey] === want) ?? null;
}

function animationsFor(cfg) {
  const byName = new Map();
  for (const a of style.default_animations ?? []) byName.set(a.name, { ...a });
  for (const a of cfg.animations ?? []) byName.set(a.name, { ...(byName.get(a.name) ?? {}), ...a });
  return [...byName.values()].filter((a) => !a.skip);
}

const units = [];
for (const file of fs.readdirSync(path.join(ROOT, "prompts/units")).sort()) {
  if (!file.endsWith(".yaml")) continue;
  const yamlText = read(path.join(ROOT, "prompts/units", file));
  const cfg = YAML.parse(yamlText);
  const dir = path.join(ROOT, "units", cfg.id);
  const atlasPath = path.join(dir, `${cfg.id}.json`);
  if (!exists(atlasPath)) continue; // configured but not generated yet
  fs.copyFileSync(path.join(dir, `${cfg.id}.png`), path.join(OUT, "units", `${cfg.id}.png`));
  fs.copyFileSync(atlasPath, path.join(OUT, "units", `${cfg.id}.json`));
  const normalPath = path.join(dir, `${cfg.id}_n.png`);
  const hasNormal = exists(normalPath);
  if (hasNormal) fs.copyFileSync(normalPath, path.join(OUT, "units", `${cfg.id}_n.png`));
  const atlas = readJson(atlasPath);
  const source = exists(path.join(dir, "source.json")) ? readJson(path.join(dir, "source.json")) : {};
  const row = sheetRowFor(cfg);
  const generated = Object.keys(atlas.animations)
    .map((k) => k.split("_")[0])
    .filter((v, i, a) => a.indexOf(v) === i);
  units.push({
    id: cfg.id,
    displayName: cfg.display_name,
    englishName: cfg.english_name ?? cfg.sheet?.name?.split(" - ")[1] ?? cfg.id,
    faction: cfg.faction,
    era: cfg.era,
    sizeClass: cfg.size_class,
    habitat: cfg.habitat ?? "land",
    demo: !!cfg.demo,
    canvas: cfg.canvas,
    cell: atlas.meta.unit.cell,
    anchor: atlas.meta.unit.anchor,
    fps: atlas.meta.unit.fps,
    generatedAnimations: generated,
    sheet: cfg.sheet ? { ...cfg.sheet, data: row } : null,
    prompt: {
      description: cfg.description?.trim(),
      templateId: cfg.template_id,
      seed: source.create_request?.seed ?? cfg.seed,
      view: cfg.view ?? style.view,
      outline: cfg.outline ?? style.outline,
      detail: cfg.detail ?? style.detail,
      model: "PixelLab create-character-v3",
    },
    animations: animationsFor(cfg).map((a) => ({
      name: a.name,
      action: a.action,
      frames: a.frames,
      generated: generated.includes(a.name),
    })),
    drawnDirections: style.drawn_directions,
    mirrored: style.mirror_map,
    provenance: {
      tool: source.tool ?? "PixelLab API v2",
      license: source.license ?? "",
      created: source.created ?? "",
      updated: source.updated ?? source.created ?? "",
      characterId: source.character_id ?? "",
      generationsSpent: source.generations_spent ?? null,
      candidates: (source.candidates ?? []).length,
    },
    yaml: yamlText,
    files: {
      png: `data/units/${cfg.id}.png`,
      atlas: `data/units/${cfg.id}.json`,
      normal: hasNormal ? `data/units/${cfg.id}_n.png` : undefined,
    },
    variants: atlas.meta.unit.variants ?? {},
  });
}

const tilesets = [];
const tsDir = path.join(ROOT, "tilesets");
if (exists(tsDir)) {
  for (const f of fs.readdirSync(tsDir).sort()) {
    if (!f.endsWith(".json")) continue;
    const id = f.replace(/\.json$/, "");
    fs.copyFileSync(path.join(tsDir, f), path.join(OUT, "tilesets", f));
    fs.copyFileSync(path.join(tsDir, `${id}.png`), path.join(OUT, "tilesets", `${id}.png`));
    const tn = path.join(tsDir, `${id}_n.png`);
    if (exists(tn)) fs.copyFileSync(tn, path.join(OUT, "tilesets", `${id}_n.png`));
    const meta = readJson(path.join(tsDir, f));
    tilesets.push({
      id,
      png: `data/tilesets/${id}.png`,
      normal: exists(path.join(tsDir, `${id}_n.png`)) ? `data/tilesets/${id}_n.png` : undefined,
      json: `data/tilesets/${id}.json`,
      lower: meta.request?.lower_description,
      upper: meta.request?.upper_description,
    });
  }
}

const unitBySheetName = new Map(units.filter((u) => u.sheet).map((u) => [u.sheet.name, u.id]));
const species = creatureRows
  .filter((r) => r[speciesKey])
  .map((r) => ({
    row: r.row,
    name: r[speciesKey],
    era: r["时代"],
    type: r["生态类型（技能树）"],
    unitId: unitBySheetName.get(r[speciesKey]) ?? null,
  }));

const manifest = {
  builtAt: new Date().toISOString(),
  sheetUrl: sheet.sheet_url ?? "",
  sheetHeader: sheet.tabs?.["生物"]?.header ?? [],
  units,
  species,
  tilesets,
};
fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify(manifest, null, 1));
console.log(`manifest: ${units.length} units, ${species.length} sheet species, ${tilesets.length} tilesets`);
