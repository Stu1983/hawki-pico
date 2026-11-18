"""python3 tests/test_oom.py - running out of memory for TLS after days up (firmware/app.py, notify.py).

MicroPython never moves memory, so after days up the free memory is in pieces too small for TLS and only a
restart joins it up again (the Pico is in a garage roof: nobody can pull the plug). So:
- an update install that runs out of memory restarts the Pico and installs first thing after the start;
- fetches and alerts that keep running out (twice in a row) restart it, once it has been up an hour;
- a signed-in Restart button.
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


class Reset(BaseException):
    pass


os.chdir(tempfile.mkdtemp())
up = [7200]
log = []
names = ('handle', 'send', 'parse_q', 'jb', 'BadRequest', '_Req', '_Resp', 'LOADS', 'MUTATING', 'read_body_to',
         'is_oom', 'note_oom', 'leave_note', 'take_note', 'with_room', 'send_alert', '_send_alert', 'sending', 'BATT_LOW', 'boot_install', 'update_info',
         'rm', 'OOM_UP_S', 'oom_run', 'alert_back', 'installing', 'manifest', 'resend_cut_off', 'read_note', 'redo_stale', 'REDO_SETTING', 'OOM_AGAIN_S')
T = types.SimpleNamespace(ticks_ms=lambda: 0, ticks_add=lambda a, b: a + b, ticks_diff=lambda a, b: a - b, time=lambda: 1795400000)


async def nap(s):
    up[0] += s
    await asyncio.sleep(0)  # (a real yield, as on the Pico: other tasks run here)


async def wait_for(c, t):
    return await c


def restart():
    log.append('restart')
    raise Reset()


g = {'time': T, 'asyncio': types.SimpleNamespace(sleep=nap, wait_for=wait_for), 'json': json, 'os': os, 'gc': __import__('gc'),
     'conns': [0], 'on_ap': lambda p: False, 'net_proof': lambda: None, 'page_s': [None], 'mono_s': lambda: up[0],
     'cfg': {'tanks': {}, 'pin': 'x'}, 'TOKEN': 'tok', 'authed': lambda a: a == 'good', 'save_cfg': lambda c: None,
     'print': lambda *a: None, 'make_room': lambda: log.append('room'), 'restart': restart, 'BOOT': 9,
     'VERSION': '1.3.0', 'boot_why': None, 'manifest_fresh': lambda: False, 'wd_hold': [0],
     'net_restart': [False], 'alert_redo': [None], 'mode_of': lambda t: t.get('mode') or 'use', 'listener': types.SimpleNamespace(s={}), 'hawki': {},
     'reading': lambda t, mm: (1300 - mm, None), 'reserve_of': lambda t: 200, 'net_trial': [False], 'wlan': types.SimpleNamespace(isconnected=lambda: True)}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []), 'app.py', 'exec'), g)
missing = [n for n in names if n not in g]
ok(not missing, 'everything under test is in app.py (%s)' % missing)


def enomem(*a):
    raise OSError(12, 'ENOMEM')


def call(fn, *a):
    try:
        return fn(*a)
    except Reset:
        return 'reset'
    except Exception as ex:
        return ex


# ---- fetches (weather, price, update check) through with_room ----
up[0], g['oom_run'][0] = 7200, 0
log.clear()
r1 = call(g['with_room'], enomem)
ok(isinstance(r1, OSError) and 'restart' not in log, 'one fetch out of memory (after its retry): no restart yet')
ok(call(g['with_room'], lambda: 5) == 5 and g['oom_run'][0] == 0, 'a fetch that works in between starts the count again')
call(g['with_room'], enomem)
ok(call(g['with_room'], enomem) == 'reset' and log[-1] == 'restart', 'two in a row, up 2 hours: restarts')
ok(json.load(open('boot.why')) == {'why': 'memory'}, '...and leaves the reason for the page')
ok(g['take_note']('boot.why') == {'why': 'memory'} and not os.path.exists('boot.why'), 'the reason is read once')
up[0], g['oom_run'][0] = 1200, 0
log.clear()
call(g['with_room'], enomem)
ok(call(g['with_room'], enomem) != 'reset' and 'restart' not in log, 'up 20 minutes: never restarts (fresh memory: a restart would not help)')
up[0], g['oom_run'][0] = 7200, 0
g['installing'][0] = True
call(g['with_room'], enomem)
ok(call(g['with_room'], enomem) != 'reset', 'never in the middle of an install')
g['installing'][0] = False
calls = []


def other(*a):
    calls.append(1)
    raise OSError(113, 'EHOSTUNREACH')


g['oom_run'][0] = 0
call(g['with_room'], other), call(g['with_room'], other)
ok(g['oom_run'][0] == 0 and len(calls) == 2, 'no internet is not out of memory: not counted, not retried')
ok(g['is_oom'](MemoryError()) and g['is_oom'](OSError(12)) and not g['is_oom'](ValueError(12)) and not g['is_oom'](OSError(-2)),
   'what counts as out of memory')
VE = ValueError(12)
VE.errno = 12  # (MicroPython: any exception made with a number has .errno)
ok(not g['is_oom'](VE), 'a ValueError(12) with .errno is not out of memory (only OSError counts)')
# memory that is really short, not in pieces: after a memory restart the next needs 6 hours up
g['boot_why'], g['oom_run'][0] = 'memory', 0
log.clear()
up[0] = 3 * 3600
call(g['with_room'], enomem)
ok(call(g['with_room'], enomem) != 'reset', 'after a memory restart: not again 3 hours later (no hourly loop)')
up[0], g['oom_run'][0] = 7 * 3600, 0
call(g['with_room'], enomem)
ok(call(g['with_room'], enomem) == 'reset', '...but after 6 hours up it may')
os.remove('boot.why')
g['boot_why'] = None

# ---- alerts ----
sys.path.insert(0, FW)
import notify  # noqa: E402 (the real module: its channels' errors set notify.oom)
g['notify'] = notify
notify._post = enomem
n = {'ntfy_topic': 'oil-alerts'}
g['cfg']['notify'] = n
up[0], g['oom_run'][0] = 7200, 0
log.clear()
r = asyncio.run(g['send_alert']('Oil', 'low', urgent=True))
ok(notify.oom[0] and 'ntfy' in r and 'restart' not in log, 'an alert out of memory: counted, not restarted yet (%s)' % r)
try:
    asyncio.run(g['send_alert']('Oil', 'low', urgent=True))
    ok(False, 'a second alert out of memory restarts')
except Reset:
    ok(log[-1] == 'restart', 'a second alert out of memory restarts')
os.remove('alert.redo')
# the alert a restart cut off is kept, and sent first after the start, marked sent the way its check would
A = 'c0:04:56:c4:0c:71'
g['cfg']['tanks'] = {A: {'name': 'Tank 1'}}
g['oom_run'][0] = 1
g['alert_back'][0] = g['alert_back'][1] = 0  # (the earlier failures' retry wait)
try:
    asyncio.run(g['send_alert']('Tank 1: no readings', 'Nothing new for 7 hours.', mark={'mac': A, 'k': 'silent', 'raw': 'ab12'}))
except Reset:
    pass
redo = json.load(open('alert.redo'))
ok(redo['title'] == 'Tank 1: no readings' and redo['mark']['k'] == 'silent' and redo['t'] == 1795400000, 'the cut-off alert is kept for after the restart')
g['alert_redo'][0] = g['read_note']('alert.redo')
notify._post = lambda *a: None
sent_titles = []
real_send = notify.send
notify.send = lambda n, t, m, u: sent_titles.append(t) or real_send(n, t, m, u)
up[0] = 300
g['alert_back'][0] = g['alert_back'][1] = 0
asyncio.run(g['resend_cut_off']())
al = g['cfg']['alerted'][A]
ok(sent_titles == ['Tank 1: no readings'] and al.get('silent') and al.get('silent_raw') == 'ab12' and g['alert_redo'][0] is None
   and not os.path.exists('alert.redo'), 'after the start: sent once, marked sent, and its file gone (%s)' % al)
asyncio.run(g['resend_cut_off']())
ok(sent_titles == ['Tank 1: no readings'], '...and only once')
g['alert_redo'][0] = {'title': 'x', 'msg': 'y', 'mark': {'mac': A, 'k': 'reorder'}}
g['cfg']['tanks'][A]['mode'] = 'off'
asyncio.run(g['resend_cut_off']())
ok(sent_titles == ['Tank 1: no readings'] and g['alert_redo'][0] is None, 'its tank turned off meanwhile: dropped')
g['cfg']['tanks'][A]['mode'] = None
NOW = 1795400000
R = lambda k, **x: dict({'title': 'x', 'msg': 'y', 't': NOW - 600, 'mark': {'mac': A, 'k': k}}, **x)
st = lambda r, n={}: g['redo_stale'](r, n, NOW)
g['cfg']['alerted'] = {}
ok(st(R('reorder')) is None and st(R('battery')) is None and st(R('drop')) is None, 'a fresh cut-off alert is still sent')
ok(st(R('reorder', t=NOW - 7 * 3600)) == 'old', 'older than 6 hours: dropped')
ok(st(R('silent'), {'silent': False}) == 'warning turned off' and st(R('drop'), {'drops': False}) == 'warning turned off', 'its warning turned off meanwhile: dropped')
g['cfg']['alerted'] = {A: {'drop': NOW - 60}}
ok(st(R('drop')) == 'already sent', 'its own check sent it meanwhile: not sent twice')
g['cfg']['alerted'] = {A: {'drop': NOW - 20 * 3600}}
ok(st(R('drop')) is None, '...an older drop warning doesn\'t count')
g['cfg']['alerted'] = {}
g['listener'].s[A] = {'chg': NOW - 30, 'raw': 'cd34'}
ok(st(R('silent')) == 'readings again', '"no readings" but a new measurement came: dropped')
g['listener'].s.clear()
g['hawki'][A] = {'level': 300}
ok(st(R('reorder')) == 'filled up', '"order oil" but the tank reads above the reorder level now: dropped')
g['hawki'][A] = {'level': 1200}
ok(st(R('reorder')) is None, '...still low: sent')
g['cfg']['tanks'][A]['mode'] = 'standby'
ok(st(R('reorder')) == 'not in use', 'an "order oil" for a tank put on standby meanwhile: dropped (standby has no warning of its own)')
g['cfg']['tanks'][A]['mode'] = None
g['hawki'].clear()
g['listener'].s[A] = {'chg': None, 'raw': 'new1'}
ok(st(R('silent', mark={'mac': A, 'k': 'silent', 'raw': 'old1'})) == 'readings again', '"no readings": the first packet after the start is a different reading: dropped')
g['listener'].s[A] = {'chg': None, 'raw': 'old1'}
ok(st(R('silent', mark={'mac': A, 'k': 'silent', 'raw': 'old1'})) is None, '...still the stuck reading: sent')
g['listener'].s.clear()
# the replay and the drop check at the same time: one warning, not two
g['cfg']['alerted'] = {}
g['alert_back'][0] = g['alert_back'][1] = 0
both = []


async def drop_check_meanwhile():  # the recorder's check (app.py drop_check): its marker, then send_alert
    a = g['cfg']['alerted'].setdefault(A, {})
    if T.time() - a.get('drop', 0) > 12 * 3600:
        res = await g['send_alert']('Tank 1: oil dropping fast', 'm', urgent=True, mark={'mac': A, 'k': 'drop'})
        if 'ok' in res.values():
            a['drop'] = int(T.time())


notify._post = lambda *a: None
notify.send = lambda n, t, m, u: both.append(t) or real_send(n, t, m, u)
T.time = lambda: NOW
for first in ('replay', 'check'):
    both.clear()
    g['cfg']['alerted'] = {}
    g['alert_back'][0] = g['alert_back'][1] = 0
    g['alert_redo'][0] = R('drop', t=NOW - 60)

    async def together():
        jobs = [g['resend_cut_off'](), drop_check_meanwhile()]
        await asyncio.gather(*(jobs if first == 'replay' else jobs[::-1]))
    asyncio.run(together())
    ok(len(both) == 1 and not g['sending'], 'the replay and the drop check at once (%s first): the warning goes once (%s)' % (first, both))
    asyncio.run(g['resend_cut_off']())
    ok(len(both) == 1 and g['alert_redo'][0] is None, '...and the replay is then dropped as already sent, never sent later')
# an exception part-way: nothing left marked sent or "being sent"
notify.send = lambda n, t, m, u: (_ for _ in ()).throw(MemoryError())
g['cfg']['alerted'] = {A: {}}
g['alert_redo'][0] = R('battery', t=NOW - 60)
try:
    asyncio.run(g['resend_cut_off']())
except MemoryError:
    pass
ok(not g['cfg']['alerted'][A] and not g['sending'] and g['alert_redo'][0], 'send_alert raising: not marked sent, not stuck "being sent", still to send')
notify.send = real_send
g['hawki'][A] = {'battery': 100}
ok(st(R('battery')) == 'battery fine now', 'a low-battery warning, but a new battery reads 100%: dropped')
g['hawki'][A] = {'battery': 15}
ok(st(R('battery')) is None, '...still low: sent')
g['hawki'].clear()
notify._post = enomem
g['alert_redo'][0] = R('battery', t=NOW - 60)
g['cfg']['alerted'] = {A: {}}
up[0] = 100
asyncio.run(g['resend_cut_off']())
ok('battery' not in g['cfg']['alerted'][A] and g['alert_redo'][0], 'a replay that fails is not left marked sent; tried again later')
notify.send = real_send
notify._post = lambda *a: None
open('alert.redo', 'w').write(json.dumps(R('reorder')))
ok(g['read_note']('alert.redo') and os.path.exists('alert.redo'), 'reading the cut-off alert at a start keeps its file (another restart before it goes doesn\'t lose it)')
g['alert_redo'][0] = R('reorder', t=NOW - 7 * 3600)
asyncio.run(g['resend_cut_off']())
ok(sent_titles == ['Tank 1: no readings'] and g['alert_redo'][0] is None and not os.path.exists('alert.redo'), 'a stale one is dropped and its file removed')
notify.send = real_send
g['oom_run'][0] = 1
asyncio.run(g['send_alert']('Oil', 'low', urgent=True))
ok(g['oom_run'][0] == 0 and not notify.oom[0], 'an alert that goes resets the count')
notify._post = lambda *a: (_ for _ in ()).throw(OSError(-2, 'no host'))
g['oom_run'][0] = 1
asyncio.run(g['send_alert']('Oil', 'low', urgent=True))
ok(g['oom_run'][0] == 1 and not notify.oom[0], 'an alert failing for another reason is not counted')


# ---- the install button ----
def req(raw):
    w = g['_Resp']()
    try:
        asyncio.run(g['handle'](g['_Req'](raw), w))
    except Reset:
        return 'reset', w
    return w.head.split(b'\r\n')[0].decode() or 'no answer', w


def post(path, body, auth=b'good'):
    return req(b'POST %s HTTP/1.0\r\nX-Auth: %s\r\nContent-Length: %d\r\n\r\n' % (path, auth, len(body)) + body)


M = {'version': '1.3.1', 'files': {}, 'ref': 'v1.3.1'}
upd = types.SimpleNamespace(check=lambda v: {'manifest': M}, vtuple=lambda v: tuple(int(x) for x in v.split('.')),
                            install=enomem, tidy=lambda: log.append('tidy'))
sys.modules['updater'] = upd
log.clear()
up[0] = 7200
r, w = post(b'/api/update/install', b'{"version": "1.3.1"}')
ok(r == 'reset' and b'202' in w.head, 'install out of memory: answers 202 then restarts (%s)' % w.head.split(b'\r\n')[0])
want = json.load(open('upd.want'))
ok(want['v'] == '1.3.1' and want['id'], '...leaving "install 1.3.1 after the restart" (%s)' % want)
os.remove('upd.want')
upd.install = lambda m, v: (_ for _ in ()).throw(ValueError('app.py did not match the release'))
r, w = post(b'/api/update/install', b'{"version": "1.3.1"}')
ok(r.startswith('HTTP/1.0 400') and not os.path.exists('upd.want'), 'any other failure: a 400 as before, no restart (%s)' % r)
upd.install = enomem
open('upd.pending', 'w').write('{}')
r, w = post(b'/api/update/install', b'{"version": "1.3.1"}')
ok(r.startswith('HTTP/1.0 400') and not os.path.exists('upd.want'), 'an update still being confirmed: no restart-and-install (%s)' % r)
os.remove('upd.pending')
upd.check = enomem
r, w = post(b'/api/update/install', b'{"version": "1.3.1"}')
ok(r == 'reset' and os.path.exists('upd.want'), 'out of memory already at the check: restart-and-install too')
os.remove('upd.want')
upd.check = lambda v: {'manifest': M}
g['installing'][0] = False

# ---- after the restart: boot_install ----
installed = []
upd.install = lambda m, v: installed.append((m['version'], v)) or m['version']
log.clear()
try:
    asyncio.run(g['boot_install']({'v': '1.3.1', 'id': '9-7200'}))
    ok(False, 'installs then restarts')
except Reset:
    ok(installed == [('1.3.1', '1.3.0')] and log[-1] == 'restart' and 'tidy' in log, 'after the restart: installs, then restarts onto it')
g['installing'][0] = False
upd.install = enomem
ok(asyncio.run(g['boot_install']({'v': '1.3.1', 'id': 'a1'})) is False, 'out of memory again: gives up (no restart loop)')
last = json.load(open('upd.last'))
ok(last['ok'] is False and last['id'] == 'a1' and last['stage'] == 'install' and 'memory' in last['reason'],
   '...and says so on the page (%s)' % last)
ok(g['installing'][0] is False, '...and the install button works again')
M['version'] = '1.3.2'
upd.install = lambda m, v: installed.append(m['version'])
ok(asyncio.run(g['boot_install']({'v': '1.3.1', 'id': 'a2'})) is False and installed[-1] != '1.3.2',
   'a newer release out by then: never installed unseen')
M['version'] = '1.3.1'
clock = [1000000000]
T.time = lambda: clock[0]
up[0] = 0
upd.install = lambda m, v: (_ for _ in ()).throw(OSError(-9984, 'certificate not yet valid'))  # (what TLS says then)
waited = asyncio.run(g['boot_install']({'v': '1.3.1', 'id': 'a3'}))
ok(waited is False and up[0] >= 180, 'with the clock unset it waits for it (certificates need the date), then gives up (%d s)' % up[0])
T.time = lambda: 1795400000
g['wlan'] = types.SimpleNamespace(isconnected=lambda: (_ for _ in ()).throw(OSError(5, 'EIO')))
ok(asyncio.run(g['boot_install']({'v': '1.3.1', 'id': 'a4'})) is False and g['installing'][0] is False, 'the Wi-Fi check itself failing: handled, not raised out of main')
g['wlan'] = types.SimpleNamespace(isconnected=lambda: True)

# ---- the restart button ----
log.clear()
r, w = post(b'/api/restart', b'{}', auth=b'bad')
ok(r.startswith('HTTP/1.0 401') or r.startswith('HTTP/1.0 403'), 'restart needs the PIN (%s)' % r)
r, w = post(b'/api/restart', b'{}')
ok(r == 'reset' and b'200' in w.head, 'signed in: answers, then restarts')
g['installing'][0] = True
r, w = post(b'/api/restart', b'{}')
ok(r.startswith('HTTP/1.0 409'), 'not while an update is being installed (%s)' % r)
g['installing'][0] = False

# ---- main(): the install runs before the other tasks fill the memory ----
body = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'main')
order = [ast.unparse(s)[:60] for s in body.body]
i_inst = next(i for i, s in enumerate(order) if s.startswith('if want'))
i_tasks = next(i for i, s in enumerate(order) if s.startswith('for fn, name in tasks'))
i_srv = next(i for i, s in enumerate(order) if 'start_server' in s)
ok(i_inst < i_tasks < i_srv and any('wifi_keeper' in s for s in order[:i_inst]), 'main: Wi-Fi, then the install, then everything else')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
