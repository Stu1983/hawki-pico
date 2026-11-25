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
//   GET    /invite?c=<code>   is this invite code good? (the Pico's page asks before turning backup on)
//
// Who may start a backup: a new ID needs an invite code (X-Invite), from the INVITES secret: 'name=CODE,name=CODE'
// (wrangler secret put INVITES; '*' lets anyone in; unset lets nobody new in). Taking a name out of INVITES stops
// that person's backups too. At most MAX_IDS backups (a var, default 20); at most DAY_MAX uploads per ID a UTC day.
// IDs made before invites (no 'inv' in their metadata) carry on.
//
// Stored per ID: one KV entry 'd:<ID>' (the upload as sent) with metadata {h: sha-256 of the key, at, size, fw,
// inv: the invite's name, day, n: uploads that day}. Nothing else is kept: no IP addresses, no logs of who looked.

export const ID = /^HK-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/;
export const MAX = 4000000;   // bytes: two years of hourly readings for four tanks is about 1 MB
export const GAP = 240;       // seconds between uploads for one ID (the Pico sends three a day, or on "Back up now")
export const DAY_MAX = 8;     // uploads per ID per UTC day
const REPO = 'https://raw.githubusercontent.com/Stu1983/hawki-pico/';
const PAGES = {'/': 'ui.html', '/index.html': 'ui.html', '/history': 'hist.html', '/common.js': 'common.js.html'};

const cors = {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, PUT, DELETE, OPTIONS',
              'Access-Control-Allow-Headers': 'X-Key, X-Invite, Content-Type'};
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

