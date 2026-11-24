// node test.mjs [upload.json]  - the share server against an in-memory KV; with NODE_PATH holding jsdom, also the
// support view: the Pico's own pages (from firmware/, standing in for GitHub) drawn from the upload.
import {handle, ID, GAP, DAY_MAX} from './src/share.js';
import fs from 'fs';
import path from 'path';
import {createRequire} from 'module';
const here = path.dirname(new URL(import.meta.url).pathname), FW = path.join(here, '..', '..', 'firmware');
let fails = 0;
const ok = (c, m) => { console.log((c ? 'ok   ' : 'FAIL ') + m); if (!c) fails++; };

class KV {  // just what the Worker uses
  constructor() { this.m = new Map(); this.writes = 0; }
  async get(k, type) { const e = this.m.get(k); return e ? (type === 'json' ? JSON.parse(e.v) : e.v) : null; }
  async getWithMetadata(k) { const e = this.m.get(k); return e ? {value: {cancel: async () => {}}, metadata: e.md} : {value: null, metadata: null}; }
  async put(k, v, o) { this.writes++; this.m.set(k, {v, md: o && o.metadata}); }
  async delete(k) { this.m.delete(k); }
  async list({prefix}) { return {keys: [...this.m.keys()].filter(k => k.startsWith(prefix)).map(name => ({name})), list_complete: true}; }
}
const env = {SHARE: new KV(), INVITES: 'me=AB12-CD34, mate = zz99-qq88', MAX_IDS: '4'};
let T = 1795500000;
const call = (method, url, body, headers = {}) => handle(new Request('https://share.test' + url, {method, body, headers}), env, T);
const K1 = 'a'.repeat(32), K2 = 'b'.repeat(32), SID = 'HK-7QM2-XFD9';
const up = fs.existsSync(process.argv[2] || '') ? fs.readFileSync(process.argv[2], 'utf8')
  : JSON.stringify({format: 'hawki-backup', version: 1, share: 1, at: T, fw: '1.3.30', tanks: {'aa:bb:cc:dd:ee:01': {name: 'T'}}, history: {}, state: {tanks: []}});

