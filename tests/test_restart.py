"""python3 tests/test_restart.py - a planned restart first saves the readings still queued (firmware/app.py).

The recorder writes queued readings every 10 s; a restart in between (a Wi-Fi or address change, an update) lost
them, and after the restart the same reading is only a baseline: that hour went missing from the history.
"""
import ast, os, struct, sys, tempfile, types

FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.insert(0, FW)
import unset

src = open(os.path.join(FW, 'app.py')).read()
tree = ast.parse(src)
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


class Reset(BaseException):
    pass


M = 'c0:04:56:c4:0c:71'
os.chdir(tempfile.mkdtemp())
g = {'os': os, 'struct': struct, 'unset': unset, 'BOOT': 3, 'mono_s': lambda: 5000,
     'time': types.SimpleNamespace(ticks_ms=lambda: 2000, ticks_diff=lambda a, b: a - b),
     'cfg': {'tanks': {M: {}}}, 'pending': [(M, 1795400000, 701)], 'pending_unset': [(M, 1000, 0, 702)], 'pending_clk': [(M, 1795400000, 1795400010, 1795399990)],
     'clocklog': __import__('clocklog'),
     'machine': types.SimpleNamespace(reset=lambda: (_ for _ in ()).throw(Reset())), 'print': lambda *a: None}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('hist_name', 'save_clk', 'save_pending', 'restart')], []),
             'app.py', 'exec'), g)
try:
    g['restart']()
except Reset:
    pass
b = open(g['hist_name'](M), 'rb').read()
ok(struct.unpack('<IH', b) == (1795400000, 701) and not g['pending'], 'a reading queued just before the restart is saved first')
ok(g['clocklog'].read(M) == [(1795400000, 1795400010, 1795399990)] and not g['pending_clk'], '...with its two clocks (clocklog)')
ok(unset.records(M) == [(4999, 0, 702, 3)] and not g['pending_unset'], '...and one heard while the clock was unset is kept aside')
# every machine.reset() in app.py goes through restart(), except restart() itself and the watchdog's
calls = []
for fn in ast.walk(tree):
    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and ast.unparse(n.func) == 'machine.reset':
                calls.append(fn.name)
ok(sorted(set(calls)) == ['restart', 'wd_check'], 'every planned restart saves first (direct resets only in: %s)' % sorted(set(calls)))
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
