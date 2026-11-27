"""python3 tests/test_watchdog.py - the hardware watchdog and the record of what was under way when it fired
(firmware/app.py ph_*, wd_read, wd_feed, freeze_note), against a fake chip."""
import ast, json, os, sys, tempfile
FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


class Mem(dict):
    def __getitem__(self, k):
        return self.get(k, 0)


class Machine:
    WDT_RESET, PWRON_RESET = 3, 1

    def __init__(self, cause=1):
        self.mem32, self.cause = Mem(), cause

    def reset_cause(self):
        return self.cause


class WDT:
    def __init__(self):
        self.fed = 0

    def feed(self):
        self.fed += 1


src = open(os.path.join(FW, 'app.py')).read()
names = ('ph_write', 'ph_on', 'ph_off', 'ph_planned', 'wd_read', 'wd_feed', 'freezes', 'freeze_note')
consts = ('PH', 'WD_SCR', 'ph_n', 'ph_last', 'ph_armed', 'WD_HOLD_S', 'WD_MINUTES', 'wd_hw', 'wd_free', 'wh', 'FREEZE_FILE')
keep = [n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name in names
        or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in consts for t in n.targets)]
os.chdir(tempfile.mkdtemp())


def load(machine, impl='Raspberry Pi Pico 2 W with RP2350'):
    g = {'machine': machine, 'json': json, 'sys': type('s', (), {'implementation': type('i', (), {'_machine': impl})}),
         'beat': [0], 'wd_hold': [0]}
    exec(compile(ast.Module(keep, []), 'app.py', 'exec'), g)
    return g


m = Machine()
g = load(m)
g['ph_armed'][0] = 0x8000  # (as wd_start does)
S0 = g['WD_SCR']
ok(S0 == 0x400d800c and load(Machine(), 'Raspberry Pi Pico W with RP2040')['WD_SCR'] == 0x4005800c, 'scratch registers: RP2350 and RP2040')
ok(g['wd_read']() is None, 'a power-on start: no freeze')
g['ph_on'](10)
g['ph_on'](1)
g['ph_on'](10)
g['ph_off'](10)
ok(m.mem32[S0] == 0x4B000000 | 10 << 16 | 0x8000 | (1 << 1) | (1 << 10), 'steps under way kept as bits (two web pages, one done), the last one begun: %x' % m.mem32[S0])
m.mem32[S0 + 4] = 1795757000
m.cause = Machine.WDT_RESET
g2 = load(m)
f = g2['wd_read']()
ok(f == {'at': 1795757000, 'last': 'web page', 'busy': ['Bluetooth connection', 'web page'], 'soft': False},
   'after the watchdog fired: when, and what was under way: %s' % f)
g['ph_off'](1)
g['ph_off'](10)
g['ph_planned']()
ok(load(m)['wd_read']() is None, 'a planned restart (restart(), or the app stopped for the rescue server): no freeze')
g['ph_planned'](0xFD)
f = load(m)['wd_read']()
ok(f and f['soft'] and f['busy'] == [], "the main loop's own 10-minute check: a freeze too, said to be the software")
m.mem32[S0] = 0x12345678
ok(load(m)['wd_read']() is None, 'registers never written by the app (another firmware, the boot ROM): no freeze')
g0 = load(m)
g0['ph_on'](0)
ok(load(m)['wd_read']() is None, 'a restart before the watchdog was on (a crash while starting, then the rescue server): no freeze')
m.mem32[S0], m.mem32[S0 + 4] = 0x4B000000 | 0xFF << 16 | 0x8000, 0
f = load(m)['wd_read']()
ok(f == {'at': None, 'last': None, 'busy': [], 'soft': False}, 'a freeze before the clock was set: time unknown')

# the feeding: every second from a hard timer, while the main loop beats
g = load(Machine())
w = WDT()
g['wd_feed'](None)
ok(w.fed == 0, 'no watchdog started: nothing to feed')
g['wd_hw'][0] = w
for s in range(1200):
    if s % 30 == 0:
        g['beat'][0] += 1
    g['wd_feed'](None)
ok(w.fed == 1200, 'the main loop beating: fed every second (%d)' % w.fed)
for s in range(700):
    g['wd_feed'](None)
ok(w.fed == 1200 + 570, 'stuck (the last beat 29 s before): fed until 10 minutes after it, then not (the chip resets 8 s later): %d' % (w.fed - 1200))
g['beat'][0] += 1
g['wd_feed'](None)
ok(w.fed == 1200 + 571, 'beating again: fed again')
g['wd_hold'][0] = 1
n0 = w.fed
for s in range(2000):
    g['wd_feed'](None)
ok(w.fed - n0 == 2000, 'a long job on purpose: fed on (2000 s)')
for s in range(6000):
    g['wd_feed'](None)
ok(w.fed - n0 == 7199, 'but up to 2 hours, not for ever (a hold never let go): %d' % (w.fed - n0))
g['wd_free'][0] = True
n0 = w.fed
for s in range(100):
    g['wd_feed'](None)
ok(w.fed - n0 == 100, 'the app stopped (main.py runs the rescue server): fed for good')

# the record
g = load(Machine())
ok(g['freezes']() == [], 'nothing on record yet')
for i in range(12):
    g['freeze_note']({'at': i})
ok([x['at'] for x in g['freezes']()] == list(range(2, 12)), 'the last 10 kept')

# the wiring
i = src.index('wd_prev = wd_read()')
ok(i < src.index('def with_room') and src.index('ph_write()  # (from here on') > i, 'read before anything writes the registers')
ok("ph_planned()\n    machine.reset()" in src, 'restart() marks itself planned')
j = src.index('asyncio.run(main())')
ok('finally:' in src[j - 20:j + 200] and "wd_free[0] = True" in src[j:j + 200] and 'ph_planned()' in src[j:j + 300],
   'the app stopping frees the watchdog for the rescue server, and is no freeze')
ok('hard=True' in src and 'period=1000, callback=wd_feed' in src and 'WD_HW_MS = 8000' in src, 'a hard timer every second, 8 s watchdog')
for k, f in (('gap_scan(0', 0), ('updater.install(m, VERSION)', 12), ('notify.send(', 7)):
    a = src.index(f and k or k)
    ok('ph_on(%d)' % f in src[a - 200:a], 'step marked before %s' % k)
sys.exit(1 if fails else 0)
