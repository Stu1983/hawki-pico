"""python3 tests/test_tankmaths.py - tank_view's litres maths is worked out once per level and settings (firmware/app.py).

/api/state (every page poll) and MQTT (every 10 s) both call tank_view; for a measured tank that was ~5 model
builds each time (25 us on CPython, far more on the Pico, and short-lived objects churning its heap).
"""
import ast, os, sys

FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.insert(0, FW)
import tankcalc

src = open(os.path.join(FW, 'core.py')).read()
tree = ast.parse(src)
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


calls = [0]


def reading(t, lvl):
    calls[0] += 1
    return tankcalc.reading(t, lvl)


g = {'reading': reading, 'total': tankcalc.total, 'below': tankcalc.below, 'cfg_gen': [0]}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('tank_maths', 'unusable')
                         or isinstance(n, ast.Assign) and any(getattr(x, 'id', '') == '_tm' for x in n.targets)], []), 'app.py', 'exec'), g)
M = 'c0:04:56:c4:0c:71'
t = {'shape': 'cuboid', 'height_cm': 123, 'outlet_cm': 9.5, 'length_cm': 173, 'width_cm': 69, 'tank_l': 1306, 'capacity_l': 1180,
     'windows': 2, 'window_model': 'measured', 'win_bottom_cm': 45, 'win_top_cm': 79, 'win_outer_w_cm': 39, 'win_inner_w_cm': 17,
     'win_inner_h_cm': 14, 'ribs_cm': [31.5, 62.5, 93.5], 'rib_h_cm': 12, 'rib_depth_cm': 1.5}
a = g['tank_maths'](M, t, 700)
n = calls[0]
for _ in range(20):
    b = g['tank_maths'](M, t, 700)
ok(b == a and calls[0] == n, '20 more polls at the same level: worked out once (%d model readings)' % calls[0])
ok(a[0] == tankcalc.reading(t, 700)[0] and a[5] and a[5][1] == 'estimate', 'the same figures as before (%s L, unusable %s)' % (a[0], a[5]))
g['tank_maths'](M, t, 705)
ok(calls[0] > n, 'a new reading: worked out again')
n = calls[0]
t['tank_l'] = 1400
g['cfg_gen'][0] += 1  # (save_cfg counts every settings change)
c = g['tank_maths'](M, t, 705)
ok(calls[0] > n and c[0] != a[0], 'settings changed: worked out again (%s L)' % c[0])
ok(g['tank_maths'](M, t, None)[0] is None, 'no level: nothing to work out')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
