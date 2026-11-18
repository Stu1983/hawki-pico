"""python3 tests/test_captive.py - the setup network's captive portal (firmware/app.py dns_answer, captive_to, handle).

A phone on HAWKi-Setup gets the Pico's address for every name, and its "is there internet?" check is sent to
the setup page, so the phone opens that page by itself. Nothing changes on the home network or for the page itself.
"""
import ast, asyncio, json, os, struct, types

src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
tree = ast.parse(src)
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


T = types.SimpleNamespace(ticks_ms=lambda: 0, ticks_add=lambda a, b: a + b, ticks_diff=lambda a, b: a - b, time=lambda: 1795400000)
names = ('dns_task', 'handle', 'send', 'parse_q', 'jb', 'BadRequest', '_Req', '_Resp', 'LOADS', 'ICON_PATHS', 'WEB_MANIFEST', 'MUTATING', 'read_body_to', 'dns_answer', 'captive_to')
AP = types.SimpleNamespace(up=True)
ap = types.SimpleNamespace(active=lambda: AP.up, ifconfig=lambda: ('192.168.4.1', '255.255.255.0', '192.168.4.1', '8.8.8.8'))
wlan = types.SimpleNamespace(ifconfig=lambda: ('192.168.1.20', '255.255.255.0', '192.168.1.1', '192.168.1.1'))
g = {'wlan': wlan, 'time': T, 'asyncio': asyncio, 'json': json, 'os': os, 'gc': __import__('gc'), 'conns': [0], 'ap': ap, 'HOSTNAME': 'hawki-pico',
     'on_ap': lambda p: AP.up and p.startswith('192.168.4.'),
     'net_proof': lambda: None, 'page_s': [None], 'mono_s': lambda: 0, 'cfg': {'tanks': {}, 'pin': 'x'}, 'TOKEN': 'tok',
     'authed': lambda a: False, 'save_cfg': lambda c: None, 'print': lambda *a: None,
     'unset': types.SimpleNamespace(clear=lambda m: None), 'last_saved': {}}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []), 'app.py', 'exec'), g)
dns_answer = g['dns_answer']
IP = bytes((192, 168, 4, 1))


def query(name, qtype=1, qid=0x1234, flags=0x0100, extra=b'', qd=1):
    q = b''.join(bytes((len(p),)) + p.encode() for p in name.split('.')) + b'\x00' + struct.pack('>HH', qtype, 1)
    return struct.pack('>HHHHHH', qid, flags, qd, 0, 0, 1 if extra else 0) + q + extra


def parse(a):
    qid, fl, qd, an, ns, ar = struct.unpack('>HHHHHH', a[:12])
    i = 12
    while a[i]:
        i += a[i] + 1
    i += 5
    ans = []
    for _ in range(an):
        ptr, typ, cls, ttl, ln = struct.unpack('>HHHIH', a[i:i + 12])
        ans.append((ptr, typ, cls, ttl, a[i + 12:i + 12 + ln]))
        i += 12 + ln
    return dict(id=qid, flags=fl, qd=qd, an=an, ans=ans, rest=a[i:])


edns = b'\x00\x00\x29\x05\xc0\x00\x00\x00\x00\x00\x00'  # (an OPT record, as phones send)
for name in ('captive.apple.com', 'connectivitycheck.gstatic.com', 'www.msftconnecttest.com', 'x'):
    p = parse(dns_answer(query(name, extra=edns), IP))
    ok(p['id'] == 0x1234 and p['flags'] == 0x8180 and p['qd'] == 1 and p['an'] == 1 and p['ans'][0] == (0xc00c, 1, 1, 10, IP) and not p['rest'],
       '%s: answered with the Pico, same id, nothing left over (%r)' % (name, p))
p = parse(dns_answer(query('captive.apple.com', qtype=28), IP))
ok(p['an'] == 0 and p['flags'] == 0x8180, 'an IPv6 (AAAA) question: no records, so the phone asks for IPv4 instead')
p = parse(dns_answer(query('a.b', flags=0x0000), IP))
ok(p['flags'] == 0x8080, 'no recursion asked for: none claimed back')
for bad, why in ((query('a.b', flags=0x8180), 'a reply'), (query('a.b', flags=0x2900), 'an update (not a query)'),
                 (query('a.b', qd=2), 'two questions'), (b'\x12\x34\x01\x00\x00\x01', 'too short'),
                 (query('a.b')[:-3], 'cut off mid-question'), (query('a.b')[:12] + b'\xc0\x0c\x00\x01\x00\x01', 'a pointer for a name'),
                 (query('a.b')[:12] + b'\x3f' + b'a' * 10, 'a label running off the end')):
    try:
        r = dns_answer(bad, IP)
    except Exception as ex:
        r = 'raised %r' % ex
    ok(r is None, '%s: ignored, never an error (%r)' % (why, r))
