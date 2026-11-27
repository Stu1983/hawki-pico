"""python3 tests/test_http.py - the request handler copes with odd requests (firmware/app.py handle).

Drives the real handle() with stand-in streams: a big Cookie header (other sites on the same host name, via
Tailscale) no longer kills the request; more than 100 headers is a 431, never headers read as the body; a POST
whose body isn't a JSON object is a 400, not a dropped connection.
"""
import ast, asyncio, json, os, types

src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
tree = ast.parse(src)
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


ms = [0]
T = types.SimpleNamespace(ticks_ms=lambda: ms[0], ticks_add=lambda a, b: a + b, ticks_diff=lambda a, b: a - b, time=lambda: 1795400000)
names = ('handle', 'send', 'parse_q', 'jb', 'BadRequest', '_Req', '_Resp', 'LOADS', 'ICON_PATHS', 'WEB_MANIFEST', 'MUTATING', 'read_body_to')
saved = []
g = {**__import__('_phstub').STUB, 'time': T, 'asyncio': asyncio, 'json': json, 'os': os, 'gc': __import__('gc'), 'conns': [0], 'on_ap': lambda p: False,
     'net_proof': lambda: None, 'page_s': [None], 'mono_s': lambda: 0, 'cfg': {'tanks': {}, 'pin': 'x'}, 'TOKEN': 'tok',
     'authed': lambda a: a == 'good', 'save_cfg': lambda c: saved.append(dict(c)), 'print': lambda *a: None,
     'unset': types.SimpleNamespace(clear=lambda m: None), 'last_saved': {}, 'poke_st': {}, 'poke_info': {}, 'clock_st': {}, 'clock_info': {}, 'radio_busy': [False],
     'moff_info': {}, 'moff_want': set(), 'moff_try': {}, 'moff_seen': {}}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []), 'app.py', 'exec'), g)


def req(raw):
    w = g['_Resp']()
    try:
        asyncio.run(g['handle'](g['_Req'](raw), w))
    except Exception as ex:
        return 'raised %r' % ex
    return w.head.split(b'\r\n')[0].decode() or 'no answer'


ok(req(b'GET /nope HTTP/1.0\r\n\r\n').startswith('HTTP/1.0 404'), 'an ordinary request is answered')
r = req(b'GET /nope HTTP/1.0\r\nCookie: ' + b'a=1; ' * 1000 + b'\r\nHost: pico\r\n\r\n')
ok(r.startswith('HTTP/1.0 404'), 'a 5 KB Cookie header: the request is still answered (%s)' % r)
r = req(b'GET /nope HTTP/1.0\r\n' + b''.join(b'X-%d: 1\r\n' % i for i in range(60)) + b'\r\n')
ok(r.startswith('HTTP/1.0 404'), '60 headers: answered (%s)' % r)
r = req(b'GET /nope HTTP/1.0\r\n' + b''.join(b'X-%d: 1\r\n' % i for i in range(150)) + b'\r\n')
ok(r.startswith('HTTP/1.0 431'), '150 headers: 431, never headers read as the body (%s)' % r)
r = req(b'POST /api/maint HTTP/1.0\r\nX-Auth: good\r\nContent-Length:' + b' ' * 2100 + b'11\r\n\r\n{"on":true}')
ok(not r.startswith('HTTP/1.0 200'), 'an over-long Content-Length is refused, never dropped (the body would be lost) (%s)' % r)
r = req(b'GET /nope HTTP/1.0\r\n' + b''.join(b'X%d: ' % i + b'a' * 2095 + b'\r\n' for i in range(9)) + b'\r\n')
ok(not r.startswith('HTTP/1.0 404'), '9 over-long headers (19 KB): refused, the 16 KB cap counts everything (%s)' % r)
for body in (b'[]', b'not json', b'null'):
    r = req(b'POST /api/maint HTTP/1.0\r\nX-Auth: good\r\nContent-Length: %d\r\n\r\n' % len(body) + body)
    ok(r.startswith('HTTP/1.0 400'), 'POST /api/maint with %r: a 400, not a dropped connection (%s)' % (body, r))
body = b'{"on": true}'
r = req(b'POST /api/maint HTTP/1.0\r\nX-Auth: good\r\nContent-Length: %d\r\n\r\n' % len(body) + body)
ok(r.startswith('HTTP/1.0 200') and saved and saved[-1].get('maint') is True, 'a good body still works (%s)' % r)
# a typical year's oil (where the forecast starts): saved as a whole number, cleared by null, checked
g['num'] = lambda v, lo, hi: (float(v) if lo <= float(v) <= hi else (_ for _ in ()).throw(ValueError('out of range')))
for body, want, code in ((b'{"litres": 2100}', 2100, '200'), (b'{"litres": "1850.6"}', 1850, '200'), (b'{"litres": 5}', 1850, '400'),
                         (b'{"litres": "lots"}', 1850, '400'), (b'{"litres": null}', None, '200')):
    r = req(b'POST /api/year HTTP/1.0\r\nX-Auth: good\r\nContent-Length: %d\r\n\r\n' % len(body) + body)
    ok(r.startswith('HTTP/1.0 ' + code) and g['cfg'].get('year_l') == want, 'POST /api/year %r: %s, kept %r' % (body, r, g['cfg'].get('year_l')))
r = req(b'POST /api/year HTTP/1.0\r\nX-Auth: bad\r\nContent-Length: 16\r\n\r\n{"litres": 2100}')
ok(r.startswith('HTTP/1.0 401') and 'year_l' not in g['cfg'], 'the typical year needs the PIN (%s)' % r)
# deleting one of two linked tanks: the other is no longer linked, and the deleted one's alert state goes
A, B = 'c0:04:56:c4:0c:71', 'c6:76:1b:dc:39:1c'
g['cfg'].update(tanks={A: {'group': 'g1'}, B: {'group': 'g1'}}, alerted={A: {'reorder': 1}, B: {}})
body = json.dumps({'mac': A}).encode()
r = req(b'POST /api/tank/delete HTTP/1.0\r\nX-Auth: good\r\nContent-Length: %d\r\n\r\n' % len(body) + body)
ok(r.startswith('HTTP/1.0 200') and A not in g['cfg']['tanks'] and 'group' not in g['cfg']['tanks'][B] and A not in g['cfg']['alerted'],
   'delete one of two linked tanks: the other is unlinked, its alerts forgotten (%s, %r)' % (r, g['cfg']['tanks']))
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
