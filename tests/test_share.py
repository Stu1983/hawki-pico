"""python3 tests/test_share.py - Online backup (firmware/share.py and app.py's share_* functions): what the upload
holds (and never holds), the ID, and when it uploads, retries, and deletes."""
import ast, asyncio, base64, json, os, struct, sys, tempfile
FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.insert(0, FW)
import share  # noqa: E402

os.chdir(tempfile.mkdtemp())
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


# ---- the ID
ids = {share.new_id() for _ in range(200)}
ok(len(ids) == 200 and all(len(i) == 12 and i[:3] == 'HK-' and i[7] == '-' and all(c in share.ALPH for c in i[3:7] + i[8:]) for i in ids),
   'IDs: HK-XXXX-XXXX from 32 unmistakable characters, all different: ' + sorted(ids)[0])
ok(share.ok_id(' hk 7qm2 xfd9 ') == 'HK-7QM2-XFD9' and share.ok_id('7QM2XFD9') == 'HK-7QM2-XFD9' and share.ok_id('HK-7QM2-XFDO') == 'HK-7QM2-XFD0'
   and share.ok_id('hk-iqm2-xfdl') == 'HK-1QM2-XFD1', 'an ID as typed: any case, spaces, no HK, O for 0, I and L for 1')
for bad in ('', 'HK-7QM2-XFD', 'HK-7QM2-XFD9X', 'HK-7QM2-XFDU', '../../etc'):
    try:
        share.ok_id(bad)
        ok(False, 'refused: %r' % bad)
    except ValueError:
        ok(True, 'refused: %r' % bad)
ok(len(share.new_key()) == 32, 'the key: 128 random bits, hex')

# ---- what's in the upload
cfg = {'ssid': 'MyHomeWiFi', 'pw': 'secret-wifi', 'pin': 'x', 'wx': {'lat': 55.04321, 'lon': -6.51234, 'name': '12 Main St, Coleraine BT51 3AB'},
       'price': {'pc': 'BT51'}, 'notify': {'po_user': 'uuuu', 'po_token': 'tttt'}, 'mqtt': {'pw': 'mq'}, 'token': 'maint-token',
       'tanks': {'aa:bb:cc:dd:ee:01': {}}}
st = {'tanks': [{'mac': 'aa:bb:cc:dd:ee:01', 'name': 'Back tank', 'level': 850, 'litres': 310.5, 'cfg': {'height_cm': 120, 'tank_l': 1100}}],
      'found': [{'mac': 'ff:ff:ff:ff:ff:ff'}], 'ssid': 'MyHomeWiFi', 'ip': '192.168.1.50', 'net': {'gw': '192.168.1.1'}, 'hostname': 'oil',
      'notify': {'po_user': True}, 'mqtt': {'host': '192.168.1.9', 'user': 'me'}, 'mac': '28:cd:c1:00:00:01', 'wifi_saved': 'MyHomeWiFi',
      'wx': {'lat': 55.04321, 'lon': -6.51234, 'name': '12 Main St, Coleraine BT51 3AB', 'norm': [1, 2], 'normw': [3, 4]}, 'price': {'on': True, 'pc': 'BT51'},
      'year_l': 2200, 'primary': 'aa:bb:cc:dd:ee:01', 'update': {'version': '1.3.30', 'last': {'x': 1}}, 'maint': True}
hist = b''.join(struct.pack('<IH', 1795000000 + i * 3600, 850 + i % 7) for i in range(5000))  # 30 KB
open('h.bin', 'wb').write(hist)
open('wx.bin', 'wb').write(bytes(range(256)) * 10)
open('deliv.json', 'w').write(json.dumps({'aa:bb:cc:dd:ee:01': [{'t': 1, 'litres': 500}], 'zz:old': [{'t': 2}]}))
n = share.build(cfg, st, {'deliv': 'deliv.json', 'hist': {'aa:bb:cc:dd:ee:01': 'h.bin'}, 'wx': 'wx.bin', 'wxf': 'none.bin', 'prices': 'none.bin'},
                {'aa:bb:cc:dd:ee:01': {'step': 10, 'h': 1200, 'l': [1, 0]}}, {'aa:bb:cc:dd:ee:01': [[9000, 2.9, 7]]}, '1.3.30', 1795000000)
