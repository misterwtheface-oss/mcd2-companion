// Audit: every item's built-in effects / enchantments / companion summons carry an origin tag, a real name and a
// description. Uses the app's own originTag (sliced from app.js), so it checks what the app shows.
// Run: node tools/audit_intrinsics.js   (exit 1 on any miss)
const fs = require('fs'), path = require('path');
const root = path.join(__dirname, '..');
global.window = {}; require(path.join(root, 'data', 'data.js')); const D = window.MCD2;
const src = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const blk = src.slice(src.indexOf('const GEAR_GRP'), src.indexOf('function originMark'));
const ITEM = Object.fromEntries(D.items.map(i => [i.id, i]));
const originTag = new Function('D', 'ITEM', blk + ';return originTag;')(D, ITEM);
const DEV_KEY = /^[A-Za-z0-9]+(_[A-Za-z0-9]+)+$/;
const counts = {}, misses = [];
for (const it of D.items) {
  const L = [];
  if (it.ue) L.push(['n', it.ue, D.enchantments[it.ue].n, D.enchantments[it.ue].d]);
  for (const t of it.fx || []) { const e = D.templates[t].e; L.push(['e', e, D.effects[e].n, D.effects[e].d]); }
  if (it.comp) L.push(['c', null, it.comp.n, it.d]);
  if (it.k === 'talisman') [...new Set(it.lv.flatMap(l => (l.fx || []).map(t => D.templates[t].e)))]
    .forEach(e => L.push(['e', e, D.effects[e].n, D.effects[e].d]));
  for (const [k, id, n, d] of L) {
    const tg = originTag(it, k, id);
    if (!tg) misses.push(`no tag: ${it.n} / ${n}`);
    if (!n || DEV_KEY.test(n)) misses.push(`no name: ${it.n} / ${n}`);
    if (!d) misses.push(`no description: ${it.n} / ${n}`);
    if (tg) counts[`${it.k} | ${tg.n}`] = (counts[`${it.k} | ${tg.n}`] || 0) + 1;
  }
}
console.log(counts);
console.log(misses.length ? misses.join('\n') : 'all built-ins tagged, named and described');
process.exit(misses.length ? 1 : 0);
