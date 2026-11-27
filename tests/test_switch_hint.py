"""python3 tests/test_switch_hint.py - "looks like you've switched to Tank 2" (firmware/app.py switch_hint).

The tank in use has held steady for a day while a standby tank went down: the valves were probably switched.
Only ever a hint (the page offers to open that tank's settings); never when anything is unclear.
"""
import ast, os, struct, sys, tempfile, time

FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.insert(0, FW)
import tankcalc

src = open(os.path.join(FW, 'core.py')).read()
tree = ast.parse(src)
names = ('MODES', 'mode_of', 'hist_name', 'hist_tail', 'fell_in_a_day', 'SWITCH_FELL_L', 'SWITCH_STEADY_L', '_hint', 'cfg_gen', 'switch_hint')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


A1, A2 = 'c0:04:56:c4:0c:71', 'c6:76:1b:dc:39:1c'
T = {'shape': 'cuboid', 'height_cm': 123, 'length_cm': 173, 'width_cm': 69, 'capacity_l': 1180, 'outlet_cm': 9.5}
os.chdir(tempfile.mkdtemp())
g = {'os': os, 'struct': struct, 'time': time, 'reading': tankcalc.reading, 'print': lambda *a: None,
     'cfg': {'tanks': {}}}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []),
             'app.py', 'exec'), g)
g['saved_last'] = lambda m: g['hist_tail'](m, 1)[-1:] and tuple(g['hist_tail'](m, 1)[-1])
NOW = int(time.time())


def write(mac, start_mm, mm_per_h, hours=40, last_age=600):
    with open(g['hist_name'](mac), 'wb') as f:
        for i in range(hours):
            f.write(struct.pack('<IH', NOW - last_age - (hours - 1 - i) * 3600, int(start_mm + mm_per_h * i)))


def hint(m1='use', m2='standby', since2=None, extra=None):
    g['cfg']['tanks'] = {A1: dict(T, name='Tank 1', **({} if m1 == 'use' else {'mode': m1})),
                         A2: dict(T, name='Tank 2', **({} if m2 == 'use' else {'mode': m2, 'isolated': since2 or 1700000000}))}
    if extra:
        g['cfg']['tanks'].update(extra)
    g['_hint'][0] = None
    return g['switch_hint'](NOW)


write(A1, 700, 0)          # tank 1 flat
write(A2, 300, 0.5)        # tank 2 going down ~12 mm a day (~12 L)
h = hint()
print('   ', h)
ok(h and h['from'] == A1 and h['to'] == A2 and h['fell'] >= 8, 'Tank 1 steady, standby Tank 2 going down: hint to switch')
write(A1, 700, 0.5)
ok(hint() is None, 'Tank 1 going down too: no hint')
write(A1, 700, 0)
write(A2, 300, 0)
ok(hint() is None, 'Tank 2 steady too: no hint')
write(A2, 300, 0.5, last_age=5 * 3600)
ok(hint() is None, 'Tank 2 not heard for 5 hours: no hint')
write(A2, 300, 0.5, hours=20)
ok(hint() is None, 'less than a day of readings: no hint')
write(A2, 300, 0.5)
ok(hint('use', 'use') is None, 'both in use: no hint (nothing to switch)')
ok(hint('use', 'off') is None, 'Tank 2 off: no hint')
ok(hint('standby', 'standby') is None, 'nothing in use: no hint')
jit = [700, 705, 700, 705, 700]  # 5 mm jitter on the steady tank
with open(g['hist_name'](A1), 'wb') as f:
    for i in range(40):
        f.write(struct.pack('<IH', NOW - 600 - (39 - i) * 3600, jit[i % 5]))
ok(hint() is not None, 'a steady tank that jitters by one 5 mm step still counts as steady')
# Codex's cases
write(A1, 700, 0)
write(A2, 300, 0.5)
ok(hint(since2=NOW - 3 * 3600) is None, 'Tank 2 only went on standby 3 hours ago: its use before then is not "going down on standby"')
ok(hint(since2=NOW - 30 * 3600) is not None, '...on standby for 30 hours and still going down: hint')
with open(g['hist_name'](A1), 'wb') as f:  # a delivery into the tank in use: 300 mm up in its last readings
    for i in range(40):
        f.write(struct.pack('<IH', NOW - 600 - (39 - i) * 3600, 700 if i < 34 else 400))
ok(hint() is None, 'a delivery into the tank in use is not "steady"')
write(A1, 700, 0)
with open(g['hist_name'](A2), 'wb') as f:  # flat, then a jitter and one misread among the last readings
    for i, mm in enumerate([300] * 35 + [300, 305, 400, 310, 300]):
        f.write(struct.pack('<IH', NOW - 600 - (39 - i) * 3600, mm))
ok(hint() is None, 'one misread among the latest readings does not tip it')
A3 = 'aa:bb:cc:dd:ee:03'
write(A2, 300, 0.5)
write(A3, 300, 0.5)
ok(hint(extra={A3: dict(T, name='Tank 3', mode='standby', isolated=1700000000)}) is None, 'two standby tanks going down: no hint (can\'t tell which)')
write(A2, 300, 0.5)
g['_hint'][0] = None
g['cfg']['tanks'] = {A1: dict(T, name='Tank 1'), A2: dict(T, name='Tank 2', mode='standby', isolated=1700000000)}
h1 = g['switch_hint'](NOW)
g['cfg']['tanks'][A2]['capacity_l'] = 100  # a much smaller tank: 12 mm is far fewer litres
g['cfg_gen'][0] += 1                         # (save_cfg counts it)
ok(h1 is not None and g['switch_hint'](NOW) is None, 'a changed tank size works the hint out again')
os.remove(g['hist_name'](A2))
ok(hint() is None, 'no history file: no hint, no error')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