// INVITES -> {CODE: name} ('*' -> null: anyone)
export function invites(env) {
  const s = String(env.INVITES || '').trim();
  if (s === '*') return null;
  const o = {};
  for (const part of s.split(',')) {
    const i = part.indexOf('='), name = part.slice(0, i).trim(), code = part.slice(i + 1).trim().toUpperCase();
    if (i > 0 && code && code.length <= 64) o[code] = name;  // (a Pico keeps up to 64 characters)
  }
  return o;
}
const okCode = c => String(c || '').toUpperCase().replace(/[^0-9A-Z]/g, '');
function inviteName(env, code) {  // -> the invite's name, '*' (open server), or null
  const inv = invites(env);
  if (inv === null) return '*';
  const c = okCode(code);
  for (const k of Object.keys(inv)) if (c && okCode(k) === c) return inv[k];
  return null;
}
function stillInvited(env, name) {
  const inv = invites(env);
  return name === undefined || name === '*' && inv === null || inv !== null && Object.values(inv).includes(name);
}
async function count(env) {  // backups stored (KV list: only when a new ID is started)
  let n = 0, cursor;
  do { const r = await env.SHARE.list({prefix: 'd:', cursor}); n += r.keys.length; cursor = r.list_complete ? null : r.cursor; } while (cursor);
  return n;
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
  const day = Math.floor(now / 86400), n = m && m.day === day ? (m.n || 1) + 1 : 1;
  if (n > DAY_MAX) return err('too many uploads today', 429, cors);
  let inv;
  if (m) {
    if (!stillInvited(env, m.inv)) return err('this backup\'s invite code has been cancelled', 403, cors);
    inv = m.inv;
  } else {
    inv = inviteName(env, req.headers.get('X-Invite'));
    if (inv === null) return err(req.headers.get('X-Invite') ? 'that invite code isn\'t right' : 'an invite code is needed', 403, cors);
    if (await count(env) >= (+env.MAX_IDS || 20)) return err('the backup server is full', 403, cors);
  }
  const md = {h, at: now, size: body.length, fw: String(u.fw || '').slice(0, 20), day, n};
  if (inv !== undefined) md.inv = inv;
  await env.SHARE.put('d:' + id, body, {metadata: md});
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
    case '/api/weather': return bin(unb64((u.files || {})[({'1': 'wxf', w: 'wxw', fw: 'wxfw'})[q.get('f')] || 'wx']));
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

// ---------- one request per page: the script and every answer the page asks for, inside the page itself
// B: '/api/...' -> [kind, body]: 'j' JSON text, 'b' base64 bytes. The page's fetch() answers from it (a reading list
// asked 'since' a time is cut down in the page); anything not in it still goes to the server.
export function bundle(u, priceh) {
  const B = {}, J = o => ['j', JSON.stringify(plain(o))], f = u.files || {};
  B['/api/state'] = J(u.state || {tanks: []});
  B['/api/deliveries'] = J(u.deliveries || {});
  for (const m of new Set([...Object.keys(u.tanks || {}), ...Object.keys(u.history || {})])) {
    const k = String(m);
    if (!/^[0-9a-f:]{17}$/.test(k)) continue;  // (as the server: it looks tanks up in lower case only)
    B['/api/hist?mac=' + k] = ['b', String((u.history || {})[m] || '')];
    if (u.curves && u.curves[m]) B['/api/curve?mac=' + k] = J(u.curves[m]);
    B['/api/battlog?mac=' + k] = J((u.battlog || {})[m] || []);
  }
  B['/api/weather'] = ['b', String(f.wx || '')];
  B['/api/weather?f=1'] = ['b', String(f.wxf || '')];
  B['/api/weather?f=w'] = ['b', String(f.wxw || '')];
  B['/api/weather?f=fw'] = ['b', String(f.wxfw || '')];
  B['/api/prices'] = ['b', String(f.prices || '')];
  if (priceh) B['/api/prices?h=1'] = ['b', priceh];
  for (const k of Object.keys(B)) if (B[k][0] === 'b') { const v = B[k][1].replace(/\s+/g, ''); if (/^[A-Za-z0-9+/=]*$/.test(v)) B[k][1] = v; else delete B[k]; }
  return B;
}
// (No backslashes in here: it sits in a template string.)
const SHIM = `const KEY=u=>{const p=u.pathname,q=u.searchParams,m=(q.get('mac')||'').toLowerCase();
 if(p==='/api/curve'&&q.get('tank_l'))return null;
 return p+(m?'?mac='+m:'')+(['1','w','fw'].includes(q.get('f'))?'?f='+q.get('f'):'')+(q.get('h')==='1'?'?h=1':'')};
const ans=(x)=>{let u;try{u=new URL(typeof x==='string'?x:x.url,location.href)}catch(e){return null}if(u.origin!==location.origin)return null;
 const k=KEY(u),e=k&&B[k];if(!e)return null;
 if(e[0]==='j')return new Response(e[1],{status:200,headers:{'Content-Type':'application/json'}});
 let b=Uint8Array.from(atob(e[1]),c=>c.charCodeAt(0));const since=+u.searchParams.get('since')||0;
 if(since&&u.pathname==='/api/hist'){const v=new DataView(b.buffer);let i=0;while(i+6<=b.length&&v.getUint32(i,true)<since)i+=6;b=b.slice(i)}
 return new Response(b,{status:200,headers:{'Content-Type':'application/octet-stream'}})};`;

export const SHIM_FOR_TEST = SHIM;
const safe = o => JSON.stringify(o).replace(/</g, '\\u003c').replace(/\u2028|\u2029/g, ' ');  // (an upload's text inside a <script>: never able to close it)
const fwOk = v => /^\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(String(v || '')) ? String(v) : null;

// Read only: only what looks around stays working (tabs, chart ranges, tank pickers, opening a tank's or a delivery's
// details, Cancel/Close, exports to this phone); every other button is greyed out, every field read only, no form sent.
// Re-applied whenever the page draws something new. (No backslashes in here: it sits in a template string.)
export const RO = `(()=>{const OK=['sub(','page(','showTank(','edit(','editDel(','tankFull(','exportCsv(','exportBackup(','pinCancel('],VIEW=['prUnit'];
const look=b=>{const oc=b.getAttribute('onclick')||'',t=(b.textContent||'').trim();
 return b.getAttribute('role')==='tab'||b.hasAttribute('data-s')||b.hasAttribute('data-t')||b.hasAttribute('data-pg')||b.hasAttribute('aria-pressed')||b.hasAttribute('aria-current')
  ||OK.some(k=>oc.indexOf(k)===0)&&oc.indexOf('(null')<0||oc.indexOf('.close()')>=0||t==='Cancel'||t==='Close'||t==='Edit'||t.indexOf('Edit ')===0};
const ro=()=>{document.querySelectorAll('button').forEach(b=>{if(!look(b)&&!b.disabled){b.disabled=true;b.title='Read only: this is a backup'}});
 document.querySelectorAll('input,select,textarea').forEach(e=>{const ty=(e.type||'').toLowerCase();
  if(VIEW.indexOf(e.id)>=0)return;if(e.tagName==='SELECT'||['checkbox','radio','file','range','color','submit','button'].indexOf(ty)>=0){if(!e.disabled)e.disabled=true}else if(!e.readOnly)e.readOnly=true})};
let q=0;const C='BUTTON,INPUT,SELECT,TEXTAREA';
const again=rs=>{if(!q&&rs.some(r=>r.type==='attributes'||[].some.call(r.addedNodes,n=>n.nodeType===1&&(n.matches(C)||n.querySelector(C))))){q=1;setTimeout(()=>{q=0;ro()},0)}};
const stop=e=>{e.preventDefault();e.stopImmediatePropagation()};
addEventListener('submit',stop,true);
addEventListener('keydown',e=>{const t=e.target;if(e.key==='Enter'&&t&&(t.readOnly||t.disabled))stop(e)},true);
addEventListener('click',e=>{const a=e.target&&e.target.closest&&e.target.closest('a[onclick]');if(a&&!look(a))stop(e)},true);
addEventListener('DOMContentLoaded',()=>{const st=document.createElement('style');st.textContent='button:disabled{opacity:.35!important;cursor:not-allowed!important;filter:grayscale(1)}input[readonly],textarea[readonly]{background:transparent!important;border-style:dashed!important}select:disabled{opacity:1!important;color:inherit!important;background:transparent!important;border-style:dashed!important}';document.head.append(st);ro();new MutationObserver(again).observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['disabled','readonly']})})})()`;

export function inject(html, id, u, B) {
  const at = Math.max(0, Math.floor(+u.at || 0)), when = new Date(at * 1000).toISOString().slice(0, 16).replace('T', ' ');
  const area = u.area && u.area.pc ? ' · ' + u.area.pc : '';
  // the clock stands at the upload (so "last heard", "today" and the forecast read as they did then); nothing is saved
  const s = `<script>(()=>{const AT=${at * 1000},D=Date;class F extends D{constructor(...a){if(a.length)super(...a);else super(AT)}static now(){return AT}}window.Date=F;
const B=${B ? safe(B) : '{}'};const V0='/v/'+${safe(id)},rebase=x=>{try{const u=new URL(typeof x==='string'?x:x.url,location.href);if(u.origin!==location.origin||u.pathname.indexOf('/api/')!==0)return x;const n=V0+u.pathname+u.search;return typeof x==='string'?n:new Request(n,x)}catch(e){return x}};${SHIM}const f=window.fetch.bind(window);window.fetch=(x,o)=>{if(String(o&&o.method||x&&x.method||'GET').toUpperCase()!=='GET')return Promise.resolve(new Response('{}',{status:200,headers:{'Content-Type':'application/json'}}));const r=ans(x);return r?Promise.resolve(r):f(rebase(x),o)};
addEventListener('DOMContentLoaded',()=>{const b=document.createElement('div');b.textContent=${safe('Backup ' + id + area + ' · as at ' + when + ' UTC · v' + (fwOk(u.fw) || '?') + ' · read only')};
b.style.cssText='position:sticky;top:0;z-index:99;background:#7a4a00;color:#fff;font:600 13px system-ui;padding:6px 10px;text-align:center';document.body.prepend(b)});
const V=V0,keep=e=>{const a=e.target&&e.target.closest&&e.target.closest('a[href]'),h=a&&a.getAttribute('href');if(h&&h[0]==='/'&&(h==='/'||'#?'.indexOf(h[1])>=0||h.indexOf('/history')===0))a.setAttribute('href',V+h)};
['click','auxclick','contextmenu','touchstart','mousedown','focusin'].forEach(k=>addEventListener(k,keep,true))})();${RO}</script>`;
  return html.replace(/<head[^>]*>/i, m => m + s);
}

async function page(name, fw) {
  for (const ref of [fw ? 'v' + fw : null, 'main'].filter(Boolean)) {
    const r = await fetch(REPO + ref + '/firmware/' + name, {cf: {cacheTtl: 3600, cacheEverything: true}});
    if (r.ok) return r.text();
  }
  return null;
}

// ---------- /go: the home-screen shortcut's first page (the same everywhere: never reads a backup)
// Its link carries the backup ID and the Pico's own address after '#', which a browser never sends: the server never
// learns them. Cached for a month, so most opens cost no request at all; only "Last backup" reads the backup.
export const GO = `<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Oil</title>
<link rel=apple-touch-icon href=/icon.png><link rel=icon type=image/png href=/icon.png>
<style>body{font:17px system-ui,sans-serif;margin:0;background:#f4f5f7;color:#1f2937}main{max-width:420px;margin:0 auto;padding:40px 18px}
h1{font-size:24px;margin:0 0 22px}a.b{display:block;text-decoration:none;color:inherit;background:#fff;border-radius:14px;padding:18px 18px;margin:0 0 14px;box-shadow:0 1px 3px #0002}
a.b b{display:block;font-size:20px;margin-bottom:4px}a.b span{color:#6b7280;font-size:15px}a.b.pri{background:#2563eb;color:#fff}a.b.pri span{color:#dbeafe}
p{color:#6b7280;font-size:14px}[hidden]{display:none!important}</style></head><body><main><h1>Oil</h1>
<a class="b pri" id=live hidden><b>Live</b><span>At home (or on your VPN): straight from the monitor</span></a>
<a class=b id=bk hidden><b>Last backup</b><span>Anywhere: the readings as they were at the last backup (up to 8 hours old)</span></a>
<p id=no hidden>This shortcut is missing its details. Make it again from the monitor's page: Config, Notifications, On your phone.</p>
</main><script>
var h=new URLSearchParams(location.hash.slice(1)),id=(h.get('id')||'').toUpperCase(),pico=h.get('pico')||'';
if(/^https?:[/][/][A-Za-z0-9.-]+(:[0-9]{1,5})?$/.test(pico)){document.getElementById('live').href=pico+'/';document.getElementById('live').hidden=false}
if(/^HK-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/.test(id)){document.getElementById('bk').href='/v/'+id;document.getElementById('bk').hidden=false}
if(document.getElementById('live').hidden&&document.getElementById('bk').hidden)document.getElementById('no').hidden=false;
</script></body></html>`;

async function priceh() {  // the older prices every Pico downloads (data/priceh.bin, from GitHub, cached a day)
  const r = await fetch(REPO + 'main/data/priceh.bin', {cf: {cacheTtl: 86400, cacheEverything: true}});
  return r.ok ? new Uint8Array(await r.arrayBuffer()) : null;
}
async function pricehB64() {  // (optional: a failure only leaves the page to ask for it, as before)
  let b = null;
  try { b = await priceh(); } catch (e) { return null; }
  if (!b) return null;
  let s = '';
  for (let i = 0; i < b.length; i += 8192) s += String.fromCharCode(...b.subarray(i, i + 8192));
  return btoa(s);
}

let iconPng = null;
async function icon() {  // the Pico's own home-screen icon (firmware/icon.py, from GitHub; kept once fetched)
  if (iconPng) return iconPng;
  const r = await fetch(REPO + 'main/firmware/icon.py', {cf: {cacheTtl: 604800, cacheEverything: true}});
  if (!r.ok) return null;
  const b64 = [...(await r.text()).matchAll(/'([A-Za-z0-9+/=]+)'/g)].map(m => m[1]).join('');
  const png = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  if (png.length > 100 && png[1] === 0x50) iconPng = png;  // (only a real PNG is kept)
  return png.length > 100 ? png : null;
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
  if (p === '/go') return new Response(GO, {headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'public, max-age=2592000'}});
  if (p === '/icon.png' || p === '/apple-touch-icon.png' || p === '/apple-touch-icon-precomposed.png') {
    const png = await icon();
    return png ? new Response(png, {headers: {'Content-Type': 'image/png', 'Cache-Control': 'public, max-age=604800'}}) : err('not found', 404);
  }
  if (p === '/invite') {
    if (req.method === 'OPTIONS') return new Response(null, {status: 204, headers: cors});
    return inviteName(env, url.searchParams.get('c')) === null ? err('that invite code isn\'t right', 403, cors) : json({ok: true}, 200, cors);
  }
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
    const seg = p.slice(3).split('/')[0], id = okId(seg);
    if (!id || !(await meta(env, id))) return new Response(HOME.replace('<p>', '<p style="color:#b00">Nothing is backed up under that ID.</p><p>'), {status: 404, headers: {'Content-Type': 'text/html'}});
    const rest = p.slice(3 + seg.length);
    if (rest === '') {  // the address to share: on to the pages under it (the cookie only for
      return new Response(null, {status: 302, headers: {'Location': '/v/' + id + '/',  // pages opened at the old addresses)
        'Set-Cookie': `hkv=${id}; Path=/; Max-Age=86400; HttpOnly; Secure; SameSite=Lax`}});
    }
    if (rest[0] !== '/') return err('not found', 404);
    return view(req, env, now, url, id, rest);
  }
  // the old addresses (/, /history, /api/...): the backup opened last in this browser, from the cookie
  return view(req, env, now, url, cookieId(req), p);
}

