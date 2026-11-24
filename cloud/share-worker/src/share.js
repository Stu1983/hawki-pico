// HAWKi share server (a Cloudflare Worker + one KV namespace, SHARE): Picos with "Online backup" switched on
// upload their readings once a day under a random ID; whoever is given the ID can look at the same pages
// (read only, as they stood at the upload) or restore the readings to a new Pico.
//
//   PUT    /u/<ID>   the Pico's upload (X-Key: its own key; the first upload for an ID sets it)
//   GET    /u/<ID>   the upload, for "Restore from ID" on a Pico's page (CORS open: the page is on the house's network)
//   DELETE /u/<ID>   sharing switched off (X-Key)
//   GET    /v/<ID>   the support view: remembers the ID in a cookie, then / and /history are that Pico's own pages
//                    (from GitHub, the release it runs) with its upload behind every /api/ call
//
// Stored per ID: one KV entry 'd:<ID>' (the upload as sent) with metadata {h: sha-256 of the key, at, size, fw}.
// Nothing else is kept: no IP addresses, no logs of who looked.

export const ID = /^HK-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/;
export const MAX = 4000000;   // bytes: two years of hourly readings for four tanks is about 1 MB
export const GAP = 240;       // seconds between uploads for one ID (the Pico sends one a day, or on "Upload now")
const REPO = 'https://raw.githubusercontent.com/Stu1983/hawki-pico/';
const PAGES = {'/': 'ui.html', '/index.html': 'ui.html', '/history': 'hist.html', '/common.js': 'common.js.html'};

const cors = {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, PUT, DELETE, OPTIONS',
              'Access-Control-Allow-Headers': 'X-Key, Content-Type'};
const json = (o, status = 200, extra = {}) => new Response(JSON.stringify(o), {status,
  headers: Object.assign({'Content-Type': 'application/json', 'Cache-Control': 'no-store'}, extra)});
const err = (msg, status, extra) => json({error: msg}, status, extra);

async function sha(s) {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, '0')).join('');
}

function okId(s) {
  const id = decodeURIComponent(s || '').toUpperCase();
  return ID.test(id) ? id : null;
}

async function meta(env, id) {  // the metadata only (the value isn't read)
  const r = await env.SHARE.getWithMetadata('d:' + id, {type: 'stream'});
  if (r.value) await r.value.cancel();
  return r.value === null ? null : (r.metadata || {});
}

async function upload(req, env, id, now) {
  const key = req.headers.get('X-Key') || '';
  if (!/^[0-9a-f]{32}$/.test(key)) return err('no key', 401, cors);
  if (req.method === 'DELETE') {
    const m = await meta(env, id);
    if (!m) return err('nothing backed up under that ID', 404, cors);
    if (m.h !== await sha(key)) return err('not this Pico\'s ID', 403, cors);
    await env.SHARE.delete('d:' + id);
    return json({ok: true}, 200, cors);
  }
  if (+req.headers.get('Content-Length') > MAX) return err('too large', 413, cors);
  const body = await req.text();
  if (body.length > MAX) return err('too large', 413, cors);
  let u;
  try { u = JSON.parse(body); } catch (e) { return err('not JSON', 400, cors); }
  if (!u || u.format !== 'hawki-backup' || u.share !== 1 || typeof u.tanks !== 'object' || typeof u.history !== 'object')
    return err('not a share upload', 400, cors);
  const m = await meta(env, id), h = await sha(key);
  if (m && m.h !== h) return err('not this Pico\'s ID', 403, cors);
  if (m && now - (m.at || 0) < GAP) return err('too soon: one upload every few minutes', 429, cors);
  await env.SHARE.put('d:' + id, body, {metadata: {h, at: now, size: body.length, fw: String(u.fw || '').slice(0, 20)}});
  return json({ok: true, at: now}, 200, cors);
}

