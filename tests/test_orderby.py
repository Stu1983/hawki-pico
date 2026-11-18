"""python3 tests/test_orderby.py - Home Assistant's "order by" date is the dashboard's (firmware/app.py + common.js).

The forecast runs in the browser (common.js analyse); the dashboard sends it to the Pico as running totals
(fcBody) and the Pico steps from its own latest reading (order_by). Same reading -> same date as the dashboard's
A.fc.ord, and readings that follow the forecast keep the date where it was. Runs the real page code under node.
"""
import ast, json, os, subprocess, time, types

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
src = open(os.path.join(ROOT, 'firmware', 'app.py')).read()
tree = ast.parse(src)
names = ('forecasts', 'fc_saved', 'FC_FILE', 'num', 'set_forecast', 'order_by', 'REFILL_L', '_level_now', 'MODES', 'mode_of', 'reserve_of', 'active_tanks', 'order_by_iso')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


M = 'c0:04:56:c4:0c:71'
JS = r"""
const fs=require('fs'),vm=require('vm'),ctx={};vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';this.analyse=analyse;this.fcBody=fcBody',ctx);
const DAY=86400,H=3600,now=+process.argv[2],perDay=+process.argv[3],start=+process.argv[4],out=[];
const p=[];let L=start;for(let t=now-60*DAY;t<=now;t+=H){L-=perDay/24*(1+0.3*Math.cos(t/DAY));p.push([t,L])}
const A=ctx.analyse(p,{now,reserve:200});const b=ctx.fcBody(A,process.argv[5],200);
console.log(JSON.stringify({body:b,ord:A.fc.ord,cur:A.cur}));
"""
clock = [0]
saved = []
g = {'time': types.SimpleNamespace(time=lambda: clock[0], gmtime=time.gmtime), 'json': json, 'os': os, 'cfg': {'tanks': {M: {}}},
     'mono_s': lambda: 0}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []),
             'app.py', 'exec'), g)
os.chdir(__import__('tempfile').mkdtemp())


