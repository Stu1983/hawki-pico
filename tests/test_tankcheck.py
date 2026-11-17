"""python3 tests/test_tankcheck.py - tank settings that make the oil go down as it rises are refused (firmware/app.py set_tank).

Each setting is checked on its own range, but some combinations break the model: window widths typed in mm
(390 instead of 39), or a capacity far below the box's size, give litres that FALL as the oil rises. And a
tank with nothing usable made reading() divide by zero.
"""
import ast, os, sys, time

FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.insert(0, FW)
import tankcalc

src = open(os.path.join(FW, 'app.py')).read()
tree = ast.parse(src)
names = ('MODES', 'MEASURED_KEYS', 'isolated_since', 'num', 'set_tank', 'check_shape')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


M = 'c0:04:56:c4:0c:71'
g = {'time': time, 'cfg': {'tanks': {M: {}}}, 'hawki': {}, 'save_cfg': lambda c: None, 'SHAPES': tankcalc.SHAPES,
     'link': tankcalc.link, 'above': tankcalc.above, 'litres_many': tankcalc.litres_many, 'whole': tankcalc.whole}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []),
             'app.py', 'exec'), g)
REAL = {'shape': 'cuboid', 'height_cm': 123, 'outlet_cm': 9.5, 'length_cm': 173, 'width_cm': 69, 'tank_l': 1306,
        'windows': 2, 'window_model': 'measured', 'win_bottom_cm': 45, 'win_top_cm': 79, 'win_outer_w_cm': 39,
        'win_inner_w_cm': 17, 'win_inner_h_cm': 14, 'ribs_cm': [31.5, 62.5, 93.5], 'rib_h_cm': 12, 'rib_depth_cm': 1.5}


def save(**k):
    try:
        g['set_tank'](dict(REAL, mac=M, name='Tank 1', **k))
        return None
    except ValueError as ex:
        return str(ex)


ok(save() is None, 'Stu\'s real Titan R1225 settings are accepted')
e = save(win_outer_w_cm=390, win_inner_w_cm=170)
ok(e and 'window' in e, 'window widths typed in mm (390 / 170): refused: %s' % e)
e = save(window_model='standard', tank_l=None, capacity_l=500, windows=2, height_cm=130, outlet_cm=None)
ok(e is not None, '500 L in a box of 1735 L with two windows: refused: %s' % e)
ok(save(window_model='standard', tank_l=None, capacity_l=1180, windows=2) is None, 'the same box with a sensible capacity: accepted')
e = save(height_cm=100, outlet_cm=100, length_cm=100, width_cm=100, tank_l=1000, win_bottom_cm=40, win_top_cm=60,
         win_outer_w_cm=100, win_inner_w_cm=100, win_inner_h_cm=20, ribs_cm=[])
ok(e is not None, 'bad windows below the outlet (the whole tank checked too): refused: %s' % e)
try:
    g['set_tank'](dict(REAL, mac=M, name='Tank 1', win_outer_w_cm=390, win_inner_w_cm=170), restore=True)
    ok(True, 'a backup with such settings still imports (refusing it would refuse the whole import)')
except ValueError:
    ok(False, 'a backup with such settings still imports (refusing it would refuse the whole import)')
for shape in ('horizontal', 'vertical', 'other'):
    ok(save(shape=shape) is None, '%s tank: accepted' % shape)
# a tank with nothing usable: no division by zero
v = tankcalc.reading({'shape': 'vertical', 'height_cm': 10, 'outlet_cm': 0, 'tank_l': 1, 'capacity_l': 0}, 50)
ok(v is not None, 'reading() with nothing usable gives an answer, no error: %r' % (v,))
try:
    v = tankcalc.reading({'shape': 'cuboid', 'height_cm': 100, 'length_cm': 100, 'width_cm': 100, 'windows': 0, 'capacity_l': 0}, 500)
    ok(v[1] is None, 'a capacity of 0: no percentage rather than a division by zero: %r' % (v,))
except ZeroDivisionError:
    ok(False, 'a capacity of 0: no percentage rather than a division by zero')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
