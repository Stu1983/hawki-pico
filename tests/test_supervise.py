"""python3 tests/test_supervise.py - nothing stops for good (firmware/app.py keep/wd_check/answers, rescue.py, main.py).

A long-running task that raises is started again; the soft watchdog restarts a Pico whose event loop has stopped;
the router probe treats "out of sockets" as no answer; the rescue server restarts into the app after 15 quiet
minutes and copes with a damaged config.json.
"""
import ast, asyncio, json, os, sys, tempfile, types

FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
src = open(os.path.join(FW, 'app.py')).read()
tree = ast.parse(src)
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


def pick(*names, **g):
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names
             or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)]
    g = {**__import__('_phstub').STUB, **g}
    exec(compile(ast.Module(nodes, []), 'app.py', 'exec'), g)
    return g


class Reset(BaseException):  # (like the real reset, no handler can swallow it)
    pass


def reset():
    raise Reset()


# --- keep(): a task that raises is started again, with growing waits; one that finishes is left finished
slept = []


async def fake_sleep(s):
    slept.append(s)

clock = [0]
g = pick('keep', asyncio=types.SimpleNamespace(sleep=fake_sleep), mono_s=lambda: clock[0], print=lambda *a: None)
ok('keep' in g, 'keep() exists')
if 'keep' in g:
    runs = []

    async def flaky():
        runs.append(1)
        if len(runs) < 4:
            raise OSError(12, 'ENOMEM')
    asyncio.run(g['keep'](flaky, 'flaky'))
    ok(len(runs) == 4, 'a task that raised 3 times was started 4 times (%d)' % len(runs))
    ok(slept == [20, 40, 80], 'waits grow while it keeps failing: %r' % slept)

    slept.clear()
    runs.clear()

    async def long_then_fail():
        runs.append(1)
        clock[0] += 3600  # ran fine for an hour
        if len(runs) < 3:
            raise ValueError('x')
    asyncio.run(g['keep'](long_then_fail, 'x'))
    ok(slept == [10, 10], 'after a long healthy run the wait starts again at 10 s: %r' % slept)

# --- wd_check(): restart only after WD_MINUTES without a beat
g = pick('WD_MINUTES', 'beat', 'wd', 'wd_hold', 'wd_check', machine=types.SimpleNamespace(reset=reset))
ok('wd_check' in g, 'soft watchdog exists')
if 'wd_check' in g:
    for _ in range(30):
        g['beat'][0] += 1
        g['wd_check']()
    ok(True, 'beating: no restart in 30 minutes')
    did = None
    for m in range(1, 20):
        try:
            g['wd_check']()
        except Reset:
            did = m
            break
    ok(did == g['WD_MINUTES'], 'stuck: restart after %s minutes (WD_MINUTES %s)' % (did, g['WD_MINUTES']))
    g['wd'][1] = 0
    g['wd_hold'][0] = 1  # an update downloading slowly over weak Wi-Fi: the loop is blocked on purpose
    try:
        for _ in range(60):
            g['wd_check']()
        held = True
    except Reset:
        held = False
    g['wd_hold'][0] = 0
    ok(held, 'a deliberate long job (update, maintenance, history upload) is not cut off')

# --- answers(): out of sockets is "no answer", never an exception that kills the Wi-Fi keeper
fake_socket = types.ModuleType('socket')


def no_sockets():
    raise OSError(12, 'ENOMEM')
fake_socket.socket = no_sockets
sys.modules['socket'] = fake_socket
g = pick('answers', time=types.SimpleNamespace(), asyncio=asyncio)
try:
    r = asyncio.run(g['answers']('192.0.2.1', 80))
except Exception as ex:
    r = ex
del sys.modules['socket']
ok(r is False, 'router probe with no sockets left: %r' % (r,))

# --- main(): every long-running task is started under keep()
main = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'main')
bare = [ast.unparse(c) for c in ast.walk(main) if isinstance(c, ast.Call) and ast.unparse(c.func) == 'asyncio.create_task'
        and not ast.unparse(c).startswith('asyncio.create_task(keep(')]
