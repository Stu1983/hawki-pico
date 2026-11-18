// HAWKi oil widget for Scriptable (iPhone / iPad): the oil left, % full and the "order by" date on the home or lock screen.
// How to set it up: see "iPhone widget" in the README. Tapping the widget opens the monitor's page.
// The monitor's address: put it in the widget's Parameter (long-press the widget, Edit Widget), or change PICO below.
// It only reaches the monitor on your home Wi-Fi; away from home it shows the last figures it got, and when they're from.

const PICO = ((args.widgetParameter || '').trim() || 'http://hawki-pico.local').replace(/\/+$/, '');
const fm = FileManager.local();
const CACHE = fm.joinPath(fm.documentsDirectory(), 'hawki-widget.json');

const DIM = Color.dynamic(new Color('#6b7385'), new Color('#9aa3b5'));
const FG = Color.dynamic(new Color('#1d2433'), new Color('#e8ebf1'));
const OIL = new Color('#c9a43f');
const WARN = new Color('#c98a1a');
const BAD = Color.dynamic(new Color('#c4423b'), new Color('#ff7a70'));
const TRACK = Color.dynamic(new Color('#e2e5ea'), new Color('#2b3240'));

async function fetchState() {
  const r = new Request(PICO + '/api/state');
  r.timeoutInterval = 8;
  return await r.loadJSON();
}

const modeOf = c => (c && c.mode) || (c && c.isolated ? 'standby' : 'use');

// What to show: the tank picked for the dashboard, or every tank not switched off added together. Chosen before
// looking at the readings: a tank with none yet is said, never quietly swapped for another or left out of a total.
function pick(s) {
  const one = (s.tanks || []).find(t => t.mac === s.primary);  /* (the one picked: shown even if switched off, as the dashboard does) */
  const tanks = (s.tanks || []).filter(t => modeOf(t.cfg) !== 'off');
  if (!one && !tanks.length) return null;
  const shown = one ? [one] : s.primary === 'all' || tanks.length > 1 ? tanks : [tanks[0]];
  const name = shown.length > 1 ? shown.length + ' tanks' : shown[0].name;
  if (shown.some(t => t.litres == null)) return { name, litres: null };
  const litres = shown.reduce((a, t) => a + t.litres, 0);
  const cap = t => +(t.cfg && t.cfg.capacity_l) || (t.percent ? t.litres * 100 / t.percent : 0);  /* (as the dashboard: the set capacity) */
  const full = shown.reduce((a, t) => a + cap(t), 0);
  const orders = shown.map(t => t.order_by).filter(Boolean).sort();
  const ages = shown.map(t => t.age).filter(a => a != null);
  return {
    name,
    litres: Math.round(litres),
    percent: full > 0 ? Math.round(litres * 100 / full) : null,
    orderBy: orders.length ? new Date(orders[0]) : null,
    age: ages.length ? Math.max(...ages) : null,
  };
}

function ago(secs) {
  if (secs == null) return '';
  if (secs < 90) return 'just now';
  if (secs < 5400) return Math.round(secs / 60) + ' min ago';
  if (secs < 129600) return Math.round(secs / 3600) + ' h ago';
  return Math.round(secs / 86400) + ' days ago';
}

function orderText(d) {
  if (!d) return { text: '', color: DIM };
  const days = Math.floor((d - new Date()) / 86400000);
  const when = d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
  if (days < 0) return { text: 'Order now', color: BAD };
  return { text: 'Order by ' + when, color: days <= 7 ? BAD : days <= 21 ? WARN : DIM };
}

