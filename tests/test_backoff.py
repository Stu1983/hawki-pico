"""python3 tests/test_backoff.py - background fetches give up on time and back off when they fail.

A fetch's deadline only counted between reads, so a server trickling bytes or gone silent held the Pico (and
everything on it) far longer; failed weather parts, prices and alerts were retried at a fixed rate forever.
"""
import ast, asyncio, os, sys, types

FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.insert(0, FW)
import weather

src = open(os.path.join(FW, 'core.py')).read()
tree = ast.parse(src)
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


# --- _within: each read only waits for the time left; past the deadline, stop
class Sock:
    def __init__(self, takes):
        self.takes, self.t = takes, None

    def settimeout(self, x):
        if not self.takes:
            raise AttributeError('no settimeout')
        self.t = x


clock = [1000]
weather.time = types.SimpleNamespace(time=lambda: clock[0])
s, raw = Sock(False), Sock(True)
weather._within(s, raw, 990, 25, 'host')
ok(raw.t == 15, 'a TLS socket without settimeout: the one under it gets the time left, at most one read\'s 15 s (%s s)' % raw.t)
weather._within(s, raw, 999, 60, 'host')
ok(raw.t == 15, 'lots of time left: still at most 15 s for one read (%s)' % raw.t)
s = Sock(True)
weather._within(s, raw, 990, 25, 'host')
ok(s.t == 15, 'one that takes it: set on it')
try:
    weather._within(s, raw, 970, 25, 'host')
    ok(False, 'past the deadline: stops')
except OSError as ex:
    ok('took too long' in str(ex), 'past the deadline: stops (%s)' % ex)

# --- a server trickling a byte at a time: weather.get gives up at its deadline, not after 15 s a read
class Trickle:
    def __init__(self, *a):
        self.n = 0

    def settimeout(self, x):
        pass

    def connect(self, a):
        pass

    def sendall(self, b):
        pass

    def recv(self, n):
        clock[0] += 3  # each read takes 3 s
        self.n += 1
        return b'x'

    def close(self):
        pass


class Ctx:
    verify_mode = None

    def __init__(self, *a):
        pass

    def load_verify_locations(self, **k):
        pass

    def wrap_socket(self, s, server_hostname=None):
        return s


weather.socket = types.SimpleNamespace(getaddrinfo=lambda *a: [(0, 0, 0, '', ('1.2.3.4', 443))], socket=Trickle, SOCK_STREAM=1)
weather.ssl = types.SimpleNamespace(SSLContext=Ctx, PROTOCOL_TLS_CLIENT=0, CERT_REQUIRED=0)
import tempfile
os.chdir(tempfile.mkdtemp())
open('ca.pem', 'wb').write(b'x')
clock[0] = 1000
try:
    weather.get('api.example', '/x', deadline=25)
    ok(False, 'trickling server: gives up')
except OSError as ex:
    ok(clock[0] - 1000 <= 28 and 'took too long' in str(ex), 'a trickling server: given up at the deadline (%d s)' % (clock[0] - 1000))

# --- alerts: after a failed send, hold off (5 min doubling to 30); a success, or the test button, always goes
mono = [0]
sent = []
res = [{'po': 'error'}]
g = {**__import__('_phstub').STUB, 'asyncio': asyncio, 'mono_s': lambda: mono[0], 'make_room': lambda: None, 'note_oom': lambda hit: None, 'print': lambda *a: None, 'cfg': {'notify': {}},
     'notify': types.SimpleNamespace(oom=[False], send=lambda n, t, m, u: sent.append(t) or dict(res[0]))}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in ('send_alert', '_send_alert')
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in ('alert_back', 'sending') for t in n.targets)], []), 'app.py', 'exec'), g)
asyncio.run(g['send_alert']('a', 'm'))
r = asyncio.run(g['send_alert']('b', 'm'))
ok(sent == ['a'] and 'held' in r, 'a failed send: the next one 5 minutes later waits')
mono[0] += 301
asyncio.run(g['send_alert']('c', 'm'))
mono[0] += 301
r = asyncio.run(g['send_alert']('d', 'm'))
ok(sent == ['a', 'c'] and 'held' in r, '...and the wait doubles while it keeps failing')
asyncio.run(g['send_alert']('drop', 'm', urgent=True))
ok(sent[-1] == 'drop', 'an urgent alert (a sudden drop) is never held')
asyncio.run(g['send_alert']('test', 'm', force=True))
ok(sent[-1] == 'test', 'the test button always sends')
res[0] = {'po': 'ok'}
mono[0] += 2000
asyncio.run(g['send_alert']('e', 'm'))
r = asyncio.run(g['send_alert']('f', 'm'))
ok(sent[-2:] == ['e', 'f'], 'after a success, no waiting')

# --- weather parts: a failing part waits 20 min, doubling to 6 h; a success resets it
g = {**__import__('_phstub').STUB, 'mono_s': lambda: mono[0], 'wx_state': {'errs': {}}, 'print': lambda *a: None}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('wx_err', 'wx_due')
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') == 'wx_back' for t in n.targets)], []), 'app.py', 'exec'), g)
mono[0] = 0
waits = []
for i in range(7):
    g['wx_err']('forecast', OSError('down'))
    waits.append(g['wx_back']['forecast'][1])
ok(waits == [1200, 2400, 4800, 9600, 19200, 21600, 21600], 'a failing weather part: %s' % waits)
ok(not g['wx_due']('forecast') and g['wx_due']('archive'), 'only that part waits')
g['wx_err']('forecast', None)
ok(g['wx_due']('forecast'), 'a success: due again at once')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