def js(now, per_day, start, key=M):
    r = subprocess.run(['node', '-e', JS, os.path.join(ROOT, 'firmware', 'common.js.html'), str(now), str(per_day), str(start), key],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


try:
    subprocess.run(['node', '-v'], capture_output=True, check=True)
    have_node = True
except Exception:
    have_node = False
    print('skip: node not installed (the same-date checks need the page code)')

if have_node:
    now = 1795400000
    for per_day, start in ((8, 900), (3, 900), (15, 1100), (6, 600)):
        d = js(now, per_day, start)
        clock[0] = now
        g['set_forecast'](dict(d['body']))
        f = g['forecasts'][M]
        got = g['order_by'](f, f['cur'], f['t0'], 200)
        ok(got is not None and d['ord'] is not None and abs(got - d['ord']) < 1, '%d L/day from %d L: the Pico\'s date %s = the dashboard\'s %s' % (
            per_day, start, got and time.strftime('%d %b %Y %H:%M', time.gmtime(got)),
            d['ord'] and time.strftime('%d %b %Y %H:%M', time.gmtime(d['ord']))))
        if d['ord'] and d['ord'] - d['body']['t0'] > 6 * 86400:  # five days on, used as forecast: same date
            cum = d['body']['cum']
            later = g['order_by'](f, f['cur'] - cum[4], f['t0'] + 5 * 86400, 200)
            ok(later is not None and abs(later - d['ord']) < 1, '   five days on, used as forecast: still %s' % (later and time.strftime('%d %b', time.gmtime(later))))
    d = js(now, 8, 900, 'all')
    g['set_forecast'](dict(d['body']))
    f = g['forecasts']['all']
    ok(abs(g['order_by'](f, f['cur'], f['t0'], 200) - d['ord']) < 1, 'the all-tanks forecast too')

# what the Pico accepts
clock[0] = 1795400000
good = {'mac': M, 't0': clock[0] - 3600, 'cur': 500, 'reserve': 200, 'cum': [5.0 * (i + 1) for i in range(400)]}
for label, b in (('an unknown tank', dict(good, mac='aa:aa:aa:aa:aa:aa')), ('a time 5 days old', dict(good, t0=clock[0] - 5 * 86400)),
                 ('running totals going down', dict(good, cum=[10, 5])), ('more than 400 days', dict(good, cum=list(range(401)))),
                 ('not numbers', dict(good, cum=['x'])), ('a negative total', dict(good, cum=[-5]))):
    try:
        g['set_forecast'](b)
        ok(False, 'refused: ' + label)
    except (ValueError, KeyError, TypeError):
        ok(True, 'refused: ' + label)
g['set_forecast'](good)
f = g['forecasts'][M]
ok(type(f['t0']) is int and 'reserve' not in f, 'kept with an int time; the posted reorder level is never used (the Pico\'s own)')
ok(g['order_by'](f, 150, clock[0], 200) == clock[0], 'already at or below the reorder level: today')
ok(g['order_by'](f, 99999, clock[0], 200) is None, 'not within 400 days: no date')
ok(g['order_by'](f, 500, f['t0'] + 401 * 86400, 200) is None, 'a reading after the 400 days the forecast covers: no date (no error)')
ok(g['order_by'](f, None, clock[0], 200) is None, 'no reading: no date')
# the Pico's own start level once newer readings came in: like the dashboard's (median of 3, none before a delivery)
g['hist_tail'] = lambda mac, n: [(1, 800), (2, 790), (3, 795), (4, 600)][-n:]
g['reading'] = lambda t, mm: (1300 - mm, None)
ok(g['_level_now'](M, {}) == (700, 4), 'a level that rose by a delivery (500 -> 700 L): the newest reading only')
g['hist_tail'] = lambda mac, n: [(1, 800), (2, 790), (3, 799), (4, 801)][-n:]
ok(g['_level_now'](M, {}) == (501, 4), 'otherwise the median of the last 3 (one noisy reading doesn\'t move it)')
# order_by_iso: off tanks get no date; the newest forecast wins; the reorder level is the tank's own
A2 = 'c6:76:1b:dc:39:1c'
g['cfg']['tanks'] = {M: {'reserve_l': 200}, A2: {'reserve_l': 200, 'mode': 'off'}}
g['level_now'] = lambda m, t: {M: (400.0, clock[0] + 7200), A2: (5.0, clock[0] + 7200)}[m]
g['forecasts'].clear()
g['forecasts'][M] = {'t0': clock[0], 'cur': 410, 'cum': [10.0 * (i + 1) for i in range(400)], 'at': 1}
iso = g['order_by_iso'](M, g['cfg']['tanks'][M])
ok(iso and iso.endswith('+00:00'), 'a tank in use with its own forecast: a date (%s)' % iso)
g['forecasts'][A2] = dict(g['forecasts'][M])
ok(g['order_by_iso'](A2, g['cfg']['tanks'][A2]) is None, 'an off tank: no date, even with a forecast kept from before')
g['forecasts']['all'] = {'t0': clock[0], 'cur': 405, 'cum': [1.0 * (i + 1) for i in range(400)], 'at': 2, 'tanks': [M]}
later = g['order_by_iso'](M, g['cfg']['tanks'][M])
ok(later and later > iso, 'a newer all-tanks forecast wins over an older one of its own (%s)' % later)
g['cfg']['tanks'][M]['reserve_l'] = 395
ok(g['order_by_iso'](M, g['cfg']['tanks'][M]) < later, 'the tank\'s own reorder level is used')
g['cfg']['tanks'][M]['reserve_l'] = 200
g['cfg']['tanks'][A2]['mode'] = 'standby'  # Tank 2 back in: the all-tanks forecast was made without it
ok(g['order_by_iso'](M, g['cfg']['tanks'][M]) == iso, 'a tank switched back in: the old all-tanks forecast no longer applies')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
