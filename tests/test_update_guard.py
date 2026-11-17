"""python3 tests/test_update_guard.py - an update is only confirmed once its web pages work (firmware/app.py).

update_guard used to confirm a new version after 2 minutes with Wi-Fi: one that imported fine but whose page was
broken was then kept for good, and (on a friend's Pico) could never be updated again from that page. Now the
state API and the main page must answer 200 through the real handle(), or after 10 minutes the old version goes back.
"""
import ast, asyncio, os, sys, types

src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
tree = ast.parse(src)
names = ('_Req', '_Resp', 'web_ok', 'update_guard')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


class Reset(BaseException):
    pass


clock = [0]


def run(handle, wifi=True):
    log = []
    clock[0] = 0
    sys.modules['updater'] = types.SimpleNamespace(commit=lambda: log.append('commit') or {'to': 'x'})
    sys.modules['rollback'] = types.SimpleNamespace(undo=lambda why: log.append('undo: ' + why) or True)

    async def nap(s):
        clock[0] += s
    g = {'asyncio': types.SimpleNamespace(sleep=nap, wait_for=lambda c, t: c), 'os': os, 'print': lambda *a: None,
         'mono_s': lambda: clock[0],
         'update_info': lambda: {'pending': True}, 'wlan': types.SimpleNamespace(isconnected=lambda: wifi),
         'cfg': {'ssid': 'home'}, 'machine': types.SimpleNamespace(reset=lambda: (_ for _ in ()).throw(Reset())),
         'handle': handle, 'restart': lambda: (_ for _ in ()).throw(Reset())}
    exec(compile(ast.Module([n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names], []),
                 'app.py', 'exec'), g)
    try:
        asyncio.run(g['update_guard']())
    except Reset:
        log.append('reset@%d' % clock[0])
    return log, g


async def good(r, w):
    line = await r.read(256)
    assert line.startswith(b'GET ')
    w.write(b'HTTP/1.0 200 OK\r\nContent-Type: text/html\r\nContent-Length: 5000\r\n\r\n')
    for _ in range(5):
        w.write(b'x' * 1000)
        await w.drain()


async def cut_off(r, w):  # the page file fails part-way: headers say 5000, 1024 sent
    w.write(b'HTTP/1.0 200 OK\r\nContent-Length: 5000\r\n\r\n')
    w.write(b'x' * 1024)


async def slow(r, w):  # every check stalls for its 30 s
    clock[0] += 30


async def broken(r, w):
    raise NameError('the new version broke the page')


async def err500(r, w):
    w.write(b'HTTP/1.0 500 OK\r\n\r\n')


log, g = run(good)
ok(log == ['commit'], 'pages working: the update is confirmed (%s)' % log)
log, _ = run(broken)
ok(log[:1] == ['undo: the web page of the new version is not working'] and log[-1].startswith('reset'), 'page code raising: back to the old version (%s)' % log)
log, _ = run(err500)
ok(log[:1] == ['undo: the web page of the new version is not working'], 'pages answering 500: back to the old version (%s)' % log)
log, _ = run(good, wifi=False)
ok(log[:1] == ['undo: no Wi-Fi after the update'], 'no Wi-Fi for 10 minutes: back to the old version, as before (%s)' % log)
log, _ = run(cut_off)
ok(log[:1] == ['undo: the web page of the new version is not working'], 'a page cut off part-way: not counted as working (%s)' % log)
log, _ = run(slow)
at = int(log[-1].split('@')[1]) if log and '@' in log[-1] else None
ok(at is not None and at <= 640, 'checks that keep stalling: still back to the old version after ~10 minutes (at %s s)' % at)
# the self-check leaves no trace: not network proof, not a page load, not counted against the connection limit
src_h = ast.unparse(next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'handle'))
ok("isinstance(w, _Resp)" in src_h and "not me" in src_h, 'handle() treats its own check without side effects')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
