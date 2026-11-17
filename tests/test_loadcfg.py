"""python3 tests/test_loadcfg.py - a config.json that can't be read at boot is never overwritten (firmware/app.py).

Only a MISSING config.json means a new Pico. A read error (flash hiccup, out of memory at boot) must leave the
real file alone; a damaged one is kept as config.bad before starting afresh.
"""
import ast, binascii, builtins, json, os, tempfile

src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
tree = ast.parse(src)
code = ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('load_cfg', 'save_cfg', 'load_deliv', 'save_deliv', 'load_json')
                   or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') == 'cfg_gen' for t in n.targets)], [])
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


def fresh():
    os.chdir(tempfile.mkdtemp())
    g = {'json': json, 'os': os, 'binascii': binascii, 'gc': __import__('gc')}
    exec(compile(code, 'app.py', 'exec'), g)
    return g


REAL = {'token': 'abc', 'ssid': 'home', 'tanks': {'c0:04:56:c4:0c:71': {'name': 'Tank 1'}}}
real_open = builtins.open


def failing_open(times, err):
    n = [0]

    def o(name, *a, **k):
        if name == 'config.json' and (not a or 'r' in a[0]) and n[0] < times:
            n[0] += 1
            raise err
        return real_open(name, *a, **k)
    return o


# a new Pico: no config.json
g = fresh()
c = g['load_cfg']()
ok(c.get('token') and c['tanks'] == {} and json.load(open('config.json'))['token'] == c['token'], 'no config.json: a new one with a token')

# a good one loads as it is
g = fresh()
json.dump(REAL, open('config.json', 'w'))
ok(g['load_cfg']() == REAL, 'a good config.json loads unchanged')

# a read error once: retried, nothing lost
for err in (OSError(5, 'EIO'), MemoryError()):
    g = fresh()
    json.dump(REAL, open('config.json', 'w'))
    builtins.open = failing_open(1, err)
    try:
        c = g['load_cfg']()
    except Exception as ex:
        c = ex
    finally:
        builtins.open = real_open
    ok(c == REAL, 'one %s while reading: retried, settings loaded (%r)' % (type(err).__name__, c if not isinstance(c, dict) else 'ok'))
    ok(json.load(open('config.json')) == REAL, '  ...and config.json is untouched')

# a read error that won't go away: the file is left alone (the app stops; main.py starts the rescue server)
g = fresh()
json.dump(REAL, open('config.json', 'w'))
builtins.open = failing_open(99, OSError(5, 'EIO'))
try:
    g['load_cfg']()
    raised = False
except OSError:
    raised = True
finally:
    builtins.open = real_open
ok(raised and json.load(open('config.json')) == REAL, 'a lasting read error: config.json never overwritten')

# damaged contents: kept as config.bad, then a fresh start
for junk in ('{"token": "abc", "ssid', '', '[1, 2]', 'null'):
    g = fresh()
    open('config.json', 'w').write(junk)
    c = g['load_cfg']()
    ok(c.get('token') and os.path.exists('config.bad') and open('config.bad').read() == junk,
       'damaged config.json %r: kept as config.bad, fresh settings' % junk[:12])

# deliveries: a read error must never let a save replace the whole file with just the new record
DL = {'c0:04:56:c4:0c:71': [{'t': 1790000000, 'litres': 500}]}
g = fresh()
json.dump(DL, open('deliv.json', 'w'))
builtins.open = failing_open(0, None)


def deliv_fails(name, *a, **k):
    if name == 'deliv.json' and (not a or 'r' in a[0]):
        raise OSError(5, 'EIO')
    return real_open(name, *a, **k)


builtins.open = deliv_fails
try:
    g['load_deliv']()
    raised = False
except OSError:
    raised = True
finally:
    builtins.open = real_open
ok(raised and json.load(open('deliv.json')) == DL, 'deliveries: a read error is an error, not "none saved yet"')
g = fresh()
ok(g['load_deliv']() == {}, 'deliveries: none saved yet')
open('deliv.json', 'w').write('{"c0')
ok(g['load_deliv']() == {} and open('deliv.bad').read() == '{"c0', 'deliveries: damaged file kept as deliv.bad')

print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
