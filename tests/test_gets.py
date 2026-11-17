"""python3 tests/test_gets.py - the slow GETs can't be used to stall the Pico (firmware/app.py).

/api/update/check is a blocking HTTPS fetch (seconds, ~40 KB of memory): anyone on the Wi-Fi, or any web page
with <img src="http://pico/api/update/check">, could repeat it. It now answers from a 10-minute cache unless the
signed-in owner asks (and then not more than every 10 s). The Wi-Fi scan blocks too: signed in, or setting up.
"""
import ast, os

src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
tree = ast.parse(src)
names = ('UPD_CACHE_S', 'upd_cache', 'update_check', 'may_setup', 'manifest_fresh')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


clock = [100000]
calls = []


class Updater:
    @staticmethod
    def check(v):
        calls.append(clock[0])
        if Updater.down:
            raise OSError(110, 'ETIMEDOUT')
        return {'current': v, 'latest': '1.2.60', 'newer': True, 'manifest': {'version': '1.2.60'}}
    down = False


import sys
sys.modules['updater'] = Updater
g = {'mono_s': lambda: clock[0], 'with_room': lambda f, *a: f(*a), 'VERSION': '1.2.53', 'manifest': [None],
     'gc': __import__('gc'), 'cfg': {'pin': 'x'}, 'authed': lambda a: a == 'good', 'on_ap': lambda p: p.startswith('192.168.4.')}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []),
             'app.py', 'exec'), g)
ok('update_check' in g, 'update_check() exists')
if 'update_check' in g:
    uc = g['update_check']
    r = uc(False)
    ok(r.get('latest') == '1.2.60' and 'manifest' not in r and g['manifest'][0], 'first check fetches (manifest kept for Install, not sent)')
    clock[0] += 300
    ok(uc(False).get('age') == 300, 'a cached answer says how old it is (the page shows it)')
    clock[0] -= 300
    for i in range(50):
        clock[0] += 5
        uc(False)
    ok(len(calls) == 1, '50 more unsigned checks in 4 minutes: still 1 fetch (%d)' % len(calls))
    clock[0] += 5
    uc(True)
    ok(len(calls) == 2, 'the signed-in owner pressing Check: fetched again')
    uc(True)
    uc(True)
    ok(len(calls) == 2, '...but not more than every 10 s, even signed in')
    clock[0] += 601
    uc(False)
    ok(len(calls) == 3, 'after 10 minutes anyone gets a fresh answer')
    Updater.down = True
    clock[0] += 601
    r = uc(False)
    n = len(calls)
    for i in range(20):
        clock[0] += 5
        uc(False)
    ok(r.get('error') and len(calls) == n, 'internet down: the failure is remembered too, not retried per request')
    ok(g['manifest_fresh']() is False, 'Install after a failed or old check fetches the release again (no stale manifest)')
    Updater.down = False
    clock[0] += 11
    uc(True)
    ok(g['manifest_fresh']() is True, 'Install right after a good check uses it')
ms = g.get('may_setup')
ok(ms and ms('good', '192.168.1.20') and not ms('', '192.168.1.20') and ms('', '192.168.4.2'),
   'Wi-Fi scan: signed in, or from the setup network')
g['cfg'] = {}
ok(ms and ms('', '192.168.1.20'), '...or before any PIN is set (first setup)')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
