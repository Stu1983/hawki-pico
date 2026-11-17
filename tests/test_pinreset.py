"""python3 tests/test_pinreset.py - after a BOOTSEL PIN reset a new PIN can be set (firmware/app.py).

A first PIN may only be set from the setup network or within 30 minutes of the Pico starting. Holding BOOTSEL
for 5 s clears the PIN; that must open a fresh 30 minutes too, or (on automatic addressing, no restart) the
page refuses every new PIN until someone pulls the plug.
"""
import ast, os

src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
tree = ast.parse(src)
names = ('FIRST_PIN_SECS', 'first_pin_until', 'may_set_first_pin', 'pin_reset')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


clock = [0]
saved = []
g = {'mono_s': lambda: clock[0], 'on_ap': lambda peer: False, 'cfg': {'pin': 'x', 'pin_salt': 's', 'sessions': ['a']},
     'save_cfg': lambda c: saved.append(dict(c)), 'lock': {'fails': 3, 'wait': 3600, 'until': 10 ** 10}}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []),
             'app.py', 'exec'), g)
ok(g['may_set_first_pin']('192.168.1.20'), 'just after start: a first PIN may be set')
clock[0] = 1801
ok(not g['may_set_first_pin']('192.168.1.20'), '30 min after start: not from the home Wi-Fi')
ok('pin_reset' in g, 'pin_reset() exists')
if 'pin_reset' in g:
    clock[0] = 8 * 86400  # a week up
    g['pin_reset']()
    ok('pin' not in g['cfg'] and 'sessions' not in g['cfg'] and saved, 'BOOTSEL: PIN and sessions cleared and saved')
    ok(g['may_set_first_pin']('192.168.1.20'), '...and a new PIN may be set straight away')
    ok(g['lock'] == {'fails': 0, 'wait': 30, 'until': 0}, '...and wrong tries with the old PIN no longer lock anyone out: %r' % g['lock'])
    clock[0] += 1799
    ok(g['may_set_first_pin']('192.168.1.20'), '...for 30 minutes')
    clock[0] += 2
    ok(not g['may_set_first_pin']('192.168.1.20'), '...then no longer')
g['on_ap'] = lambda peer: True
ok(g['may_set_first_pin']('192.168.4.2'), 'from the setup network: always')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
