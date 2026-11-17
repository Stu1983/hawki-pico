"""python3 tests/test_reorder.py - the reorder warning needs two low readings in a row (firmware/app.py).

The battery warning waits for 3 readings and the sudden-drop one for 2; the reorder warning went on one, so a
single bad reading (or the sensor's 'nearly empty' code) sent "time to order oil". Adverts repeat each hourly
measurement every 4 s: a reading only counts once, by its payload.
"""
import ast, os

src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
tree = ast.parse(src)
names = ('low_seen', 'low_confirmed')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


g = {}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []),
             'app.py', 'exec'), g)
lc = g.get('low_confirmed')
ok(lc is not None, 'low_confirmed() exists')
if lc:
    M, t = 'c0:04:56:c4:0c:71', 1790000000
    ok(not lc(M, 'aa', True, t), 'one low reading: not yet')
    ok(not lc(M, 'aa', True, t + 60) and not lc(M, 'aa', True, t + 300), 'the same reading repeated (adverts every 4 s): still one')
    ok(lc(M, 'bb', True, t + 3600), 'the next hourly reading low too: warn')
    ok(not lc(M, 'bb', False, t + 3700), 'the same reading no longer low (reorder level lowered, shape changed): not confirmed')
    ok(not lc(M, 'cc', True, t + 7200), '...and counting starts again')
    ok(not lc('other', 'x1', True, t) and lc(M, 'dd', True, t + 10800), 'each tank counts its own')
    S = 'stuck'
    ok(not lc(S, 'zz', True, t) and not lc(S, 'zz', True, t + 3600) and lc(S, 'zz', True, t + 70 * 60), 'a sensor stuck on one low reading: warns after 70 minutes')
al = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'alerts')
ok('low_confirmed(' in ast.unparse(al), 'alerts() asks for two low readings before the reorder warning')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
