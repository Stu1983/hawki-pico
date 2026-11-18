// node tests/tests_widget.js  - the Scriptable widget (tools/hawki-widget.js), run against stand-ins for Scriptable's
// classes: what it shows for one tank, several, a tank switched off, no tanks, the monitor out of reach (the last figures,
// marked as old), the order-by colours, the lock-screen sizes, and the address from the widget's parameter.
const fs = require('fs'), path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'tools', 'hawki-widget.js'), 'utf8');
let fails = 0; const ok = (c, m) => { console.log((c ? 'ok   ' : 'FAIL ') + m); if (!c) fails++ };

function run({ state, fail, family = 'small', param = '', cache = null, now = Date.parse('2026-11-18T12:00:00Z') }) {
  const texts = [], files = { ...(cache ? { '/docs/hawki-widget.json': cache } : {}) }, asked = [];
  class Color { constructor(h) { this.hex = h } static dynamic(a) { return a } }
  class Stack {
    constructor() { this.items = [] }
    addText(s) { const t = { s, textColor: null }; texts.push(t); this.items.push(t); return t }
    addStack() { const k = new Stack(); this.items.push(k); return k }
    addSpacer() {} bottomAlignContent() {}
    addImage(i) { return { i } }
  }
  class ListWidget extends Stack {}
  const env = {
    args: { widgetParameter: param }, config: { widgetFamily: family, runsInWidget: true },
    FileManager: { local: () => ({ documentsDirectory: () => '/docs', joinPath: (a, b) => a + '/' + b,
      writeString: (p, s) => { files[p] = s }, readString: p => { if (!(p in files)) throw new Error('none'); return files[p] } }) },
    Request: class { constructor(u) { asked.push(u) } async loadJSON() { if (fail) throw new Error('The request timed out.'); return state } },
    Color, ListWidget, Font: { systemFont: n => n, boldSystemFont: n => n },
    Size: class {}, Rect: class {}, Path: class { addRoundedRect() {} },
    DrawContext: class { addPath() {} setFillColor() {} fillPath() {} getImage() { return {} } },
    Script: { setWidget(w) { env.out = w }, complete() {} },
  };
  const RealDate = Date;
  global.Date = class extends RealDate { constructor(...a) { super(...(a.length ? a : [now])) } static now() { return now } };
  const fn = new (Object.getPrototypeOf(async function () {}).constructor)(...Object.keys(env), src);
  return fn(...Object.values(env)).then(() => { global.Date = RealDate; return { texts, out: env.out, files, asked, all: texts.map(t => t.s).join(' | ') } });
}