raw = open(share.FILE).read()
u = json.loads(raw)
ok(n == len(raw.encode()) and u['format'] == 'hawki-backup' and u['version'] == 1 and u['share'] == 1 and u['fw'] == '1.3.30' and u['at'] == 1795000000,
   'valid JSON, the backup format (so it restores the way a backup does): %d bytes' % n)
ok(base64.b64decode(u['history']['aa:bb:cc:dd:ee:01']) == hist and base64.b64decode(u['files']['wx']) == bytes(range(256)) * 10 and 'wxf' not in u['files'],
   'readings and weather exactly as on the Pico (missing files left out)')
ok(u['tanks'] == {'aa:bb:cc:dd:ee:01': {'height_cm': 120, 'tank_l': 1100, 'name': 'Back tank'}} and u['deliveries'] == {'aa:bb:cc:dd:ee:01': [{'t': 1, 'litres': 500}]},
   'tank settings and deliveries, only for tanks it has')
ok(u['curves']['aa:bb:cc:dd:ee:01']['h'] == 1200 and u['battlog']['aa:bb:cc:dd:ee:01'] == [[9000, 2.9, 7]] and u['state']['tanks'][0]['litres'] == 310.5,
   'what the support view needs: curves, battery log, the dashboard\'s state')
for secret in ('MyHomeWiFi', 'secret-wifi', '192.168.', 'maint-token', 'uuuu', 'tttt', 'Main St', '3AB', '55.04', '-6.51', '28:cd:c1', 'oil"', 'ff:ff:ff'):
    ok(secret not in raw, 'never sent: ' + secret)
ok(u['state']['wx']['norm'] == [1, 2] and u['state']['wx']['normw'] == [3, 4], 'the usual temperatures and wind kept (the shared forecast counts the wind as at home)')
ok(u['area'] == {'pc': 'BT51', 'lat': 55.0, 'lon': -6.5} and u['state']['wx']['lat'] == 55.0 and u['state']['wx']['name'] == 'BT51',
   'where: the postcode district and the weather location to a quarter degree only: %r' % u['area'])
ok(sorted(u['state']) == ['found', 'pin_set', 'price', 'primary', 'tanks', 'update', 'wx', 'year_l'] and u['state']['found'] == [] and u['state']['update'] == {'version': '1.3.30'},
   'the state: only what the pages draw from')
cfg2 = dict(cfg, price=None)
ok(share.area(cfg2) == {'pc': None, 'lat': 55.0, 'lon': -6.5} and share.clean_state(st, cfg2)['wx']['name'] == 'about 55.00, -6.50' and share.area({}) == {'pc': None, 'lat': None, 'lon': None},
   'no postcode district: the rounded place only; no location at all: nothing')

# ---- app.py: switching on and off, when it uploads, retries, deletes
src = open(os.path.join(FW, 'app.py')).read()
names = ('SHARE_EVERY', 'share_host', 'ok_host', 'share_state', 'share_view', 'set_share', 'share_dels', 'share_due', 'share_files', 'share_size_guess', 'share_step')
keep = [x for x in ast.parse(src).body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name in names
        or isinstance(x, ast.Assign) and getattr(x.targets[0], 'id', None) in names]
T = [1795000000.0]
M = [1000]
calls = []
saved = []
sent = []


class W:
    up = True

    def isconnected(self):
        return self.up


class Sh:
    HOST = 'share.example'
    FILE = 'share.up'
    new_id, new_key = staticmethod(share.new_id), staticmethod(share.new_key)
    fail = None

    @staticmethod
    def upload(h, i, k, path=None, inv=None):
        calls.append(('PUT', i))
        sent.append((h, inv))
        if Sh.fail:
            raise OSError(Sh.fail)

    @staticmethod
    def delete(h, i, k):
        calls.append(('DELETE', i))
        sent.append((h, None))
        if Sh.fail:
            raise OSError(Sh.fail)


async def quiet():
    pass


g = {**__import__('_phstub').STUB, 'cfg': {'tanks': {'aa:bb:cc:dd:ee:01': {}}}, 'share': Sh, 'time': type('t', (), {'time': staticmethod(lambda: T[0])}), 'wlan': W(),
     'mono_s': lambda: M[0], 'web_quiet': quiet, 'wd_hold': [0], 'with_room': lambda f, *a: f(*a), 'save_cfg': lambda c: saved.append(1),
     'installing': [False], 'free_bytes': lambda: 10 ** 7, 'rm': lambda n: None, 'share_build': lambda now: 1234, 'os': os, 'hist_name': lambda m: 'h.bin',
     'weather': type('w', (), {'FILE': 'wx.bin', 'FFILE': 'wxf.bin', 'WFILE': 'wxw.bin', 'FWFILE': 'wxfw.bin'}), 'price': type('p', (), {'FILE': 'p.bin'})}