// ---------- the support view ----------
const cache = new Map();  // id -> {t, u}: a page and its dozen API calls read the upload once, not a dozen times
async function data(env, id, now) {
  const c = cache.get(id);
  if (c && now - c.t < 60) return c.u;
  const u = await env.SHARE.get('d:' + id, 'json');
  if (cache.size > 20) cache.clear();
  if (u) cache.set(id, {t: now, u});
  return u;
}

function unb64(s) {
  const b = atob(s || ''), out = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) out[i] = b.charCodeAt(i);
  return out;
}

const bin = b => new Response(b, {headers: {'Content-Type': 'application/octet-stream', 'Cache-Control': 'no-store'}});

// What the pages are handed is plain data: every string loses < > " ' and ` (the pages build HTML from some of it,
// and an upload is whatever its sender made it), so nothing in an upload can become markup or script
export function plain(o) {
  if (typeof o === 'string') return o.replace(/[<>"'`]/g, '');
  if (Array.isArray(o)) return o.map(plain);
  if (o && typeof o === 'object') { const r = {}; for (const k in o) r[plain(k)] = plain(o[k]); return r; }
  return o;
}

export function api(u, path, q) {
  const json = o => new Response(JSON.stringify(plain(o)), {headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}});
  const mac = (q.get('mac') || '').toLowerCase();
  switch (path) {
    case '/api/state': return json(u.state || {tanks: []});
    case '/api/deliveries': return json(u.deliveries || {});
    case '/api/curve':  // (not a trial capacity: the Pico works those out; the view leaves the capacity check undone)
      return !q.get('tank_l') && u.curves && u.curves[mac] ? json(u.curves[mac]) : err(q.get('tank_l') ? 'not in a shared view' : 'unknown tank', 404);
    case '/api/battlog': return json((u.battlog || {})[mac] || []);
    case '/api/weather': return bin(unb64((u.files || {})[q.get('f') === '1' ? 'wxf' : 'wx']));
    case '/api/prices': return q.get('h') === '1' ? null : bin(unb64((u.files || {}).prices));  // (h=1: the older prices, the same for every Pico: from GitHub)
    case '/api/hist': {
      if (!(u.history || {})[mac] && !(u.tanks || {})[mac]) return err('unknown tank', 404);
      let b = unb64(u.history[mac]);
      const since = +q.get('since') || 0;
      if (since) {  // (records are 6 bytes, sorted by time: keep those from `since` on)
        const v = new DataView(b.buffer);
        let i = 0;
        while (i + 6 <= b.length && v.getUint32(i, true) < since) i += 6;
        b = b.slice(i);
      }
      return bin(b);
    }
  }
  return null;
}

const safe = o => JSON.stringify(o).replace(/</g, '\\u003c').replace(/\u2028|\u2029/g, ' ');  // (an upload's text inside a <script>: never able to close it)
const fwOk = v => /^\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(String(v || '')) ? String(v) : null;

export function inject(html, id, u) {
  const at = Math.max(0, Math.floor(+u.at || 0)), when = new Date(at * 1000).toISOString().slice(0, 16).replace('T', ' ');
  const area = u.area && u.area.pc ? ' · ' + u.area.pc : '';
  // the clock stands at the upload (so "last heard", "today" and the forecast read as they did then); nothing is saved
  const s = `<script>(()=>{const AT=${at * 1000},D=Date;class F extends D{constructor(...a){if(a.length)super(...a);else super(AT)}static now(){return AT}}window.Date=F;
const f=window.fetch.bind(window);window.fetch=(x,o)=>o&&o.method&&String(o.method).toUpperCase()!=='GET'?Promise.resolve(new Response('{}',{status:200,headers:{'Content-Type':'application/json'}})):f(x,o);
addEventListener('DOMContentLoaded',()=>{const b=document.createElement('div');b.textContent=${safe('Backup ' + id + area + ' · as at ' + when + ' UTC · v' + (fwOk(u.fw) || '?') + ' · read only')};
b.style.cssText='position:sticky;top:0;z-index:99;background:#7a4a00;color:#fff;font:600 13px system-ui;padding:6px 10px;text-align:center';document.body.prepend(b)})})()</script>`;
  return html.replace(/<head[^>]*>/i, m => m + s);
}

async function page(name, fw) {
  for (const ref of [fw ? 'v' + fw : null, 'main'].filter(Boolean)) {
    const r = await fetch(REPO + ref + '/firmware/' + name, {cf: {cacheTtl: 3600, cacheEverything: true}});
    if (r.ok) return r.text();
  }
  return null;
}

const HOME = `<!doctype html><meta name=viewport content="width=device-width"><title>Oil monitor backups</title>
<body style="font:16px system-ui;max-width:420px;margin:40px auto;padding:0 16px"><h2>Oil monitor backups</h2>
<p>Enter the backup ID from the Pico's Config page, under Online backup (like HK-7QM2-XFD9).</p>
<form onsubmit="location.href='/v/'+encodeURIComponent(this.id.value.trim());return false"><input name=id autofocus style="font:inherit;padding:6px;width:14em"> <button>Look</button></form>`;

function cookieId(req) {
  const m = /(?:^|;\s*)hkv=([^;]+)/.exec(req.headers.get('Cookie') || '');
  return m ? okId(m[1]) : null;
}

export async function handle(req, env, now = Math.floor(Date.now() / 1000)) {
  const url = new URL(req.url), p = url.pathname;
  if (p.startsWith('/u/')) {
    if (req.method === 'OPTIONS') return new Response(null, {status: 204, headers: cors});
    const id = okId(p.slice(3));
    if (!id) return err('a backup ID looks like HK-7QM2-XFD9', 400, cors);
    if (req.method === 'GET') {
      const v = await env.SHARE.get('d:' + id, 'text');
      return v === null ? err('nothing backed up under that ID', 404, cors)
        : new Response(v, {headers: Object.assign({'Content-Type': 'application/json', 'Cache-Control': 'no-store'}, cors)});
    }
    if (req.method === 'PUT' || req.method === 'DELETE') return upload(req, env, id, now);
    return err('not allowed', 405, cors);
  }
  if (p.startsWith('/v/')) {
    const id = okId(p.slice(3));
    if (!id || !(await meta(env, id))) return new Response(HOME.replace('<p>', '<p style="color:#b00">Nothing is backed up under that ID.</p><p>'), {status: 404, headers: {'Content-Type': 'text/html'}});
    return new Response(null, {status: 302, headers: {'Location': '/', 'Set-Cookie': `hkv=${id}; Path=/; Max-Age=86400; HttpOnly; Secure; SameSite=Lax`}});
  }
  const id = cookieId(req);
  if (!id) return p === '/' ? new Response(HOME, {headers: {'Content-Type': 'text/html'}}) : err('not found', 404);
  const u = await data(env, id, now);
  if (!u) return new Response(HOME.replace('<p>', '<p style="color:#b00">Nothing is backed up under that ID any more.</p><p>'), {status: 404, headers: {'Content-Type': 'text/html'}});
  if (req.method !== 'GET') return json({});  // read only
  if (p === '/api/prices' && url.searchParams.get('h') === '1') {
    const r = await fetch(REPO + 'main/data/priceh.bin', {cf: {cacheTtl: 86400, cacheEverything: true}});
    return r.ok ? bin(new Uint8Array(await r.arrayBuffer())) : bin(new Uint8Array(0));
  }
  if (p.startsWith('/api/')) return api(u, p, url.searchParams) || err('not available in a shared view', 404);
  const name = PAGES[p];
  if (!name) return err('not found', 404);
  const t = await page(name, fwOk(u.fw));
  if (t == null) return err('could not fetch the page from GitHub', 502);
  if (name === 'common.js.html') return new Response(t, {headers: {'Content-Type': 'application/javascript'}});
  return new Response(inject(t, id, u), {headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'}});
}