const tank = (o) => Object.assign({ mac: 'aa:bb:cc:00:00:01', name: 'Tank 1', litres: 611.4, percent: 46, age: 720, order_by: '2026-12-29T09:00:00+00:00', cfg: {} }, o);
(async () => {
  let r = await run({ state: { primary: 'aa:bb:cc:00:00:01', tanks: [tank()] } });
  ok(/611/.test(r.all) && /46%/.test(r.all) && /Tank 1/.test(r.all), 'one tank: litres, % and its name (' + r.all + ')');
  ok(/Order by Tue 29 Dec/.test(r.all) && /read 12 min ago/.test(r.all), '...the order-by date and how old the reading is');
  ok(r.asked[0] === 'http://hawki-pico.local/api/state' && r.out.url === 'http://hawki-pico.local/', 'asks hawki-pico.local; a tap opens the page');
  ok(JSON.parse(r.files['/docs/hawki-widget.json']).v.litres === 611, 'keeps the figures for when it can\'t reach the monitor');

  r = await run({ state: { primary: 'all', tanks: [tank(), tank({ mac: 'b', name: 'Tank 2', litres: 300, percent: 25, order_by: '2026-12-20T09:00:00+00:00' })] } });
  ok(/2 tanks/.test(r.all) && /911/.test(r.all) && /Order by Sun 20 Dec/.test(r.all), 'both tanks on the dashboard: added together, the earlier order date (' + r.all + ')');
  ok(/ 36% /.test(' '+r.texts.map(t=>t.s).join(' ')+' '), '...% of the two together, 911 of 2,529 L (' + r.all + ')');

  r = await run({ state: { primary: 'all', tanks: [tank(), tank({ mac: 'b', name: 'Tank 2', litres: 900, cfg: { mode: 'off' } })] } });
  ok(/611/.test(r.all) && !/1511/.test(r.all), 'a tank switched off is left out (' + r.all + ')');

  r = await run({ state: { primary: 'all', tanks: [tank({ litres: 0, percent: 0, cfg: { capacity_l: 1000 } }), tank({ mac: 'b', name: 'Tank 2', litres: 500, percent: 50, cfg: { capacity_l: 1000 } })] } });
  ok(/ 25% /.test(' ' + r.texts.map(t => t.s).join(' ') + ' '), 'an empty tank still counts towards the % (0 + 500 of 2,000 L: 25%) (' + r.all + ')');
  r = await run({ state: { primary: 'aa:bb:cc:00:00:01', tanks: [tank({ litres: null, percent: null }), tank({ mac: 'b', name: 'Tank 2', litres: 500 })] } });
  ok(/Tank 1/.test(r.all) && /No reading yet/.test(r.all) && !/500/.test(r.all), 'the chosen tank has no reading yet: says so, never shows another (' + r.all + ')');
  r = await run({ state: { primary: 'all', tanks: [tank({ litres: null }), tank({ mac: 'b', name: 'Tank 2', litres: 500 })] } });
  ok(/2 tanks/.test(r.all) && /No reading yet/.test(r.all), 'all tanks, one without a reading: no part-total passed off as the whole (' + r.all + ')');
  r = await run({ state: { primary: null, tanks: [] } });
  ok(/No tanks added yet/.test(r.all), 'no tanks: says so');

  const cache = JSON.stringify({ pico: 'http://hawki-pico.local', at: Date.parse('2026-11-18T08:30:00Z'), v: { name: 'Tank 1', litres: 615, percent: 47, orderBy: '2026-12-29T09:00:00.000Z', age: 60 } });
  r = await run({ fail: true, cache });
  const asOf = r.texts.find(t => /as of/.test(t.s));
  ok(/615/.test(r.all) && asOf && asOf.textColor.hex === '#c98a1a', 'out of reach: the last figures, marked "as of" in amber (' + r.all + ')');
  const old = JSON.stringify({ pico: 'http://hawki-pico.local', at: Date.parse('2026-11-16T08:30:00Z'), v: { name: 'Tank 1', litres: 640, percent: 49, orderBy: null, age: 60 } });
  r = await run({ fail: true, cache: old });
  ok(/as of Mon 08:30/.test(r.all), 'old figures from earlier in the week: the day too (' + r.all + ')');
  r = await run({ fail: true, cache: JSON.stringify({ pico: 'http://hawki-pico.local', at: Date.parse('2026-11-01T08:30:00Z'), v: { name: 'Tank 1', litres: 700, percent: 53, age: 60 } }) });
  ok(/as of 1 Nov/.test(r.all), 'older still: the date (' + r.all + ')');
  r = await run({ fail: true, cache: old, param: 'http://192.168.1.99' });
  ok(/Can't reach the monitor/.test(r.all) && !/640/.test(r.all), 'another monitor\'s address: never shows the figures kept for this one (' + r.all + ')');
  r = await run({ fail: true, cache: old, family: 'accessoryInline' });
  ok(/as of Mon/.test(r.all), 'lock screen, one line, old figures: says how old (' + r.all + ')');
  r = await run({ fail: true, cache: old, family: 'accessoryCircular' });
  ok(/old/.test(r.all), 'lock screen, round, old figures: marked "old" (' + r.all + ')');
  r = await run({ state: { primary: 'aa:bb:cc:00:00:01', tanks: [tank({ cfg: { mode: 'off' } }), tank({ mac: 'b', name: 'Tank 2', litres: 500 })] } });
  ok(/Tank 1/.test(r.all) && /611/.test(r.all), 'the tank picked on the dashboard, though switched off: still that one, as the dashboard shows (' + r.all + ')');
  r = await run({ fail: true });
  ok(/Can't reach the monitor/.test(r.all) && /home Wi-Fi/.test(r.all), 'out of reach with nothing kept: says so, and to check the home Wi-Fi');

  for (const [ob, want, colour] of [['2026-11-25T09:00:00+00:00', /Order by/, '#c4423b'], ['2026-12-05T09:00:00+00:00', /Order by/, '#c98a1a'], ['2026-11-10T09:00:00+00:00', /Order now/, '#c4423b']]) {
    r = await run({ state: { primary: 'aa:bb:cc:00:00:01', tanks: [tank({ order_by: ob })] } });
    const t = r.texts.find(x => /Order/.test(x.s));
    ok(t && want.test(t.s) && t.textColor.hex === colour, ob.slice(0, 10) + ': "' + (t && t.s) + '" in ' + colour);
  }
  r = await run({ state: { primary: 'aa:bb:cc:00:00:01', tanks: [tank({ order_by: null })] } });
  ok(!/Order/.test(r.all), 'no forecast yet (the dashboard not opened): no order-by line');

  r = await run({ state: { primary: 'aa:bb:cc:00:00:01', tanks: [tank()] }, family: 'accessoryRectangular' });
  ok(r.texts.length === 3 && /Oil 611 L/.test(r.texts[0].s) && /Order by/.test(r.texts[1].s), 'lock screen (rectangular): three short lines (' + r.all + ')');
  r = await run({ state: { primary: 'aa:bb:cc:00:00:01', tanks: [tank()] }, family: 'accessoryInline' });
  ok(r.texts.length === 1 && r.texts[0].s === 'Oil 611 L · 46%', 'lock screen (one line): "' + r.texts[0].s + '"');
  r = await run({ state: { primary: 'aa:bb:cc:00:00:01', tanks: [tank()] }, param: ' http://192.168.1.57/ ' });
  ok(r.asked[0] === 'http://192.168.1.57/api/state' && r.out.url === 'http://192.168.1.57/', 'an address in the widget\'s parameter is used, tidied');
  process.exit(fails ? 1 : 0);
})();
