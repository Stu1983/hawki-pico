"""python3 tests/test_front_door.py - app.py, the front door: an update asked for is installed before the app (core.py)
is loaded, while the heap is still in one piece; otherwise, and after a failed try, the app is loaded as always."""
import json, os, sys, tempfile, time, types
FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
SRC = open(os.path.join(FW, 'app.py')).read()
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


class Reset(Exception):
    pass


def run(note=None, cfg=None, manifest='1.3.47', install=None, joins_after=1, clock=1795800000):
    os.chdir(tempfile.mkdtemp())
    log = []
    if note is not None:
        json.dump(note, open('upd.want', 'w'))
    json.dump(cfg if cfg is not None else {'ssid': 'Home', 'pw': 'pw', 'ap_b': 'aabbccddeeff'}, open('config.json', 'w'))
    mem = {}
    ck = [clock]
    machine = types.SimpleNamespace(mem32=mem, reset=lambda: (_ for _ in ()).throw(Reset()))

    class WLAN:
        def __init__(self, *a):
            self.n = 0
            self.up = False

        def active(self, *a):
            log.append('active')

        def config(self, **k):
            pass

        def ifconfig(self, t=None):
            log.append(('ifconfig', t))

        def connect(self, ssid, pw, bssid=None):
            log.append(('connect', ssid, bssid))
            self.n += 1
            self.up = self.n >= joins_after

        def disconnect(self):
            log.append('disconnect')
            self.up = False

        def isconnected(self):
            return self.up
    net = types.SimpleNamespace(WLAN=WLAN, STA_IF=0, ipconfig=lambda **k: log.append(('dns', k)))
    upd = types.SimpleNamespace(check=lambda v: {'manifest': {'version': manifest}}, vtuple=lambda v: tuple(int(x) for x in v.split('.')),
                                tidy=lambda: log.append('tidy'), install=install or (lambda m, v: log.append(('install', m['version'], v))))
    core = types.ModuleType('core')
    fake = {'machine': machine, 'network': net, 'updater': upd, 'version': types.SimpleNamespace(VERSION='1.3.46'),
            'ntptime': types.SimpleNamespace(settime=lambda: (log.append('ntp'), ck.__setitem__(0, 1795800000)), host=None),
            'netcfg': types.SimpleNamespace(tup=lambda n: (n['ip'], n['mask'], n['gw'], n['dns']))}
    saved = {k: sys.modules.get(k) for k in list(fake) + ['core']}
    sys.modules.update(fake)
    sys.modules['core'] = core  # (importing it = the app starting)
    t = time.time
    time.time = lambda: ck[0]
    tk = [0]  # (a clock that moves only as it waits: the 90 s for a Wi-Fi that never comes pass at once)
    time.ticks_ms = lambda: tk[0]
    time.ticks_diff = lambda a, b: a - b
    time.sleep_ms = lambda ms: tk.__setitem__(0, tk[0] + ms)
    out = 'core'
    try:
        exec(compile(SRC, 'app.py', 'exec'), {'__name__': 'app'})
    except Reset:
        out = 'reset'
    finally:
        time.time = t
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    last = json.load(open('upd.last')) if os.path.exists('upd.last') else None
    return out, log, last, mem, os.path.exists('upd.want')


out, log, last, mem, want = run()
ok(out == 'core' and log == [] and last is None, 'no update asked for: straight to the app, nothing joined')
out, log, last, mem, want = run({'v': '1.3.47', 'id': 'x'})
ok(out == 'reset' and ('install', '1.3.47', '1.3.46') in log and 'tidy' in log and not want, 'asked for: installed before the app, then a restart (the note used up)')
ok(('connect', 'Home', b'\xaa\xbb\xcc\xdd\xee\xff') in log, 'joined on the access point it was on last')
ok(mem.get(0x400d800c if 'RP2350' in getattr(sys.implementation, '_machine', '') else 0x4005800c) == 0x4BFE0000, 'the restart marked planned (not a freeze)')
out, log, last, mem, want = run({'v': '1.3.47', 'id': 'x'}, joins_after=2)
ok(out == 'reset' and [x[2] for x in log if x[0] == 'connect'] == [b'\xaa\xbb\xcc\xdd\xee\xff', None], 'that access point not answering: any of them')
out, log, last, mem, want = run({'v': '1.3.47', 'id': 'x'}, clock=0)
ok(out == 'reset' and 'ntp' in log, 'the clock unset: set first (certificates are checked against the date)')


def oom(m, v):
    raise OSError(12)


out, log, last, mem, want = run({'v': '1.3.47', 'id': 'q'}, install=oom)
ok(out == 'core' and last == {'ok': False, 'from': '1.3.46', 'to': '1.3.47', 'id': 'q', 'reason': 'not enough memory even before the app started', 'stage': 'install'},
   'out of memory even here: said, and the app starts as always: %s' % last)
ok(log[-1] == 'disconnect', '... with the Wi-Fi left for the app to join its own way')
out, log, last, mem, want = run({'v': '1.3.47', 'id': 'q'}, manifest='1.3.48')
ok(out == 'core' and 'out now' in last['reason'] and not any(x[0] == 'install' for x in log if isinstance(x, tuple)), 'a newer release out meanwhile: never installed unseen')
out, log, last, mem, want = run({'v': '1.3.46', 'id': 'q'}, manifest='1.3.46')
ok(out == 'core' and last['reason'] == 'already up to date', 'already on it: nothing installed')
out, log, last, mem, want = run({'v': '1.3.47', 'id': 'q'}, cfg={})
ok(out == 'core' and last['reason'] == 'no Wi-Fi set up', 'no Wi-Fi set up: the app starts (its setup screen)')
out, log, last, mem, want = run({'v': '1.3.47', 'id': 'q'}, joins_after=99)
ok(out == 'core' and last['reason'] == 'could not join the Wi-Fi', 'the Wi-Fi not there: the app starts, and says why')
out, log, last, mem, want = run({'v': '1.3.47', 'id': 'x'}, cfg={'ssid': 'Home', 'pw': 'pw', 'net': {'ip': '192.168.1.9', 'mask': '255.255.255.0', 'gw': '192.168.1.1', 'dns': '192.168.1.1'}})
ok(out == 'reset' and ('ifconfig', ('192.168.1.9', '255.255.255.0', '192.168.1.1', '192.168.1.1')) in log and ('connect', 'Home', None) in log,
   'a fixed address: used; no access point remembered: any')
out, log, last, mem, want = run({'v': '1.3.47', 'id': 'x'}, cfg={'ssid': 'Home', 'pw': 'pw', 'ap_b': 'aa'})
ok(out == 'reset' and [x[2] for x in log if x[0] == 'connect'] == [None], 'a remembered access point that makes no sense: any of them')
c = open(os.path.join(FW, 'core.py')).read()
ok("sys.modules['app'] = sys.modules.get(__name__)" in c[:3000], "the app takes the name 'app' (maintenance scripts find it there)")
sys.exit(1 if fails else 0)
