"""python3 tests/test_modes.py - tank modes: In use / Standby / Off (firmware/app.py set_tank, mode_of, reorder_alert).

Like failover states: the tank in use warns; a standby tank's oil counts but it never warns of its own; an off
tank is left out. When the tank in use reaches its reorder level and a standby tank still has oil: "switch to"
it; "order oil" only when there is no oil waiting.
"""
import ast, os, sys, time

FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.insert(0, FW)
import tankcalc

src = open(os.path.join(FW, 'app.py')).read()
tree = ast.parse(src)
names = ('MODES', 'MEASURED_KEYS', 'CFG_KEYS', 'isolated_since', 'num', 'set_tank', 'mode_of', 'reserve_of', 'reorder_alert', 'cfg_view')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


A1, A2 = 'c0:04:56:c4:0c:71', 'c6:76:1b:dc:39:1c'
g = {'time': time, 'cfg': {'tanks': {}}, 'hawki': {A1: {'level': 700}, A2: {'level': 700}}, 'save_cfg': lambda c: None,
     'SHAPES': tankcalc.SHAPES, 'link': tankcalc.link, 'above': tankcalc.above, 'reading': tankcalc.reading,
     '_equiv': {}, 'tank_equiv': lambda t: None}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []),
             'app.py', 'exec'), g)
base = {'shape': 'cuboid', 'height_cm': 123, 'length_cm': 173, 'width_cm': 69, 'tank_l': 1306, 'outlet_cm': 9.5, 'reserve_l': 200}


def save(mac, **k):
    g['set_tank'](dict(base, mac=mac, name='Tank 1' if mac == A1 else 'Tank 2', **k))
    return g['cfg']['tanks'][mac]


t1 = save(A1)
ok(g['mode_of'](t1) == 'use' and 'mode' not in t1, 'a tank is in use unless told otherwise')
t2 = save(A2, mode='off')
ok(t2['mode'] == 'off' and type(t2['isolated']) is int, 'off: saved, with the time it stopped being in use')
since = t2['isolated']
t2 = save(A2, mode='standby')
ok(t2['mode'] == 'standby' and t2['isolated'] == since, 'off -> standby keeps the time it stopped being in use')
t2 = save(A2, isolated=True)
ok(g['mode_of'](t2) == 'standby', 'the old Isolated tick (no mode) means standby')
g['cfg']['tanks'][A2] = dict(t2)
g['cfg']['tanks'][A2].pop('mode')
ok(g['mode_of'](g['cfg']['tanks'][A2]) == 'standby', 'settings saved before modes: isolated = standby')
try:
    save(A2, mode='sideways')
    ok(False, 'a made-up mode is refused')
except ValueError:
    ok(True, 'a made-up mode is refused')
ok(g['cfg_view'](save(A2, mode='off')).get('mode') == 'off', 'the pages see the mode')

# the reorder warning
t1 = save(A1)
save(A2, mode='standby')
low = 150
g['hawki'][A2] = {'level': 300, 'rx': time.time()}   # tank 2 well filled
title, msg = g['reorder_alert'](A1, g['cfg']['tanks'][A1], low)
print('   ', title, '|', msg)
ok(title == 'Tank 1 is low - switch to Tank 2', 'standby tank with oil: "switch to Tank 2"')
g['hawki'][A2] = {'level': 1150, 'rx': time.time()}  # tank 2 nearly empty too
title, msg = g['reorder_alert'](A1, g['cfg']['tanks'][A1], low)
ok(title == 'Tank 1: time to order oil', 'standby tank below its own reorder level: order oil (%s)' % title)
save(A2, mode='off')
g['hawki'][A2] = {'level': 300}
title, msg = g['reorder_alert'](A1, g['cfg']['tanks'][A1], low)
ok(title == 'Tank 1: time to order oil', 'an off tank is never offered as the one to switch to (%s)' % title)
g['hawki'][A2] = {'level': 16383}
save(A2, mode='standby')
title, msg = g['reorder_alert'](A1, g['cfg']['tanks'][A1], low)
ok(title == 'Tank 1: time to order oil', 'standby tank with no reading: order oil (%s)' % title)

g['hawki'][A2] = {'level': 300, 'rx': time.time() - 4 * 3600}
title, _ = g['reorder_alert'](A1, g['cfg']['tanks'][A1], low)
ok(title == 'Tank 1: time to order oil', 'standby tank not heard for 4 h: not offered (%s)' % title)
g['hawki'][A2] = {'level': 300, 'rx': time.time(), 'bad_level': 0}
title, _ = g['reorder_alert'](A1, g['cfg']['tanks'][A1], low)
ok(title == 'Tank 1: time to order oil', 'standby tank whose latest reading was a misread: not offered (%s)' % title)
save(A2, mode='off')
t2 = save(A2, isolated=True)  # the page without modes ticks Isolated for it
ok(t2['mode'] == 'off', 'an off tank saved from a form without modes stays off (%s)' % t2.get('mode'))

# alerts(): off tanks are skipped before any warning; rearm happens in any mode
al = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'alerts')
loop = next(n for n in ast.walk(al) if isinstance(n, ast.For))
first = ast.unparse(loop.body[0])
ok("mode_of(t) == 'off'" in first and 'continue' in first, 'alerts(): an off tank is skipped first: %s' % first.split(chr(10))[0])

# linked tanks share shape, never the mode
g['cfg']['tanks'].clear()
save(A1)
t2 = save(A2, mode='standby', same_as=A1)
t1 = g['cfg']['tanks'][A1]
ok(g['mode_of'](t1) == 'use' and g['mode_of'](t2) == 'standby', 'linked ("same tank as"): each keeps its own mode')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
