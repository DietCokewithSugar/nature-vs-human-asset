// Render a rigged GLB to per-direction PNG frames with headless Chromium + three.js.
//   node scripts/render3d/render3d.cjs <model.glb> <outdir> '<clips json>' [size=256] [elevation=38]
// clips: [{"name":"walk","source":"clip:<gltf clip>","frames":6,"dirs":[...]},
//         {"name":"attack","source":"proc:attack","base":"<clip for base pose>","frames":9,"loop":false,"dirs":[...]}]
// proc:idle | proc:attack | proc:death are procedural poses on the rig (see render.html).
const { chromium } = require('playwright');
const fs = require('fs'); const path = require('path'); const http = require('http');
const ROOT = path.resolve(__dirname, '../..');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.glb': 'model/gltf-binary', '.png': 'image/png', '.json': 'application/json' };
(async () => {
  const [model, outdir, clipsJson, size = '256', elev = '38'] = process.argv.slice(2);
  const server = http.createServer((req, res) => {
    const f = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
    if (!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(f)] || 'application/octet-stream' }); fs.createReadStream(f).pipe(res);
  }).listen(0);
  const port = server.address().port;
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const p = await b.newPage();
  p.on('pageerror', (e) => console.log('pageerror', e.message));
  await p.goto(`http://localhost:${port}/scripts/render3d/render.html`); await p.waitForFunction(() => window.ready);
  const url = '/' + path.relative(ROOT, path.resolve(model)).split(path.sep).join('/');
  const res = await p.evaluate((cfg) => window.renderJob(cfg), { url, size: +size, elevation: +elev, clips: JSON.parse(clipsJson) });
  console.log('bone roles', JSON.stringify(res.roles));
  for (const [clip, dirs] of Object.entries(res.frames)) for (const [d, list] of Object.entries(dirs)) {
    const dir = path.join(outdir, clip, d); fs.mkdirSync(dir, { recursive: true });
    list.forEach((u, i) => fs.writeFileSync(path.join(dir, `frame_${String(i).padStart(2, '0')}.png`), Buffer.from(u.split(',')[1], 'base64')));
  }
  await b.close(); server.close(); console.log('rendered to', outdir);
})();