function asOf(d) {
  const now = new Date(), hm = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  if (d.toDateString() === now.toDateString()) return 'as of ' + hm;
  if (now - d < 6 * 86400000) return 'as of ' + d.toLocaleDateString('en-GB', { weekday: 'short' }) + ' ' + hm;
  return 'as of ' + d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

function bar(percent, w, h) {
  const dc = new DrawContext();
  dc.size = new Size(w, h);
  dc.opaque = false;
  dc.respectScreenScale = true;
  const p = new Path();
  p.addRoundedRect(new Rect(0, 0, w, h), h / 2, h / 2);
  dc.addPath(p);
  dc.setFillColor(TRACK);
  dc.fillPath();
  const fw = Math.max(h, Math.min(1, (percent || 0) / 100) * w);
  const f = new Path();
  f.addRoundedRect(new Rect(0, 0, fw, h), h / 2, h / 2);
  dc.addPath(f);
  dc.setFillColor(OIL);
  dc.fillPath();
  return dc.getImage();
}

function text(stack, s, size, color, bold) {
  const t = stack.addText(s);
  t.font = bold ? Font.boldSystemFont(size) : Font.systemFont(size);
  t.textColor = color;
  t.lineLimit = 1;
  t.minimumScaleFactor = 0.6;
  return t;
}

function build(v, stale, err) {
  const fam = config.widgetFamily || 'small';
  const w = new ListWidget();
  w.url = PICO + '/';
  w.refreshAfterDate = new Date(Date.now() + 15 * 60000);
  if (!v) {
    if (fam.startsWith('accessory')) { text(w, err ? 'Oil: no reading' : 'Oil: no tanks', 12, FG, false); return w; }
    text(w, 'Oil', 13, DIM, true);
    w.addSpacer(6);
    text(w, err ? "Can't reach the monitor" : 'No tanks added yet', 14, FG, true);
    w.addSpacer(4);
    text(w, err ? 'On your home Wi-Fi? ' + PICO.replace('http://', '') : 'Add one on its page', 11, DIM, false);
    return w;
  }
  if (v.litres == null) {
    if (fam.startsWith('accessory')) { text(w, 'Oil: no reading yet', 12, FG, false); return w; }
    text(w, 'Oil', 13, DIM, true);
    w.addSpacer(6);
    text(w, v.name, 14, FG, true);
    w.addSpacer(4);
    text(w, 'No reading yet', 12, DIM, false);
    return w;
  }
  const o = orderText(v.orderBy);
  const pc = v.percent != null ? v.percent + '%' : '';
  const when = stale ? asOf(stale) : 'read ' + ago(v.age);
  if (fam === 'accessoryInline') { text(w, 'Oil ' + v.litres + ' L · ' + (stale ? asOf(stale) : pc), 12, FG, false); return w; }
  if (fam === 'accessoryCircular') {
    text(w, String(v.litres), 14, FG, true); text(w, stale ? 'old' : 'L', 10, FG, false); return w;
  }
  if (fam === 'accessoryRectangular') {
    text(w, 'Oil ' + v.litres + ' L' + (pc ? '  ' + pc : ''), 14, FG, true);
    text(w, o.text || v.name, 11, FG, false);
    text(w, when, 10, FG, false);
    return w;
  }
  const head = w.addStack();
  text(head, 'Oil', 13, DIM, true);
  head.addSpacer();
  text(head, v.name, 11, DIM, false);
  w.addSpacer(4);
  const big = w.addStack();
  big.bottomAlignContent();
  text(big, String(v.litres), fam === 'small' ? 30 : 34, FG, true);
  text(big, ' L', 15, DIM, true);
  big.addSpacer();
  if (pc) text(big, pc, 15, FG, true);
  w.addSpacer(6);
  const img = w.addImage(bar(v.percent, fam === 'small' ? 130 : 290, 8));
  img.imageSize = new Size(fam === 'small' ? 130 : 290, 8);
  w.addSpacer(8);
  if (o.text) text(w, o.text, 12, o.color, true);
  w.addSpacer();
  text(w, when, 10, stale ? WARN : DIM, false);
  return w;
}

let v = null, stale = null, err = null;
try {
  const s = await fetchState();
  v = pick(s);
  fm.writeString(CACHE, JSON.stringify({ at: Date.now(), pico: PICO, v }));
} catch (e) {
  err = e;
  try {
    const c = JSON.parse(fm.readString(CACHE));
    if (c && c.v && c.pico === PICO) {  // (only this monitor's figures, never another's)
      v = c.v;
      if (v.orderBy) v.orderBy = new Date(v.orderBy);
      stale = new Date(c.at);
    }
  } catch (e2) { /* nothing kept yet */ }
}
const widget = build(v, stale, err);
if (config.runsInWidget) Script.setWidget(widget);
else await widget.presentSmall();
Script.complete();
