"""python3 tests/test_etag.py - pages are revalidated, not re-sent (firmware/app.py send_page).

ui.html (87 KB), hist.html and common.js only change with an update, but went out in full on every visit over
weak Wi-Fi (Cache-Control: no-store). Now no-cache + an ETag of version and size: unchanged -> 304, no body.
"""
import ast, asyncio, os, tempfile, types

src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
tree = ast.parse(src)
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


class W:
    def __init__(self):
        self.b = b''

    def write(self, x):
        self.b += bytes(x)

    async def drain(self):
        pass


os.chdir(tempfile.mkdtemp())
open('ui.html', 'w').write('x' * 5000)
g = {'os': os, 'asyncio': types.SimpleNamespace(wait_for=lambda c, t: c), 'VERSION': '1.2.54'}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in ('send_file', 'send_page')], []), 'app.py', 'exec'), g)
w = W()
asyncio.run(g['send_page'](w, 'ui.html', 'text/html'))
head = w.b.split(b'\r\n\r\n')[0].decode()
tag = head.split('ETag: ')[1].split('\r\n')[0]
ok(head.startswith('HTTP/1.0 200') and tag.startswith('"1.2.54-5000-') and 'no-cache' in head and len(w.b) > 5000, 'first visit: the page, with an ETag (%s)' % tag)
w = W()
asyncio.run(g['send_page'](w, 'ui.html', 'text/html', tag))
ok(w.b.startswith(b'HTTP/1.0 304') and len(w.b) < 200, 'revisit, unchanged: 304 and no body (%d bytes instead of 5000+)' % len(w.b))
w = W()
asyncio.run(g['send_page'](w, 'ui.html', 'text/html', tag.replace('1.2.54', '1.2.53')))
ok(w.b.startswith(b'HTTP/1.0 200'), 'after an update (new version): the new page')
for label, inm in (('weak', 'W/' + tag), ('in a list', '"other", ' + tag)):
    w = W()
    asyncio.run(g['send_page'](w, 'ui.html', 'text/html', inm))
    ok(w.b.startswith(b'HTTP/1.0 304'), 'a %s ETag still matches' % label)
st = os.stat('ui.html')
open('ui.html', 'w').write('y' * 5000)  # same size (a maintenance upload, or an update's swap before the restart)
os.utime('ui.html', (st.st_atime, st.st_mtime + 5))
w = W()
asyncio.run(g['send_page'](w, 'ui.html', 'text/html', tag))
ok(w.b.startswith(b'HTTP/1.0 200'), 'a file changed without a new version, even at the same size: the new page')
w = W()
asyncio.run(g['send_file'](w, 'ui.html', 'text/html'))
ok(b'no-store' in w.b.split(b'\r\n\r\n')[0], 'everything else stays no-store (history, readings)')
handle = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'handle')
ok("b'if-none-match:'" in ast.unparse(handle), 'the request handler reads If-None-Match')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
