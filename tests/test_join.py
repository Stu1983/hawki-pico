"""python3 tests/test_join.py - joining the home Wi-Fi from the setup screen (firmware/app.py try_join, /api/wifi/try).

The network is tried while the setup Wi-Fi stays up: saved only once it works, a wrong password or a missing network said
as such, and the setup Wi-Fi kept up for a while after joining so the phone can be told where to find the monitor.
"""
import ast, asyncio, json, os, types

src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
tree = ast.parse(src)
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


class Wlan:
    def __init__(self, script):
        self.script, self.calls, self.up = list(script), [], False

    def connect(self, s, p, channel=None, bssid=None):
        self.calls.append(('connect', s, p) + ((channel,) if channel else ()) + ((bssid,) if bssid else ()))

    def disconnect(self):
        self.calls.append(('disconnect',))
        self.up = False

    def status(self, *a):
        v = self.script.pop(0) if self.script else self.last
        self.last = v
        if v == 3:
            self.up = True
        return v

    def isconnected(self):
        return self.up or (self.script[:1] == [3] and self.status() == 3)

    def config(self, k):
        return b'\x28\xcd\xc1\x00\x00\x01'

    def ifconfig(self):
        return ('192.168.1.57', '255.255.255.0', '192.168.1.1', '192.168.1.1')


async def nosleep(s):
    await asyncio.sleep(0)


T = types.SimpleNamespace(ticks_ms=lambda: 0, ticks_add=lambda a, b: a + b, ticks_diff=lambda a, b: a - b, time=lambda: 1795400000)
names = ('setup_restart_ok', 'ap_channel', 'note_seen', 'wifi_seen', 'SEEN_S', 'aps_of', 'best_ap', 'STICK_DB', 'pick_ap', 'keep_ap', 'keeper_hit', 'join_wifi', 'try_join', 'join_view', 'joining', 'join', 'ap_hold', 'handle', 'send', 'parse_q', 'jb', 'BadRequest', '_Req', '_Resp',
         'LOADS', 'ICON_PATHS', 'WEB_MANIFEST', 'MUTATING', 'read_body_to', 'FIRST_PIN_SECS', 'captive_to')
saved = []
aps = []
CLOCK = [1000]
PENDING = [False]