ok(ID.test(SID) && !ID.test('HK-7QM2-XFDU') && !ID.test('hk-7qm2-xfd9'), 'IDs: the Pico\'s alphabet only');
let r = await call('PUT', '/u/' + SID, up, {'X-Key': K1});
ok(r.status === 403 && /invite code is needed/.test(await r.text()) && env.SHARE.writes === 0, 'a new ID without an invite code: refused');
r = await call('PUT', '/u/' + SID, up, {'X-Key': K1, 'X-Invite': 'AB12-CD35'});
ok(r.status === 403 && /isn't right/.test(await r.text()), 'a wrong invite code: refused');
r = await call('GET', '/invite?c=ab12cd34');
ok(r.status === 200 && r.headers.get('Access-Control-Allow-Origin') === '*', 'the page can check a code first (any case, with or without the dash)');
ok((await call('GET', '/invite?c=AB12')).status === 403 && (await call('GET', '/invite')).status === 403, '...a wrong or empty one: no');
r = await call('PUT', '/u/' + SID, up, {'X-Key': K1, 'X-Invite': 'ab12-cd34'});
ok(r.status === 200 && env.SHARE.writes === 1 && env.SHARE.m.get('d:' + SID).md.inv === 'me', 'the first upload, with an invite: stored, one KV write, which invite noted');
r = await call('GET', '/u/' + SID.toLowerCase());
ok(r.status === 200 && (await r.text()) === up && r.headers.get('Access-Control-Allow-Origin') === '*', 'read back as sent (any case), open to a Pico\'s page');
r = await call('PUT', '/u/' + SID, up, {'X-Key': K1});
ok(r.status === 429, 'again within a few minutes: refused');
T += GAP + 1;
r = await call('PUT', '/u/' + SID, up, {'X-Key': K2});
ok(r.status === 403, 'another key for the same ID: refused (only the Pico that made it can change it)');
r = await call('PUT', '/u/' + SID, up, {'X-Key': K1});
ok(r.status === 200 && env.SHARE.writes === 2, 'the same Pico later: replaced');
r = await call('PUT', '/u/' + SID, up, {});
ok(r.status === 401, 'no key: refused');
{ // the limits
  const K3 = 'c'.repeat(32), ids = ['HK-0000-0003', 'HK-0000-0004', 'HK-0000-0005', 'HK-0000-0006'];
  for (const i of ids.slice(0, 3)) await call('PUT', '/u/' + i, up, {'X-Key': K3, 'X-Invite': 'ZZ99-QQ88'});
  r = await call('PUT', '/u/' + ids[3], up, {'X-Key': K3, 'X-Invite': 'ZZ99-QQ88'});
  ok(r.status === 403 && /full/.test(await r.text()) && env.SHARE.m.size === 4, 'MAX_IDS backups: no more new ones');
  const t0 = T; let last;
  for (let k = 0; k < DAY_MAX + 1; k++) { T = (Math.floor(t0 / 86400) + 1) * 86400 + 60 + k * (GAP + 1); last = await call('PUT', '/u/' + ids[0], up, {'X-Key': K3}); }
  ok(last.status === 429 && /too many uploads today/.test(await last.text()), DAY_MAX + ' uploads a day per ID, then refused');
  T += 86400; ok((await call('PUT', '/u/' + ids[0], up, {'X-Key': K3})).status === 200, '...the next day: fine again');
  env.INVITES = 'me=AB12-CD34'; T += GAP + 1;
  r = await call('PUT', '/u/' + ids[1], up, {'X-Key': K3});
  ok(r.status === 403 && /cancelled/.test(await r.text()), 'an invite taken out of INVITES: its backups stop');
  ok((await call('GET', '/u/' + ids[1])).status === 200, '...though what is there can still be restored');
  env.SHARE.m.get('d:' + ids[2]).md.inv = undefined; delete env.SHARE.m.get('d:' + ids[2]).md.inv;
  ok((await call('PUT', '/u/' + ids[2], up, {'X-Key': K3})).status === 200, 'a backup from before invites: carries on');
  env.INVITES = 'long=' + 'A'.repeat(65); ok((await call('GET', '/invite?c=' + 'A'.repeat(65))).status === 403, 'a code longer than a Pico keeps: never accepted');
  delete env.INVITES; ok((await call('GET', '/invite?c=AB12-CD34')).status === 403, 'no INVITES at all: nobody new');
  env.INVITES = '*'; ok((await call('GET', '/invite?c=')).status === 200, "INVITES '*': anyone (someone's own server)");
  for (const i of ids) await env.SHARE.delete('d:' + i);
  env.INVITES = 'me=AB12-CD34, mate = zz99-qq88'; T += GAP + 1;
}
r = await call('PUT', '/u/HK-0000-0001', '{"format":"other"}', {'X-Key': K1});
ok(r.status === 400, 'not a share upload: refused');
r = await call('PUT', '/u/HK-0000-0001', 'x'.repeat(4000001), {'X-Key': K1});
ok(r.status === 413, 'too large: refused');
r = await call('GET', '/u/HK-12%2F..');
ok(r.status === 400, 'a bad ID: refused');
r = await call('GET', '/u/HK-0000-0002');
ok(r.status === 404, 'an ID never used: not found');
r = await call('OPTIONS', '/u/' + SID);
ok(r.status === 204 && /X-Key/.test(r.headers.get('Access-Control-Allow-Headers')), 'CORS preflight');

// ---- the support view
r = await call('GET', '/');
ok(r.status === 200 && /Enter the backup ID/.test(await r.text()), 'the home page asks for an ID');
r = await call('GET', '/v/HK-0000-0002');
ok(r.status === 404 && /Nothing is backed up/.test(await r.text()), 'an ID with nothing: says so');
r = await call('GET', '/v/' + SID.toLowerCase());
const ck = (r.headers.get('Set-Cookie') || '').split(';')[0];
ok(r.status === 302 && r.headers.get('Location') === '/' && ck === 'hkv=' + SID, 'the view remembers the ID and opens the dashboard');
const realFetch = globalThis.fetch;
globalThis.fetch = async u => {  // GitHub, from the local firmware/
  const m = /\/firmware\/(.+)$/.exec(String(u));
  return m && fs.existsSync(path.join(FW, m[1])) ? new Response(fs.readFileSync(path.join(FW, m[1]), 'utf8')) : new Response('', {status: 404});
};
const view = (url, method = 'GET') => call(method, url, method === 'GET' ? undefined : '{}', {Cookie: ck});
const U = JSON.parse(up), mac = Object.keys(U.tanks).sort((a, b) => (U.history[b] || '').length - (U.history[a] || '').length)[0];  // (the tank with most readings)
r = await view('/api/state');
ok(JSON.stringify(await r.json()) === JSON.stringify(U.state), '/api/state: the upload\'s');
r = await view('/api/hist?mac=' + mac);
const hb = new Uint8Array(await r.arrayBuffer());
ok(hb.length === Buffer.from(U.history[mac] || '', 'base64').length, '/api/hist: the readings (' + hb.length / 6 + ')');
if (hb.length >= 12) {
  const t1 = new DataView(hb.buffer).getUint32(6, true);
  r = await view('/api/hist?mac=' + mac + '&since=' + t1);
  ok((await r.arrayBuffer()).byteLength === hb.length - 6, '/api/hist?since=: from then on');
}
r = await view('/api/curve?mac=' + mac);
ok(r.status === (U.curves && U.curves[mac] ? 200 : 404), '/api/curve');
r = await view('/api/curve?mac=' + mac + '&tank_l=1200');
ok(r.status === 404, '/api/curve with a trial capacity: not offered (the Pico works those out)');
{ const f0 = globalThis.fetch; let asked = ''; globalThis.fetch = async u => { asked = String(u); return new Response(new Uint8Array([1, 2, 3, 4, 5, 6])); };
  r = await view('/api/prices?h=1'); const b = new Uint8Array(await r.arrayBuffer()); globalThis.fetch = f0;
  ok(asked.endsWith('/main/data/priceh.bin') && b.length === 6, '/api/prices?h=1: the older prices every Pico has, from GitHub'); }
r = await view('/api/tank', 'POST');
ok(r.status === 200 && JSON.stringify(await r.json()) === '{}', 'anything sent: ignored (read only)');
r = await view('/api/wifi/scan');
ok(r.status === 404, 'anything else on the Pico: not there');
r = await view('/');
const html = await r.text();
ok(r.status === 200 && /Backup HK-7QM2-XFD9/.test(html) && /class F extends D/.test(html) && /<html|<!doctype/i.test(html), 'the dashboard page: the Pico\'s own, with the banner and the clock at the upload');

// ---- the pages themselves, drawn from the upload (jsdom)
let JSDOM = null;
try { JSDOM = createRequire(import.meta.url)('jsdom').JSDOM; } catch (e) { console.log('(no jsdom on NODE_PATH: page check skipped)'); }
if (JSDOM && fs.existsSync(process.argv[2] || '')) {  // (the pages need a real upload to draw)
  const common = await (await view('/common.js')).text();
  for (const [url, check, what] of [['/', d => d.getElementById('d_l').textContent, 'dashboard: oil left'],
    ['/history?mac=' + mac, d => d.getElementById('c2s') && d.getElementById('c2s').textContent, 'forecast page: usage by month']]) {
    const h = (await (await view(url)).text()).replace('<script src="/common.js"></script>', () => '<script>' + common + '</script>');
    const errs = [];
    const w = new JSDOM(h, {url: 'https://share.test' + url, runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) {
      w.fetch = async (u, o) => { const x = await view(String(u).replace(/^https:\/\/share\.test/, ''), (o && o.method) || 'GET'); return x; };
      w.Response = Response; w.setInterval = () => 0; w.onerror = e => errs.push(String(e));
      w.HTMLDialogElement.prototype.showModal = function () { this.open = true; }; w.HTMLDialogElement.prototype.close = function () { this.open = false; };
    }}).window;
    await new Promise(res => setTimeout(res, 1500));
    const got = check(w.document);
    ok(!errs.length && got && got.trim() && got.trim() !== '–', what + ': ' + JSON.stringify((got || '').trim().slice(0, 90)) + (errs.length ? ' ERR ' + errs[0] : ''));
    { const d = w.document, bs = [...d.querySelectorAll('button')], live = bs.filter(b => !b.disabled).map(b => b.textContent.trim());
      const fields = [...d.querySelectorAll('input,select,textarea')].filter(e => !e.disabled && !e.readOnly);
      const bad = live.filter(t => /^(Save|Add|Delete|Remove|Turn|Restart|Set PIN|Change|Find|Send|Back up|Restore|Check for|Import|Use )/.test(t));
      ok(!fields.length && !bad.length && live.some(t => /^(Config|Usage)$/.test(t)), url + ': read only (no field to type in, no button that changes anything; tabs still work)' + (bad.length ? ' LEFT: ' + bad.join(', ') : '') + (fields.length ? ' FIELDS: ' + fields.map(e => e.id).join(',') : '')); }
    ok(new w.Date().getTime() === U.at * 1000 && w.Date.now() === U.at * 1000 && new w.Date(0).getTime() === 0, url + ': the clock stands at the upload');
  }
}
{ const bad = JSON.parse(up); bad.area = {pc: '</script><script>alert(1)</script>'}; bad.fw = '1.3.0/../../../evil/x/main'; bad.at = T;
  const {inject} = await import('./src/share.js');
  const h = inject('<html><head></head><body></body></html>', SID, bad);
  ok(!/<\/script><script>alert/.test(h) && /\\u003c\/script>/.test(h) && !/evil/.test(h), 'an upload\'s text can never close the viewer\'s script; a bad version is never used');
  const seen = []; const f0 = globalThis.fetch; globalThis.fetch = async u => { seen.push(String(u)); return new Response('<html><head></head></html>'); };
  T += GAP + 1; await call('PUT', '/u/' + SID, JSON.stringify(bad), {'X-Key': K1}); T += 61;
  await view('/'); globalThis.fetch = f0;
  ok(seen.length && seen.every(u => u.startsWith('https://raw.githubusercontent.com/Stu1983/hawki-pico/main/firmware/')), 'pages only ever from this repo: ' + seen[0]); }
{ const {api} = await import('./src/share.js');
  const st = {tanks: [{mac: 'x', name: 'Stu\'s <b>tank</b>', level: '<svg onload="x()">', n: 5}]};
  const got = await api({state: st}, '/api/state', new URLSearchParams()).json();
  ok(JSON.stringify(got) === JSON.stringify({tanks: [{mac: 'x', name: 'Stus btank/b', level: 'svg onload=x()', n: 5}]}), 'what the pages are handed is plain text: ' + JSON.stringify(got.tanks[0])); }
