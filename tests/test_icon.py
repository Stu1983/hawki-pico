"""python3 tests/test_icon.py - the home-screen icon and web-app manifest (firmware/app.py handle, firmware/icon.py).

An iPhone's Add to Home Screen asks for /apple-touch-icon.png (even without the page's link); browsers ask for
/favicon.ico; Android's Install app reads /manifest.webmanifest. Each gets a real answer, never a 404.
"""
import ast, asyncio, binascii, json, os, sys, types

FW = os.path.join(os.path.dirname(__file__), '..', 'firmware')
sys.path.insert(0, FW)
src = open(os.path.join(FW, 'app.py')).read()
tree = ast.parse(src)
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


T = types.SimpleNamespace(ticks_ms=lambda: 0, ticks_add=lambda a, b: a + b, ticks_diff=lambda a, b: a - b, time=lambda: 1795400000)
names = ('handle', 'send', 'parse_q', 'jb', 'BadRequest', '_Req', '_Resp', 'LOADS', 'MUTATING', 'read_body_to', 'captive_to',
         'ICON_PATHS', 'WEB_MANIFEST')
g = {'time': T, 'asyncio': asyncio, 'json': json, 'os': os, 'binascii': binascii, 'gc': __import__('gc'), 'conns': [0],
     'on_ap': lambda p: False, 'net_proof': lambda: None, 'page_s': [None], 'mono_s': lambda: 0, 'cfg': {'tanks': {}, 'pin': 'x'},
     'TOKEN': 'tok', 'authed': lambda a: False, 'print': lambda *a: None, 'HOSTNAME': 'hawki-pico'}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []), 'app.py', 'exec'), g)


class W:
    def __init__(self):
        self.out = b''

    def get_extra_info(self, k):
        return ('192.168.1.40', 0)

    def write(self, b):
        self.out += b

    async def drain(self):
        pass


def get(path):
    w = W()
    asyncio.run(g['handle'](g['_Req'](b'GET ' + path.encode() + b' HTTP/1.1\r\nHost: hawki-pico.local\r\n\r\n'), w))
    head, _, body = w.out.partition(b'\r\n\r\n')
    return head.decode(), body


for p in ('/apple-touch-icon.png', '/apple-touch-icon-precomposed.png', '/icon.png', '/favicon.ico'):
    head, body = get(p)
    ok(head.startswith('HTTP/1.0 200') and 'Content-Type: image/png' in head and body[:8] == b'\x89PNG\r\n\x1a\n'
       and 'Content-Length: %d' % len(body) in head and 'max-age' in head, '%s: the PNG, cached (%d bytes)' % (p, len(body)))
w, h = int.from_bytes(body[16:20], 'big'), int.from_bytes(body[20:24], 'big')
ok((w, h) == (180, 180), 'it is 180 x 180, the size iPhones use (%dx%d)' % (w, h))
head, body = get('/manifest.webmanifest')
m = json.loads(body)
ok(head.startswith('HTTP/1.0 200') and 'application/manifest+json' in head and m['start_url'] == '/' and m['display'] == 'standalone'
   and m['icons'][0]['src'] == '/icon.png', 'the web-app manifest: opens the dashboard, full screen, with the icon')
for page in ('ui.html', 'hist.html'):
    h = open(os.path.join(FW, page)).read().split('</head>')[0]
    ok('rel="apple-touch-icon" href="/apple-touch-icon.png"' in h and 'rel="manifest"' in h and 'apple-mobile-web-app-title' in h,
       '%s names the icon, the manifest and the app\'s name' % page)
ok('href="/"' in open(os.path.join(FW, 'hist.html')).read(), 'the history page links back to the dashboard (no browser back button full screen)')
# the widget script, served by the Pico with its own name in it
os.chdir(FW)
g['HOSTNAME'] = 'oil-shed'
head, body = get('/widget.js')
js = body.decode()
ok(head.startswith('HTTP/1.0 200') and 'text/plain' in head and "'http://oil-shed.local'" in js and 'hawki-pico.local' not in js
   and 'ListWidget' in js, '/widget.js: the Scriptable widget, set to this Pico\'s own name (oil-shed.local)')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