// Each backup's pages sit under its own /v/<ID>/, so two backups open in two tabs never swap (one cookie for every
// tab did: Conor's Forecast tab showed Stu's, 2026-11-24).
async function view(req, env, now, url, id, p) {
  if (!id) return p === '/' ? new Response(HOME, {headers: {'Content-Type': 'text/html'}}) : err('not found', 404);
  const u = await data(env, id, now);
  if (!u) return new Response(HOME.replace('<p>', '<p style="color:#b00">Nothing is backed up under that ID any more.</p><p>'), {status: 404, headers: {'Content-Type': 'text/html'}});
  if (req.method !== 'GET') return json({});  // read only
  if (p === '/api/prices' && url.searchParams.get('h') === '1') {
    const b = await priceh();
    return bin(b || new Uint8Array(0));
  }
  if (p.startsWith('/api/')) return api(u, p, url.searchParams) || err('not available in a shared view', 404);
  const name = PAGES[p];
  if (!name) return err('not found', 404);
  const t = await page(name, fwOk(u.fw));
  if (t == null) return err('could not fetch the page from GitHub', 502);
  if (name === 'common.js.html') return new Response(t, {headers: {'Content-Type': 'application/javascript'}});
  let html = t;
  const cj = html.includes('<script src="/common.js"></script>') ? await page('common.js.html', fwOk(u.fw)) : null;
  if (cj != null && !/<\/script/i.test(cj)) html = html.replace('<script src="/common.js"></script>', () => '<script>' + cj + '</script>');
  const B = bundle(u, name === 'hist.html' ? await pricehB64() : null);
  return new Response(inject(html, id, u, B), {headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'}});
}