exec(compile(ast.Module(keep, []), 'app.py', 'exec'), g)
step = lambda: asyncio.run(g['share_step']())
step()
ok(calls == [], 'off: nothing sent')
v = g['set_share']({'on': True, 'invite': 'AB12-CD34"\r\nX: y'})
sid = g['cfg']['share']['id']
g['cfg']['share']['key'] = '%08x' % (int(T[0] + 7200) % (8 * 3600)) + g['cfg']['share']['key'][8:]  # (its time: 2 hours from now, so the steps below don't hang on chance)
ok(g['cfg']['share']['inv'] == 'AB12CD34Xy' and 'inv' not in v and 'invite' not in str(v), 'the invite code kept (letters and digits only, as the server compares them: nothing to break the request), never shown')
ok(v['on'] and v['id'] == sid and 'key' not in v and v['host'] == 'share.example', 'switched on: a new ID shown (the key never is)')
step()
ok(calls == [('PUT', sid)] and g['cfg']['share']['at'] == int(T[0]) and not g['share_state']['want'], 'uploads straight away')
ok(sent[-1] == ('share.example', 'AB12CD34Xy'), '...with the invite code')
T[0] += 3600
step()
ok(len(calls) == 1, 'an hour later: nothing')
P = 8 * 3600
slot = int(g['cfg']['share']['key'][:8], 16) % P
T[0] = ((T[0] - slot) // P + 1) * P + slot - 60
step()
ok(len(calls) == 1, 'a minute before its own time: nothing')
T[0] += 120
step()
ok(len(calls) == 2, '...at its own time: again')
T[0] += P - 180
step()
ok(len(calls) == 2, 'never twice in one 8 hours')
T[0] += 120
step()
ok(len(calls) == 3, '...then the next one: three a day')
n = len(calls)
for k in range(24 * 6):
    T[0] += 600
    step()
ok(len(calls) == n + 3, 'a whole day, checked every 10 minutes: three uploads (%d)' % (len(calls) - n))
del calls[n - 1:]  # (the counts below were written for two)
g['installing'][0] = True
g['set_share']({'now': 1})
step()
ok(len(calls) == 2, 'not while an update is installing')
g['installing'][0] = False
g['share_state']['want'] = False
g['set_share']({'now': 1})
step()
ok(len(calls) == 3, '"Upload now": again at once')
Sh.fail = 'the backup server said 500'
g['set_share']({'now': 1})
step()
ok(len(calls) == 4 and g['share_state']['err'] == 'the backup server said 500' and g['share_state']['want'], 'a failure: said, and still wanted')
step()
ok(len(calls) == 4, '...not tried again straight away')
M[0] += 1801
step()
ok(len(calls) == 5 and g['share_state']['gap'] == 7200, '...again after 30 minutes, then waits longer each time')
Sh.fail = None
M[0] += 3601
step()
ok(len(calls) == 6 and g['share_state']['err'] is None and not g['share_state']['want'], '...and once through, all clear')
g['set_share']({'on': False})
ok(g['cfg']['share'] == {'on': False} and g['cfg']['share_del'][0]['id'] == sid and g['share_view']()['id'] is None, 'switched off: the ID forgotten, its upload to delete')
ok(g['share_view']()['deleting'], 'switched off, not yet deleted: the card can say so')
step()
ok(calls[-1] == ('DELETE', sid) and 'share_del' not in g['cfg'], '...and deleted from the server')
step()
ok(len(calls) == 7, '...once')
g['set_share']({'on': True})
ok(g['cfg']['share']['id'] != sid, 'on again: a new ID (the old one is gone for good)')
# stop, start, stop before the first deletion went through: both deleted, in turn
Sh.fail = 'offline'
g['set_share']({'on': False})
sid2 = g['cfg']['share_del'][-1]['id']
g['set_share']({'on': True})
g['set_share']({'on': False})
ok([x['id'] for x in g['cfg']['share_del']][:1] == [sid2] and len(g['cfg']['share_del']) == 2, 'stopped twice before a deletion went through: both still to delete')
Sh.fail = None
M[0] += 10 ** 5
step()
step()
ok(calls[-2:] == [('DELETE', sid2), ('DELETE', calls[-1][1])] and calls[-1][1] != sid2 and 'share_del' not in g['cfg'], '...and both deleted, in turn')
g['cfg']['share_del'] = {'id': 'HK-OLD0-0000', 'key': 'k'}
step()
ok(calls[-1] == ('DELETE', 'HK-OLD0-0000') and 'share_del' not in g['cfg'], 'an older single pending deletion: still done')
g['set_share']({'on': True})
g['wlan'].up = False
n0 = len(calls)
step()
ok(len(calls) == n0, 'no Wi-Fi: waits')
g['wlan'].up = True
Sh.HOST = ''
step()
ok(len(calls) == n0 and g['share_view']()['host'] is None, 'no share server yet: nothing, and the card can say so')
Sh.HOST = 'share.example'
# another backup server (someone's own)
ok(not g['set_share']({'host': 'x.example'}).get('own_host'), 'the server can\'t be changed while backup is on (an ID belongs to its server)')
sid3 = g['cfg']['share']['id']
g['set_share']({'on': False})
v = g['set_share']({'host': ' https://My-Own.workers.dev/ '})
ok(v['host'] == 'my-own.workers.dev' and v['own_host'] and g['cfg']['share_del'][-1]['host'] == 'share.example', 'off: another server set (tidied); the old ID still to delete on the old one')
step()
ok(calls[-1] == ('DELETE', sid3) and sent[-1][0] == 'share.example', '...and deleted there, not on the new one')
try:
    g['set_share']({'host': 'evil/path?x'})
    ok(False, 'a bad server name: refused')
except ValueError:
    ok(g['share_host']() == 'my-own.workers.dev', 'a bad server name: refused, nothing changed')
ok(all(g['ok_host'](x) is None for x in ('https://.../', 'a..b', '-a.b', 'a.b-', 'a' * 64 + '.com', 'localhost', 'a b.c', '')) and g['ok_host']('A-1.b2.dev') == 'a-1.b2.dev', 'server names: only proper ones')
# the old server gone for good: its pending deletion never holds up backups to the new one
g['set_share']({'on': True, 'invite': 'Q'})
sid4 = g['cfg']['share']['id']
g['set_share']({'on': False})
real_del = Sh.delete
Sh.delete = staticmethod(lambda h, i, k: (calls.append(('DELETE', i)), sent.append((h, None)), (_ for _ in ()).throw(OSError('gone')) if h == 'my-own.workers.dev' else None))
g['set_share']({'host': ''})
g['set_share']({'on': True, 'invite': 'Q'})
for k in range(4):
    M[0] += 61
    step()
ok(g['share_view']()['derr'] == 'gone' and not g['share_view']()['err'], 'the old server\'s failure kept apart: the card never blames the backup for it')
ok(('PUT', g['cfg']['share']['id']) in calls[-4:] and g['cfg']['share_del'][0]['id'] == sid4, 'the old server down: the new backup still goes; the old deletion waits its turn: %r' % calls[-4:])
M[0] += 10 ** 5
Sh.delete = real_del
step()
ok(calls[-1] == ('DELETE', sid4) and 'share_del' not in g['cfg'], '...and is tried again later')
g['set_share']({'on': False})
step()
g['cfg']['share_del'] = [{'id': 'HK-OLD0-0001', 'key': 'k'}]
g['set_share']({'host': 'my-own.workers.dev'})
step()
ok(sent[-1] == ('share.example', None), 'an older pending deletion (no server noted): the usual server, where it was made')
v = g['set_share']({'host': ''})
ok(v['host'] == 'share.example' and not v['own_host'] and 'share_host' not in g['cfg'], 'cleared: back to the usual server')
g['set_share']({'host': 'share.example'})
ok('share_host' not in g['cfg'], 'the usual server typed in: nothing stored (it follows future updates)')
g['set_share']({'host': 'my-own.workers.dev'})
g['set_share']({'on': True, 'invite': 'Q'})
step()
ok(sent[-1] == ('my-own.workers.dev', 'Q'), 'on with another server: uploads go there')
g['set_share']({'on': False})
g['set_share']({'host': ''})
step()
g['set_share']({'on': True})
n0 = len(calls)
g['free_bytes'] = lambda: 1000
step()
ok(len(calls) == n0 and 'not enough room' in g['share_state']['err'], 'not enough room for the upload: says so, sends nothing')
sys.exit(1 if fails else 0)
