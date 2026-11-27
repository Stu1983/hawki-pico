"""python3 tests/test_built.py - the ready-built modules: app.py's built() uses b/X.mpy only while X.py is the source
it was built from (built.py), and tools/release.py builds them and refuses a release whose built copies are stale."""
import ast, hashlib, os, shutil, subprocess, sys, tempfile, types
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
FW = os.path.join(ROOT, 'firmware')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


src = open(os.path.join(FW, 'app.py')).read()
keep = [n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name in ('_rm', '_sha', '_runs_here', 'built')
        or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') == 'B' for t in n.targets)]
MPY = 6 | 3 << 8 | 7 << 10  # sys.implementation._mpy on the Pico 2 W (v1.29.0)
HDR = bytes([77, 6, 0, 31])


def h(b):
    return hashlib.sha256(b).hexdigest()


def setup(mods):
    """mods: name -> (source bytes, built bytes, recorded (src, built) or None for 'as they are')."""
    os.chdir(tempfile.mkdtemp())
    rec = {}
    for n, (s, b, r) in mods.items():
        open(n, 'wb').write(s)
        if b is not None:
            open(n[:-3] + '.mpy.html', 'wb').write(b)
        rec[n] = r or (h(s), h(b or b''))
    open('built.py', 'w').write('SRC = %r\n' % rec)


def run(mpy=MPY, path=None):
    g = {'os': os, '__name__': 'x'}
    exec(compile(ast.Module(keep, []), 'app.py', 'exec'), g)
    sys.modules.pop('built', None)
    old_path, old_impl = sys.path[:], sys.implementation
    sys.path.insert(0, os.getcwd())
    i = {k: v for k, v in vars(old_impl).items() if k != '_mpy'}  # (importing needs the rest: cache_tag)
    sys.implementation = types.SimpleNamespace(**dict(i, _mpy=mpy) if mpy is not None else i)
    p = path if path is not None else ['', '/lib']
    try:
        return g['built'](p), p
    finally:
        sys.path[:], sys.implementation = old_path, old_impl
        sys.modules.pop('built', None)


A, AB = b'x = 1\n', HDR + b'aaaa'
C, CB = b'y = 2\n', HDR + b'cccc'
setup({'a.py': (A, AB, None), 'c.py': (C, CB, None)})
n, p = run()
ok(n == 2 and p[0] == '/b' and open('b/a.mpy', 'rb').read() == AB and open('b/c.mpy', 'rb').read() == CB,
   'built from these sources: copied to b/, searched first')
st = os.stat('b/a.mpy').st_mtime_ns
n, p = run()
ok(n == 2 and os.stat('b/a.mpy').st_mtime_ns == st, 'the next start: nothing copied again')
open('a.py', 'wb').write(b'x = 3\n')  # (a fix put on by hand)
n, p = run()
ok(n == 1 and not os.path.exists('b/a.mpy') and os.path.exists('b/c.mpy'), 'a source changed by hand: that one runs as source')
open('a.py', 'wb').write(A)
open('b/a.mpy', 'wb').write(b'damaged')
n, p = run()
ok(n == 2 and open('b/a.mpy', 'rb').read() == AB, 'a damaged copy: copied again')
open('a.mpy.html', 'wb').write(HDR + b'other')
os.remove('b/a.mpy')
n, p = run()
ok(n == 1 and not os.path.exists('b/a.mpy'), 'a built file that is not the one built.py lists: never used')
setup({'a.py': (A, AB, None)})
os.mkdir('b')
open('b/gone.mpy', 'wb').write(HDR)
open('b/a.mpy.tmp', 'wb').write(b'half')
n, p = run()
ok(n == 1 and sorted(os.listdir('b')) == ['a.mpy'], "a module that's gone and a copy cut off part-way: removed")
n, p = run(mpy=7 | 3 << 8)
ok(n == 0 and p == ['', '/lib'] and os.listdir('b') == [], 'a MicroPython that loads another .mpy version: the sources')
n, p = run(mpy=None)
ok(n == 0 and p == ['', '/lib'], 'a MicroPython that loads no .mpy at all: the sources')
setup({'a.py': (A, bytes([77, 6, 0x1F, 31]) + b'x', None)})
ok(run()[0] == 0, 'machine code in it (never built so, but never used if it were): the sources')
os.chdir(tempfile.mkdtemp())
n, p = run()
ok(n == 0 and p == ['', '/lib'], 'no built.py (a release from before them): the sources')
n, p = run(path=['/b', ''])
ok(p == ['/b', ''], 'b/ already on the path: not twice')

setup({'a.py': (A, AB, None), 'c.py': (C, CB, None)})
os.makedirs('b/hawki_decode')
open('b/hawki_decode/__init__.py', 'w').write('raise RuntimeError')
n, p = run()
ok(n == 0 and p == ['', '/lib'], "something in b/ that can't be removed (a directory, a flash error): b/ never searched")
n, p = run(path=['/b', ''])
ok(n == 0 and p == [''], '... and taken off the path if it was on it')
import errno  # noqa: E402
real = os.stat
os.stat = lambda n, *a: (_ for _ in ()).throw(OSError(errno.EIO, 'io')) if n.startswith('b/') else real(n, *a)
try:
    setup({'a.py': (A, AB, None), 'c.py': (C, CB, None)})
    run()
    open('a.py', 'wb').write(b'x = 9\n')
    n, p = run()
finally:
    os.stat = real
ok(n == 0 and p == ['', '/lib'], 'a flash error checking an old copy is gone: b/ never searched (only "no such file" says gone)')
c = open(os.path.join(FW, 'core.py')).read()
i = c.index("path == '/file'")
ok("rm('b/%s.mpy' % name[:-3])" in c[i:i + 1200] and "sys.path.remove('/b')" in c[i:i + 1400],
   'a module put on by hand: its built copy removed, and the rest of this run imports from source')

# the release side (needs mpy-cross v1.29: skipped without it)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import release  # noqa: E402
mc = shutil.which(release.MPY_CROSS) or os.environ.get('HAWKI_MPY_CROSS')
if mc and release.MPY in subprocess.run([mc, '--version'], capture_output=True, text=True).stdout:
    d = tempfile.mkdtemp()
    for n in ('app.py', 'main.py', 'version.py', 'weather.py', 'tankcalc.py'):
        shutil.copy(os.path.join(FW, n), d)
    open(os.path.join(d, 'old.mpy.html'), 'wb').write(HDR)
    release.MPY_CROSS = mc
    s = release.build_mpy(d)
    ok(sorted(s) == ['tankcalc.py', 'weather.py'] and not os.path.exists(os.path.join(d, 'old.mpy.html'))
       and open(os.path.join(d, 'weather.mpy.html'), 'rb').read(4) == HDR,
       'built: every module but the boot files, the front door and version.py; one that is gone removed')
    ok(release.built_stale(d) == [], '... and built.py lists them as they are')
    g = {}
    exec(open(os.path.join(d, 'built.py')).read(), g)
    ok(g['SRC']['weather.py'][0] == h(open(os.path.join(d, 'weather.py'), 'rb').read()), '... by the sha-256 the Pico checks')
    open(os.path.join(d, 'weather.py'), 'a').write('\n# changed\n')
    ok(release.built_stale(d) == ['weather.py'], 'a source changed after the build: stale (no release made with it)')
else:
    print('skip release build (no mpy-cross v1.29: pip install mpy-cross==1.29.0.post2)')
sys.exit(1 if fails else 0)
