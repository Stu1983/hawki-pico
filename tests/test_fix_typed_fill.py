"""python3 tests/test_fix_typed_fill.py - the one-off fix of the one reading typed in as usable before v1.3.26."""
import ast, os, struct, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'firmware'))
src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'core.py')).read()
names = ('FIX_T', 'fix_typed_fill', 'merge_hist', 'hist_name')
keep = [n for n in ast.parse(src).body if isinstance(n, (ast.FunctionDef, ast.Assign)) and
        (getattr(n, 'name', None) in names or isinstance(n, ast.Assign) and any(getattr(x, 'id', None) in names for x in getattr(n.targets[0], 'elts', [n.targets[0]])))]
import time
os.chdir(tempfile.mkdtemp())
saved = []
L = lambda t, xs: [max(0.0, 1000 - x) for x in xs]  # 1 L a mm, 1000 L usable at 0 mm, none at 1000 mm
g = {'os': os, 'struct': struct, 'time': time, 'litres_many': L, 'last_saved': {}, 'save_cfg': lambda c: saved.append(1),
     'rm': lambda n: os.path.exists(n) and os.remove(n), 'unusable': lambda t: [100, 'estimate']}
exec(compile(ast.Module(keep, []), 'app.py', 'exec'), g)
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


def write(name, recs):
    with open(name, 'wb') as f:
        for r in recs:
            f.write(struct.pack('<IH', *r))


def read(name):
    b = open(name, 'rb').read()
    return [struct.unpack_from('<IH', b, i) for i in range(0, len(b), 6)]


T = g['FIX_T']
A, B = 'aa:bb:cc:dd:ee:01', 'aa:bb:cc:dd:ee:02'
own = [(T + 21 * 86400 + 37 + k * 3600, 852) for k in range(5)]
write(g['hist_name'](A), [(T, 582)] + own)
write(g['hist_name'](B), [(T - 3600 + 5, 582), (T + 7, 582), (T + 3600 + 9, 600)])
g['cfg'] = {'tanks': {A: {'height_cm': 100}, B: {'height_cm': 100}}}
g['fix_typed_fill']()
ok(read(g['hist_name'](A)) == [(T, 682)] + own, 'the typed 29 Oct fill: the 418 L typed (stored at 582 mm as usable) was all the oil; less 100 L below the outlet = 318 L usable = 682 mm')
ok(read(g['hist_name'](B)) == [(T - 3600 + 5, 582), (T + 7, 582), (T + 3600 + 9, 600)], 'readings that only look like it (not the exact second): untouched')
ok(g['cfg'].get('fix1029') and saved and not os.path.exists('fix.up'), 'marked done, nothing left behind')
write(g['hist_name'](A), [(T, 582)])
g['fix_typed_fill']()
ok(read(g['hist_name'](A)) == [(T, 582)], 'runs once only')
del g['cfg']['fix1029']
g['cfg']['tanks'] = {A: {'height_cm': 100}, 'aa:bb:cc:dd:ee:03': {'height_cm': 100}}
g['fix_typed_fill']()
ok(g['cfg'].get('fix1029') and read(g['hist_name'](A)) == [(T, 682)], 'a tank with no history file: skipped, the rest still fixed')
del g['cfg']['fix1029']
write(g['hist_name'](A), [(T, 582)])
mh = g['merge_hist']
def full(*a):
    raise OSError(28)
g['merge_hist'] = full
g['fix_typed_fill']()
ok(not g['cfg'].get('fix1029') and read(g['hist_name'](A)) == [(T, 582)], 'found but could not rewrite it (flash full): not marked done')
g['merge_hist'] = mh
g['fix_typed_fill']()
ok(g['cfg'].get('fix1029') and read(g['hist_name'](A)) == [(T, 682)], '...so the next start fixes it')
del g['cfg']['fix1029']
write(g['hist_name'](A), [(T, 582)])
g['unusable'] = lambda t: None
g['fix_typed_fill']()
ok(not g['cfg'].get('fix1029') and read(g['hist_name'](A)) == [(T, 582)], 'the part below the outlet not known yet: left, not marked done')
g['unusable'] = lambda t: [100, 'set']
import builtins
ro = builtins.open
def bad(n, *a):
    if n == g['hist_name'](A):
        raise OSError(5)
    return ro(n, *a)
g['open'] = bad
g['fix_typed_fill']()
ok(not g['cfg'].get('fix1029'), 'the file there but unreadable: not marked done')
del g['open']
g['fix_typed_fill']()
ok(g['cfg'].get('fix1029') and read(g['hist_name'](A)) == [(T, 682)], '...and both fixed on a later start')
sys.exit(1 if fails else 0)