ok(not bare, 'no task started without keep(): %r' % bare)


# --- rescue.py with stub MicroPython modules
def run_rescue(files, requests=(), max_accepts=200):
    d = tempfile.mkdtemp()
    os.chdir(d)
    for n, b in files.items():
        open(n, 'w').write(b)
    now = [0]
    t = types.ModuleType('time')
    t.ticks_ms = lambda: now[0]
    t.ticks_diff = lambda a, b: a - b
    t.sleep = lambda s: None
    m = types.ModuleType('machine')
    m.reset = reset
    net = types.ModuleType('network')

    class WLAN:
        def __init__(self, *a): pass
        def active(self, *a): return True
        def connect(self, *a): pass
        def isconnected(self): return False
        def config(self, **k): pass
    net.WLAN, net.STA_IF, net.AP_IF = WLAN, 0, 1
    sk = types.ModuleType('socket')
    sk.SOL_SOCKET = sk.SO_REUSEADDR = 0
    reqs = list(requests)
    sent = []

    class Conn:
        def __init__(self, data): self.data = data
        def settimeout(self, x): pass
        def recv(self, n):
            b, self.data = self.data[:n], self.data[n:]
            return b
        def send(self, b): sent.append(b)
        def close(self): pass

    class Sock:
        n = 0
        def setsockopt(self, *a): pass
        def bind(self, *a): pass
        def listen(self, *a): pass
        def settimeout(self, x): self.t = x
        def accept(self):
            Sock.n += 1
            if Sock.n > max_accepts:
                raise RuntimeError('no restart after %d accepts' % max_accepts)
            if reqs and reqs[0][0] <= now[0]:
                return Conn(reqs.pop(0)[1]), None
            now[0] += getattr(self, 't', 30) * 1000 if getattr(self, 't', None) else 10 ** 9
            if getattr(self, 't', None):
                raise OSError(110, 'ETIMEDOUT')
            raise RuntimeError('accept() would block forever')
    sk.socket = Sock
    saved = {k: sys.modules.get(k) for k in ('time', 'machine', 'network', 'socket')}
    sys.modules.update(time=t, machine=m, network=net, socket=sk)
    try:
        exec(compile(open(os.path.join(FW, 'rescue.py')).read(), 'rescue.py', 'exec'), {'__name__': 'rescue'})
        return 'ran off the end', now[0], sent
    except Reset:
        return 'reset', now[0], sent
    except Exception as ex:
        return repr(ex), now[0], sent
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


r, at, _ = run_rescue({'config.json': json.dumps({'token': 't0k'})})
ok(r == 'reset' and 15 * 60000 < at <= 16 * 60000, 'rescue with nobody asking: restarts into the app after 15 min (%s at %.1f min)' % (r, at / 60000))
r, at, sent = run_rescue({'config.json': json.dumps({'token': 't0k'})}, [(10 * 60000, b'GET /crash HTTP/1.0\r\n\r\n')])
ok(r == 'reset' and at > 25 * 60000 and sent, 'a request puts the restart back 15 min (%s at %.1f min)' % (r, at / 60000))
for junk in ('[1]', 'null', '{"tok'):
    r, at, _ = run_rescue({'config.json': junk})
    ok(r == 'reset', 'rescue with config.json %r: starts, then restarts (%s)' % (junk, r))
r, at, sent = run_rescue({'config.json': '{"tok', 'config.bad': json.dumps({'token': 'old'})},
                         [(0, b'GET /reboot?t=old HTTP/1.0\r\n\r\n')])
ok(r == 'reset' and at == 0, 'damaged config.json: the token kept in config.bad still works (%s at %d)' % (r, at))

# --- main.py: if even the rescue server can't start, restart after a while (never sit there dead)
mp = open(os.path.join(FW, 'main.py')).read()
ok('import rescue' in mp and 'machine.reset()' in mp.split('import rescue', 1)[1], 'main.py restarts if rescue fails to start')

print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