globalThis.fetch = realFetch;

// ---- /go: the home-screen shortcut's first page
{ const reads0 = env.SHARE.reads = 0; const g0 = env.SHARE.get, w0 = env.SHARE.getWithMetadata; let kv = 0;
  env.SHARE.get = async (...a) => { kv++; return g0.apply(env.SHARE, a); }; env.SHARE.getWithMetadata = async (...a) => { kv++; return w0.apply(env.SHARE, a); };
  r = await call('GET', '/go');
  const t = await r.text(); env.SHARE.get = g0; env.SHARE.getWithMetadata = w0;
  ok(r.status === 200 && kv === 0 && /max-age=2592000/.test(r.headers.get('Cache-Control')) && /Last backup/.test(t) && /Live/.test(t), '/go: the same page for everyone, cached a month, never reads a backup');
  ok(/\[hidden\]\{display:none!important\}/.test(t), '/go: hidden choices stay hidden (the buttons\' display:block would win otherwise; checked in Chromium)');
  if (JSDOM) for (const [hash, live, bk, what] of [['#id=hk-7qm2-xfd9&pico=' + encodeURIComponent('http://192.168.1.225'), 'http://192.168.1.225/', '/v/HK-7QM2-XFD9', 'both'],
      ['#id=HK-7QM2-XFD9', null, '/v/HK-7QM2-XFD9', 'no Pico address: Last backup only'],
      ['#id=x&pico=' + encodeURIComponent('javascript:alert(1)'), null, null, 'bad details: neither, and says how to make it again']]) {
    const d = new JSDOM(t, {url: 'https://share.test/go' + hash, runScripts: 'dangerously'}).window.document;
    const L = d.getElementById('live'), B = d.getElementById('bk');
    ok((live ? !L.hidden && L.getAttribute('href') === live : L.hidden) && (bk ? !B.hidden && B.getAttribute('href') === bk : B.hidden) && d.getElementById('no').hidden === !!(live || bk), '/go' + hash.slice(0, 40) + ': ' + what);
  }
  const f0 = globalThis.fetch; globalThis.fetch = async u => new Response(fs.readFileSync(path.join(FW, 'icon.py'), 'utf8'));
  r = await call('GET', '/apple-touch-icon.png'); const png = new Uint8Array(await r.arrayBuffer()); globalThis.fetch = f0;
  ok(r.status === 200 && r.headers.get('Content-Type') === 'image/png' && png[1] === 0x50 && png[2] === 0x4e && png[3] === 0x47 && png.length > 1000, 'the icon: the Pico\'s own (' + png.length + ' bytes)'); }

r = await call('DELETE', '/u/' + SID, undefined, {'X-Key': K2});
ok(r.status === 403, 'deleting with another key: refused');
r = await call('DELETE', '/u/' + SID, undefined, {'X-Key': K1});
ok(r.status === 200 && (await call('GET', '/u/' + SID)).status === 404, 'deleted by its Pico: gone');
process.exit(fails ? 1 : 0);