long = query('.'.join(['a' * 63] * 4))  # (a 257-byte name)
ok(dns_answer(long, IP) is None, 'a name over 255 bytes: ignored')
ok(dns_answer(query('.'.join(['a' * 63] * 3) + '.' + 'a' * 61), IP) is not None, 'a 255-byte name: answered')


class W:  # a real client's stream (not the Pico's own self-check)
    def __init__(self, peer):
        self.peer, self.out = peer, b''

    def get_extra_info(self, k):
        return (self.peer, 0)

    def write(self, b):
        self.out += b

    async def drain(self):
        pass


def req(raw, peer):
    w = W(peer)
    asyncio.run(g['handle'](g['_Req'](raw), w))
    return w.out.decode(errors='replace')


r = req(b'GET /hotspot-detect.html HTTP/1.0\r\nHost: captive.apple.com\r\n\r\n', '192.168.4.16')
ok(r.startswith('HTTP/1.0 302') and 'Location: http://192.168.4.1/\r\n' in r, 'an iPhone\'s check on the setup network: sent to the setup page')
r = req(b'GET /generate_204 HTTP/1.1\r\nHost: connectivitycheck.gstatic.com\r\nConnection: keep-alive\r\n\r\n', '192.168.4.16')
ok(r.startswith('HTTP/1.0 302'), 'an Android check: sent to the setup page, never the 204 it wants')
for host in ('192.168.4.1', '192.168.4.1:80', 'HAWKi-Pico.local', 'hawki-pico', '192.168.1.20'):
    r = req(b'GET /nope HTTP/1.0\r\nHost: %s\r\n\r\n' % host.encode(), '192.168.4.16')
    ok(r.startswith('HTTP/1.0 404'), 'the page itself (Host: %s) is served as before' % host)
for line in (b'POST /api/wifi HTTP/1.0', b'GET /api/state HTTP/1.0', b'POST /nope HTTP/1.0'):
    r = req(line + b'\r\nHost: alias.local\r\nContent-Length: 0\r\n\r\n', '192.168.4.16')
    ok(not r.startswith('HTTP/1.0 302'), '%s by another name on the setup network: never redirected (%s)' % (line.decode(), r.split(chr(13))[0]))
r = req(b'GET /nope HTTP/1.0\r\n\r\n', '192.168.4.16')
ok(r.startswith('HTTP/1.0 404'), 'no Host header: served as before')
r = req(b'GET /nope HTTP/1.0\r\nHost: proxy.example.ts.net:8450\r\n\r\n', '192.168.1.50')
ok(r.startswith('HTTP/1.0 404'), 'the home network, by any name (a proxy): never redirected')
AP.up = False
r = req(b'GET /nope HTTP/1.0\r\nHost: captive.apple.com\r\n\r\n', '192.168.4.16')
ok(r.startswith('HTTP/1.0 404'), 'setup network off: never redirected')
AP.up = True
w = g['_Resp']()
asyncio.run(g['handle'](g['_Req'](b'GET /nope HTTP/1.0\r\nHost: captive.apple.com\r\n\r\n'), w))
ok(w.head.startswith(b'HTTP/1.0 404'), 'the Pico checking its own pages after an update: never redirected')
# the DNS task: a socket that goes bad is never polled forever; nothing waiting is not an error


class Sock:
    def __init__(self, errs):
        self.errs, self.closed = errs, False

    def setsockopt(self, *a):
        pass

    def bind(self, a):
        pass

    def setblocking(self, b):
        pass

    def recvfrom(self, n):
        raise OSError(self.errs.pop(0) if self.errs else 11, "x")

    def close(self):
        self.closed = True


import sys
made = []
sys.modules['socket'] = types.SimpleNamespace(AF_INET=2, SOCK_DGRAM=2, SOL_SOCKET=1, SO_REUSEADDR=4,
                                              socket=lambda *a: made.append(Sock([11, 9])) or made[-1])


async def drive():
    try:
        await asyncio.wait_for(g['dns_task'](), 1)
        return 'returned'
    except asyncio.TimeoutError:  # (first: on Python 3.11+ it is an OSError too)
        return 'still polling'
    except OSError as ex:
        return ex.errno


r = asyncio.run(drive())
ok(r == 9 and made[0].closed, 'a broken socket (EBADF): the task stops, closing it, so keep() starts afresh (%r)' % r)
made[:] = []
sys.modules['socket'].socket = lambda *a: made.append(Sock([])) or made[-1]
r = asyncio.run(drive())
ok(r == 'still polling', 'nothing to read: it just waits (%r)' % r)
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
