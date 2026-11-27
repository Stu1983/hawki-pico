"""python3 tests/test_cfgview.py - every tank setting set_tank() stores reaches the pages (firmware/app.py cfg_view).

The pages fill the tank form, the dashboard and the backup from /api/state's `cfg`, so a setting that
set_tank() keeps but cfg_view() leaves out is lost on the next save and missing from every backup.
"""
import ast, os

src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'core.py')).read()
tree = ast.parse(src)
want = {'cfg_view', 'isolated_since'}
code = ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want
                   or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in ('CFG_KEYS', 'MEASURED_KEYS')
                                                         for t in n.targets)], [])
import time
g = {'_equiv': {}, 'tank_equiv': lambda t: None, 'time': time}
exec(compile(code, 'app.py', 'exec'), g)
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


# keys set_tank() writes into the stored tank: t['x'] = ..., t = {'x': ...}, and the MEASURED_KEYS loop
st = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'set_tank')
stored = set()
for n in ast.walk(st):
    if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) and getattr(n.value, 'id', '') == 't' \
            and isinstance(n.slice, ast.Constant):
        stored.add(n.slice.value)
    if isinstance(n, ast.Assign) and any(getattr(x, 'id', '') == 't' for x in n.targets) and isinstance(n.value, ast.Dict):
        stored |= {k.value for k in n.value.keys if isinstance(k, ast.Constant)}
stored.discard('name')  # sent as the tank's own field, not inside cfg
missing = sorted(stored - set(g['CFG_KEYS']))
ok(not missing, 'every setting set_tank() stores is in CFG_KEYS (missing: %s)' % missing)
ok('group' in g['CFG_KEYS'], "link()'s group is shown too")

c = g['cfg_view']({'tank_l': 1306, 'isolated': True})
ok(c.get('isolated') is True, 'an isolated tank says so in /api/state')
ok(g['cfg_view']({'tank_l': 1306}).get('isolated') in (None, False), 'a tank in use is not isolated')

iso = g['isolated_since']
now = int(time.time())
ok(abs(iso(True, None) - now) <= 2, 'ticking the box stamps it with now')
ok(iso(True, 1790000000) == 1790000000, 're-saving the form keeps when it was isolated')
ok(iso(1780000000, None) == 1780000000, 'a backup brings its own time')
ok(iso(True, True) == now or abs(iso(True, True) - now) <= 2, 'older setting (true) gets a time on its next save')
ok(abs(iso(now + 10 * 86400, None) - now) <= 2 and abs(iso(5, None) - now) <= 2, 'absurd times are not trusted')
ok(type(iso(True, None)) is int, 'an int (never a float: single precision on the Pico)')

class Unset:  # just after boot, before NTP: the clock says 2021
    @staticmethod
    def time():
        return 1610000000
g['time'] = Unset
ok(iso(True, 1790000000) == 1790000000, 'clock not set yet: a saved isolation time is kept')
ok(iso(1780000000, None) == 1780000000, 'clock not set yet: a backup time is kept')
ok(iso(True, None) is True, 'clock not set yet, newly isolated: true (since ever) rather than a wrong time')
g['time'] = time

print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
