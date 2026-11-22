"""python3 tests/test_clocklog.py - each reading's two clocks (firmware/clocklog.py) and setting a monitor's clock
(poke.clock_due, poke.set_clock)."""
import asyncio, os, sys, tempfile
FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.insert(0, FW)
import clocklog, poke

fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


os.chdir(tempfile.mkdtemp())
M = 'c0:04:56:c4:0c:71'
S = 1_795_314_295
for k in range(5):
    clocklog.add(M, S + k * 3600 + 9, S + k * 3600 + 30, S + k * 3600)
ok(clocklog.read(M)[0] == (S + 9, S + 30, S) and len(clocklog.read(M)) == 5, 'three times kept per reading')
ok(clocklog.offsets(M, S + 5 * 3600) == [30] * 5, 'offsets: heard - its own time, the last day')
ok(clocklog.offsets(M, S + 30 * 3600) == [], '...none once they are over a day old')
clocklog.add(M, S + 5 * 3600 + 9, S + 5 * 3600 + 20, S + 5 * 3600 - 1500)  # its clock set 25 min back
ok(clocklog.offsets(M, S + 6 * 3600) == [1520], 'a clock that was changed: only what came after it')
clocklog.add(M, S + 6 * 3600 + 9, S + 6 * 3600 + 20, 0)
ok(clocklog.offsets(M, S + 7 * 3600) == [], 'an advert without a time (unset clock): nothing to seed')
with open(clocklog.name(M), 'ab') as f:
    f.write(b'\x01\x02\x03')  # power cut mid-write
clocklog.add(M, S + 7 * 3600, S + 7 * 3600 + 5, S + 7 * 3600)
ok(len(clocklog.read(M)) == 8 and clocklog.read(M)[-1][2] == S + 7 * 3600, 'a record cut short is dropped, the rest stay aligned')
N = 'c6:76:1b:dc:39:1c'
clocklog.CAP, clocklog.TRIM = 10, 6
for k in range(12):
    clocklog.add(N, k, k, k)
ok([r[0] for r in clocklog.read(N)] == list(range(4, 12)), 'full at 10: the newest 6 kept, then 2 more: %r' % [r[0] for r in clocklog.read(N)])

# when to set a monitor's clock
NOW = 1_795_310_473
ok(not poke.clock_bad({'timestamp': NOW - 1500}, NOW) and not poke.clock_bad({}, NOW), 'minutes out (app-installed): left alone')
ok(poke.clock_bad({'timestamp': 0}, NOW) and poke.clock_bad({'timestamp': 3925600108}, NOW) and poke.clock_bad({'timestamp': 661424963}, NOW),
   'unset: 0 after a battery change, or junk (2094, 1990: seen on both of Stu\'s)')
st = {}
ok(not poke.clock_due({'timestamp': 0}, st, 5, 100), 'never before the Pico has the time (NTP)')
ok(not poke.clock_due({'timestamp': 0}, st, NOW, 100) and not poke.clock_due({'timestamp': 0}, st, NOW, 699), 'not on one advert: after 10 min')
ok(poke.clock_due({'timestamp': 0}, st, NOW, 700), 'unset for 10 min: set it')
st['last'], st['n'] = 700, 1
ok(not poke.clock_due({'timestamp': 0}, st, NOW, 700 + 6 * 3600 - 1) and poke.clock_due({'timestamp': 0}, st, NOW, 700 + 6 * 3600), 'again after 6 h')
st['n'] = 4
ok(not poke.clock_due({'timestamp': 0}, st, NOW, 10 ** 6), 'at most 4 times')
ok(not poke.clock_due({'timestamp': NOW}, st, NOW, 10 ** 6) and st == {}, 'right again: forgotten')
ok(poke.clock_text(1795310473) == '22.11.2026 01:21:13', 'the monitor\'s format, UTC: ' + poke.clock_text(1795310473))


# the write: a fake monitor that keeps what it is sent
class Mon:
    def __init__(self, take=True):
        self.v, self.take, self.writes = b'07.01.1970 05:08:23', take, []

    def gattc_read(self, c, h):
        st['rd'][h] = self.v
        st['done'] = 0

    def gattc_write(self, c, h, v, mode):
        self.writes.append(v)
        if self.take:
            self.v = bytes(v)
        st['done'] = 14


async def wait(key, t=8):
    return st.pop(key) if key == 'done' else st[key]


AS = type('A', (), {'sleep_ms': staticmethod(lambda ms: asyncio.sleep(0))})


def write(m, now):
    global st
    st = {'rd': {}}
    try:
        return asyncio.run(poke._write_clock(m, 1, {'1993': 40}, st, wait, AS, now=now))
    except OSError as ex:
        return ex


m = Mon()
r = write(m, lambda: NOW)
ok(r == ('07.01.1970 05:08:23', '22.11.2026 01:21:14') and m.writes == [b'22.11.2026 01:21:14'], 'set_clock writes UTC text and reads it back: %r' % (r,))
r = write(Mon(False), lambda: NOW)
ok(isinstance(r, OSError) and 'not taken' in str(r), 'a monitor that ignores it: an error (tried again later), not "set"')
m = Mon(False); m.v = b'22.11.2026 06:00:00'
r = write(m, lambda: NOW + 3 * 86400)
ok(isinstance(r, OSError), 'the right date but the wrong time read back: not "set" either')
m = Mon(); m.v = b'22.11.2026 01:20:00'
r = write(m, lambda: NOW)
ok(r == ('22.11.2026 01:20:00', '22.11.2026 01:20:00') and m.writes == [], 'already set (the Magnus app, meanwhile): not written again')
# a write read back wrong, then the retry: it must write again, not take the wrong time as "already set"
m = Mon(False); m.v = b'01.01.1970 00:00:00'
wrote = []
st = {'rd': {}}
def wrong_back(c, h, v, mode):
    m.writes.append(v); m.v = b'22.11.2026 06:00:00'; st['done'] = 14
m.gattc_write = wrong_back
try:
    asyncio.run(poke._write_clock(m, 1, {'1993': 40}, st, wait, AS, now=lambda: 1795348800, wrote=wrote))
except OSError:
    pass
st = {'rd': {}}
try:
    r = asyncio.run(poke._write_clock(m, 1, {'1993': 40}, st, wait, AS, now=lambda: 1795348803, wrote=wrote))
except OSError as ex:
    r = ex
ok(len(m.writes) == 2 and isinstance(r, OSError), 'retry after a wrong read-back: written again, still not "set" (%r)' % (r,))
ok(poke.clock_parse('22.11.2026 11:60:00') is None and poke.clock_parse('22.11.2026 24:00:00') is None, 'impossible times rejected')
ok(poke.clock_parse('22.11.2026 01:21:13') == 1795310473 and poke.clock_parse('07.01.1970 05:08:23') == 6 * 86400 + 5 * 3600 + 503
   and poke.clock_parse('29.02.2028 00:00:00') == 1835395200 and poke.clock_parse('junk') is None, 'clock_parse (UTC, leap years)')
sys.exit(1 if fails else 0)
