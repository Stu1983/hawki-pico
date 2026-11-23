"""python3 tests/test_odd_empty.py - the monitor's 'nearly empty' code when the tank isn't (firmware/app.py odd_empty)."""
import ast, os, sys
src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
keep = [n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == 'odd_empty'
        or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in ('EMPTY_NEAR_MM', 'EMPTY_WAIT') for t in n.targets)]
g = {}
exec(compile(ast.Module(keep, []), 'app.py', 'exec'), g)
f, fails = g['odd_empty'], 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


T0 = 1.8e9
tank = {'height_cm': 117}
good = {'level': 867, 'raw': 'g', 'good_at': T0}
ok(f(16382, good, 'e1', tank, T0 + 3600), 'at 26% (867 mm down a 1170 mm tank), an hour after a good reading: a misread')
ok(not f(16382, dict(good, level=1100), 'e1', tank, T0 + 3600), '70 mm above the outlet already: believed')
ok(not f(16382, good, 'e1', tank, T0 + 4 * 3600), 'the last good reading 4 hours ago (a leak, or out of range meanwhile): believed')
bad = {'level': 867, 'bad_level': 16382, 'raw': 'e1', 'good_at': T0}
ok(f(16382, bad, 'e1', tank, T0 + 3600 + 5), '...the same advert again a few seconds later: still set aside')
ok(not f(16382, bad, 'e2', tank, T0 + 2 * 3600), '...the next measurement says so again: believed')
ok(not f(16382, dict(good, level=16382), 'e1', tank, T0 + 3600), 'still nearly empty: believed')
ok(not f(16382, None, 'e1', tank, T0) and not f(16382, {'level': 16383}, 'e1', tank, T0), 'nothing good to judge it by: believed')
ok(not f(16382, good, 'e1', None, T0 + 60) and not f(16382, good, 'e1', {}, T0 + 60), 'tank not set up: believed')
ok(not f(16382, dict(good, good_at=None), 'e1', tank, T0 + 60), 'no time for the last good reading: believed')
ok(not f(867, good, 'x', tank, T0 + 3600), 'an ordinary reading: never')
sys.exit(1 if fails else 0)