def fresh(script, have=None):
    g = {**__import__('_phstub').STUB, 'binascii': __import__('binascii'), 'time': T, 'json': json, 'os': os, 'gc': __import__('gc'), 'print': lambda *a: None,
         'asyncio': types.SimpleNamespace(sleep=nosleep, wait_for=asyncio.wait_for),
         'network': types.SimpleNamespace(STAT_WRONG_PASSWORD=-3, STAT_NO_AP_FOUND=-2, STAT_CONNECT_FAIL=-1),
         'wlan': Wlan(script), 'led': types.SimpleNamespace(toggle=lambda: None), 'net_apply': lambda: None, 'ap_on': lambda: aps.append(1),
         'cfg': dict(have or {}, tanks={}, pin='x'), 'save_cfg': lambda c: saved.append(dict(c)), 'mono_s': lambda: CLOCK[0],
         'first_pin_until': [1800], 'ntp_wait': [5, 2], 'ntp_sync': nosleep_ntp, 'conns': [0], 'on_ap': lambda p: True,
         'net_proof': lambda: None, 'page_s': [None], 'TOKEN': 'tok', 'authed': lambda a: a == 'good',
         'unset': types.SimpleNamespace(clear=lambda m: None), 'last_saved': {}, 'HOSTNAME': 'hawki-pico',
         'ap': types.SimpleNamespace(active=lambda: True, ifconfig=lambda: ('192.168.4.1',) * 4),
         'installing': [False], 'update_info': lambda: {'pending': PENDING[0]}}
    exec(compile(ast.Module([n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in names
                             or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []), 'app.py', 'exec'), g)
    return g


async def nosleep_ntp():
    pass


def run(g, ssid='HomeNet', pw='rightpassword'):
    g['join'][0] = {'ssid': ssid, 'pw': pw, 'state': 'trying'}
    asyncio.run(g['try_join'](g['join'][0]))
    return g['join'][0]


saved[:] = []
g = fresh([1, 1, 1, 3])
j = run(g)
ok(j['state'] == 'ok' and j['ip'] == '192.168.1.57' and 'pw' not in j, 'it joins: "ok", with its new address, the password not kept in the answer')
ok(saved and saved[-1]['ssid'] == 'HomeNet' and saved[-1]['pw'] == 'rightpassword', 'saved only now it works')
ok(g['wlan'].calls[0] == ('disconnect',) and g['wlan'].calls[1] == ('connect', 'HomeNet', 'rightpassword') and aps,
   'always drops whatever connect was under way first (never a second on top), with the setup Wi-Fi up (%r)' % g['wlan'].calls)
ok(g['ap_hold'][0] == 1600 and g['first_pin_until'][0] == 2800, 'the setup Wi-Fi stays up 10 minutes, and a first PIN can still be set from home for 30')
ok(json.dumps(g['join_view']()) == '{"ssid": "HomeNet", "state": "ok", "ip": "192.168.1.57", "k": null}', 'what the page sees: no password (%s)' % json.dumps(g['join_view']()))

saved[:] = []
g = fresh([1, 1, -3], have={'ssid': 'Old', 'pw': 'oldpassword'})
j = run(g, pw='wrongpassword')
ok(j['state'] == 'password' and not saved, 'a wrong password: "password", nothing saved (%r)' % j)
ok(g['cfg']['ssid'] == 'Old' and ('disconnect',) in g['wlan'].calls, '...the old network kept to go back to, the attempt dropped')

g = fresh([-2] * 30)
ok(run(g)['state'] == 'missing', 'a network it cannot see (for 10 s): "missing"')
g = fresh([-2, -2, 1, 3])
ok(run(g)['state'] == 'ok', 'not seen for a moment, then found: still joins')
g = fresh([1] * 100)
ok(run(g)['state'] == 'failed', 'never connects within 30 s: "failed"')

# joined on the channel the network was heard on (no look round every channel, which takes the setup Wi-Fi off the air)
g = fresh([1, 3])
g['note_seen']([(b'HomeNet', b'far', 11, -84), (b'HomeNet', b'near', 6, -60), (b'HomeNet', b'mid', 6, -77), (b'Other', b'x', 1, -40)])
j = run(g)
ok(j['state'] == 'ok' and ('connect', 'HomeNet', 'rightpassword', 6, b'near') in g['wlan'].calls,
   'several access points: joined the strongest by its address, on its channel (%r)' % g['wlan'].calls)
g = fresh([-2] * 25 + [1, 3])
g['note_seen']([(b'HomeNet', b'', 6, -60)])
j = run(g)
ok(j['state'] == 'ok' and g['wlan'].calls[1][3:4] == (6,) and g['wlan'].calls[-1] == ('connect', 'HomeNet', 'rightpassword'),
   'not found on that channel: tried again on any, and joins (%r)' % g['wlan'].calls)
g = fresh([1, -3])
g['note_seen']([(b'HomeNet', b'', 6, -60)])
j = run(g)
ok(j['state'] == 'password' and sum(c[0] == 'connect' for c in g['wlan'].calls) == 1, 'a wrong password on that channel: said at once, not tried again')
g = fresh([1, 3])
j = run(g)
ok(('connect', 'HomeNet', 'rightpassword') in g['wlan'].calls, 'never heard (typed in): joined on any channel')
# a later scan that misses the near access point (the setup Wi-Fi was up): the near one, heard minutes ago, still wins
g = fresh([1, 3])
g['note_seen']([(b'HomeNet', b'near', 6, -60), (b'HomeNet', b'far', 1, -80)])
CLOCK[0] += 120
g['note_seen']([(b'HomeNet', b'far', 1, -81)])
run(g)
ok(('connect', 'HomeNet', 'rightpassword', 6, b'near') in g['wlan'].calls, 'a later scan missing the near access point: still the near one (%r)' % g['wlan'].calls)
CLOCK[0] += 600
g['note_seen']([(b'HomeNet', b'far', 1, -81)])
ok(g['best_ap'](b'HomeNet') == (-81, 1, b'far') and b'near' not in g['wifi_seen'][b'HomeNet'],
   'not heard for over 10 minutes: forgotten (%r)' % (g['best_ap'](b'HomeNet'),))
CLOCK[0] = 1000
# the strongest remembered one has gone: the next strongest before any (never straight to "any", which picked a far one)
g = fresh([-2] * 11 + [1, 3])  # (a missing access point is given up on after 10 checks when it was pinned)
g['note_seen']([(b'HomeNet', b'A', 6, -45), (b'HomeNet', b'B', 11, -60), (b'HomeNet', b'C', 1, -80)])
j = run(g)
cs = [c for c in g['wlan'].calls if c[0] == 'connect']
ok(j['state'] == 'ok' and cs[0][4:] == (b'A',) and cs[1][3:] == (11, b'B') and len(cs) == 2 and b'A' not in g['wifi_seen'][b'HomeNet'],
   'the strongest gone: the next strongest, and the gone one not first choice again (%r)' % cs)
g = fresh([-2] * 22 + [1, 3])
g['note_seen']([(b'HomeNet', b'A', 6, -45), (b'HomeNet', b'B', 11, -60), (b'HomeNet', b'C', 1, -80)])
j = run(g)
cs = [c for c in g['wlan'].calls if c[0] == 'connect']
ok(j['state'] == 'ok' and len(cs) == 3 and cs[2] == ('connect', 'HomeNet', 'rightpassword'), 'the nearest two both gone: then any (%r)' % cs)
g = fresh([1] * 200)
g['note_seen']([(b'HomeNet', b'A', 6, -45), (b'HomeNet', b'B', 11, -60)])
slept = [0]


async def counted(t):
    slept[0] += t
g['asyncio'].sleep = counted
j = run(g)
ok(j['state'] == 'failed' and slept[0] <= 60, 'nothing answers at all: gives up within a minute (%.0f s), inside the page\'s 75' % slept[0])

# a finished setup is forgotten once its hold is over or the connection goes (wifi_keeper's check, as written)
src_keeper = src[src.index('async def wifi_keeper'):src.index('# ---------- history')]
ok("join[0]['state'] == 'ok' and (not wlan.isconnected() or mono_s() >= ap_hold[0])" in src_keeper and 'join[0] = None' in src_keeper,
   'the keeper forgets a finished setup once its time is up or the Wi-Fi drops')
# the keeper's own reconnects: scan, then the strongest access point; every third try any of them
ks = src_keeper[src_keeper.index("if cfg.get('ssid') and not wlan.isconnected():"):src_keeper.index('for _ in range(20):')]
ok('note_seen(wlan.scan())' in ks and "join_wifi(cfg['ssid'], cfg.get('pw', ''), keeper_hit[0])" in ks and 'pick_ap(' in ks and 'wifi_try[0] % 3 == 0' in ks
   and 'wlan.connect(' not in ks, 'reconnects scan first and join the access point picked (the one it was on, else the nearest; every third: any)')
ok(ks.index('wlan.disconnect()') < ks.index('join_wifi('), 'each reconnect drops the last attempt first (never a second connect on top)')
# it goes back to the access point it was on (signals on a mesh sit within a few dB and swap from scan to scan)
g = fresh([1, 3])
g['note_seen']([(b'HomeNet', b'\x01near', 1, -69), (b'HomeNet', b'\x06also', 6, -72)])
run(g)
ok(g['cfg'].get('ap_b') == '016e656172', 'setup joined the strongest; it is remembered (%r)' % g['cfg'].get('ap_b'))
g['note_seen']([(b'HomeNet', b'\x01near', 1, -76), (b'HomeNet', b'\x06also', 6, -70)])
ok(g['pick_ap'](b'HomeNet')[2] == b'\x01near', 'next time the other reads 6 dB stronger: still the same one')
g['note_seen']([(b'HomeNet', b'\x01near', 1, -85), (b'HomeNet', b'\x06also', 6, -70)])
ok(g['pick_ap'](b'HomeNet')[2] == b'\x06also', '15 dB weaker than another: moves')
CLOCK[0] += 700
g['note_seen']([(b'HomeNet', b'\x06also', 6, -72)])
ok(g['pick_ap'](b'HomeNet')[2] == b'\x06also', 'gone: the strongest there is')
CLOCK[0] = 1000
g['keep_ap']((-72, 6, b'\x06also'))
ok(g['cfg']['ap_b'] == '06616c736f', 'a join that worked elsewhere: that one remembered')
g['keep_ap'](None)
ok('ap_b' not in g['cfg'], 'joined just anyhow: nothing remembered')
# told its channel only for the setup join (it stalls big transfers); the keeper's joins: the access point alone
g = fresh([])
g['join_wifi']('HomeNet', 'pw', (-60, 6, b'near'))
g['join_wifi']('HomeNet', 'pw', (-60, 6, b'near'), on_channel=True)
g['join_wifi']('HomeNet', 'pw', None)
ok(g['wlan'].calls == [('connect', 'HomeNet', 'pw', b'near'), ('connect', 'HomeNet', 'pw', 6, b'near'), ('connect', 'HomeNet', 'pw')],
   'normal joins: the access point only; the setup join: with its channel; none known: any (%r)' % g['wlan'].calls)
ok('on_channel=True' not in src_keeper, 'the keeper never tells the chip the channel')
ok('keep_ap(keeper_hit[0])' in src_keeper and 'keeper_hit[:] = [pick_ap(' in src_keeper, 'the keeper joins the remembered one and remembers what worked')
outer = src_keeper[src_keeper.index('led.value(1)'):][:300]
ok('if keeper_hit[1]:' in outer and 'keep_ap(keeper_hit[0])' in outer, 'recorded whenever it is first seen joined (a join that came late too)')
g = fresh([1, 3])
g['keeper_hit'][:] = [(-50, 11, b'old'), True]
run(g)
ok(g['keeper_hit'][1] is False, 'a setup join drops the keeper\'s pending one: never recorded over the setup\'s choice')
ok("wifi_try[0] = 0" in src_keeper[src_keeper.index("led.value(1)"):][:120], 'the count of failed tries starts again whenever it is found joined (a late join too)')

ok('mono_s() >= ap_hold[0] and not joining()' in src_keeper, 'the setup Wi-Fi is never switched off with a join waiting')
hold = src_keeper[src_keeper.index('mono_s() >= ap_hold[0] and not joining()'):]
ok(hold.index('restart()') < hold.index('ap.active(False)'), 'after a setup join, the hold running out restarts the Pico (never the setup Wi-Fi switched off under it)')
w20 = src_keeper[src_keeper.index('for _ in range(20):'):]
ok(w20.index('if joining():') < w20.index('if wlan.isconnected():'), "the keeper's own connect wait gives way to a join at once")

# the request: signed in, checked, one at a time


def post(g, body, auth='good'):
    w = types.SimpleNamespace(out=b'', get_extra_info=lambda k: ('192.168.4.16', 0))
    w.write = lambda b: setattr(w, 'out', w.out + b)

    async def drain():
        pass
    w.drain = drain
    raw = json.dumps(body).encode()
    asyncio.run(g['handle'](g['_Req'](b'POST /api/wifi/try HTTP/1.0\r\nX-Auth: %s\r\nContent-Length: %d\r\n\r\n' % (auth.encode(), len(raw)) + raw), w))
    return w.out.split(b'\r\n')[0].decode(), w.out.split(b'\r\n\r\n', 1)[1].decode()


g = fresh([])
r = post(g, {'ssid': 'HomeNet', 'pw': 'rightpassword'}, auth='bad')
ok(r[0].startswith('HTTP/1.0 401') and not g['join'][0], 'not signed in: refused (%s)' % r[0])
for body, why in (({'ssid': '', 'pw': 'rightpassword'}, 'no network'), ({'ssid': 'x' * 33, 'pw': 'rightpassword'}, 'a name over 32 bytes'),
                  ({'ssid': 'HomeNet', 'pw': 'short'}, 'a 5-character password'), ({'ssid': 'HomeNet', 'pw': 'p' * 64}, 'a 64-character password')):
    r = post(g, body)
    ok(r[0].startswith('HTTP/1.0 400') and not g['join'][0], '%s: refused (%s %s)' % (why, r[0], r[1]))
r = post(g, {'ssid': 'Open cafe', 'pw': ''})
ok(r[0].startswith('HTTP/1.0 200') and g['join'][0] == {'ssid': 'Open cafe', 'pw': '', 'state': 'trying', 'k': ''}, 'an open network (no password): tried')
r = post(g, {'ssid': 'HomeNet', 'pw': 'rightpassword'})
ok(r[0].startswith('HTTP/1.0 409') and g['join'][0]['ssid'] == 'Open cafe', 'one already being tried: the second waits its turn (%s)' % r[0])
# the setup Wi-Fi starts on the home network's channel, so joining it doesn't move it (and drop the phone)
apc = fresh([])['ap_channel']
scan = [(b'Next door', b'', 1, -85), (b'HomeNet', b'', 6, -60), (b'HomeNet', b'', 11, -84), (b'Cafe', b'', 3, -40)]
ok(apc(scan, b'') == 3, 'nothing saved: the strongest network heard (%r)' % apc(scan, b''))
ok(apc(scan, b'HomeNet') == 6, 'a saved network: its strongest channel, even with a stronger stranger (%r)' % apc(scan, b'HomeNet'))
ok(apc(scan, b'Gone') == 3, 'a saved network not heard: the strongest')
ok(apc([(b'x', b'', 36, -40), (b'y', b'', 0, -50)], b'') is None and apc([], b'') is None, 'no 2.4 GHz channel to go by: the default (%r)' % apc([(b'x', b'', 36, -40)], b''))
# the page asking by name from the home Wi-Fi: open to any origin, no password
g = fresh([])
g['join'][0] = {'ssid': 'HomeNet', 'state': 'ok', 'ip': '192.168.1.57', 'k': 'abc123'}
w = types.SimpleNamespace(out=b'', get_extra_info=lambda k: ('192.168.1.40', 0))
w.write = lambda b: setattr(w, 'out', w.out + b)


async def _d():
    pass
w.drain = _d
g['on_ap'] = lambda p: False
g['BOOT'] = 7
for qk, want in ((b'?k=abc123', b'{"ssid": "HomeNet", "state": "ok", "ip": "192.168.1.57", "k": "abc123", "via_ap": false, "boot": 7, "id": "28:cd:c1:00:00:01"}'),
                 (b'', b'{"boot": 7, "id": "28:cd:c1:00:00:01"}'), (b'?k=wrong', b'{"boot": 7, "id": "28:cd:c1:00:00:01"}')):
    w.out = b''
    asyncio.run(g['handle'](g['_Req'](b'GET /api/setup/status' + qk + b' HTTP/1.0\r\nHost: hawki-pico.local\r\n\r\n'), w))
    ok(w.out.startswith(b'HTTP/1.0 200') and b'Access-Control-Allow-Origin: *' in w.out and w.out.endswith(want),
       'GET /api/setup/status%s: %s (%r)' % (qk.decode(), 'its join, readable from the setup page' if qk == b'?k=abc123' else 'only which start this is, for anyone else', w.out[-90:]))
g['join'][0]['k'] = ''
w.out = b''
asyncio.run(g['handle'](g['_Req'](b'GET /api/setup/status?k= HTTP/1.0\r\nHost: x\r\n\r\n'), w))
ok(w.out.endswith(b'{"boot": 7, "id": "28:cd:c1:00:00:01"}'), 'a join started without a key: never given out by name, only which start this is')
# Finish: restarts on the home Wi-Fi; refused while not on it yet


def finish(up, broken=False):
    g = fresh([], have={'ssid': 'HomeNet'} if up else {})
    g['wlan'].up = up
    rs = []
    g['restart'] = lambda: rs.append(1)
    w = types.SimpleNamespace(out=b'', get_extra_info=lambda k: ('192.168.4.16', 0))
    w.write = lambda b: setattr(w, 'out', w.out + b)

    async def drain():
        if broken and w.out.startswith(b'HTTP/1.0 200'):
            raise OSError(104, 'reset')
    w.drain = drain
    try:
        asyncio.run(g['handle'](g['_Req'](b'POST /api/setup/done HTTP/1.0\r\nX-Auth: good\r\nContent-Length: 0\r\n\r\n'), w))
    except OSError:
        pass
    finish.g = g
    return w.out.split(b'\r\n')[0].decode(), rs


r, rs = finish(True)
ok(r.startswith('HTTP/1.0 200') and not rs and finish.g['ap_hold'][0] == 1, 'Finish on the home Wi-Fi: answered; the keeper restarts it (one place decides when) (%s)' % r)
r, rs = finish(False)
ok(r.startswith('HTTP/1.0 409') and not rs and finish.g['ap_hold'][0] == 0, 'Finish before joining: refused (%s)' % r)
r, rs = finish(True, broken=True)
ok(finish.g['ap_hold'][0] == 1, 'Finish whose answer is cut off: the restart is still on (it was agreed)')
ok("if not setup_restart_ok():" in hold and hold.index('setup_restart_ok') < hold.index('restart()'),
   'the keeper waits for an update (installing or unconfirmed) before the setup restart')
# the Wi-Fi channel table is its own: the Bluetooth sensors' table (also "seen") is never touched
ok('wifi_seen' in src and src.count('\nseen = {}') == 1, 'one "seen" (the sensors\'), the Wi-Fi channels kept apart in wifi_seen')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
