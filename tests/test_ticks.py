"""python3 tests/test_ticks.py - long uptimes: no elapsed time in firmware/app.py may break when ticks_ms wraps.

MicroPython's ticks_ms wraps at 2**30 ms (12.4 days), and ticks_diff of two values more than 6.2 days apart
comes out negative. So the network watch (setup network after 15 quiet minutes on a fixed address, the 60 s
boot grace before the setup network opens) and "a page was loaded lately" must not keep a ticks value for days.
"""
import ast, os

src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
tree = ast.parse(src)
want = {'mono_s', 'net_proof', 'net_quiet_s', 'boot_grace_over'}
PERIOD = 1 << 30


class FakeTime:
    ms = 0

    @classmethod
    def ticks_ms(cls):
        return cls.ms % PERIOD

    @staticmethod
    def ticks_diff(a, b):
        d = (a - b) % PERIOD
        return d - PERIOD if d >= PERIOD // 2 else d


def load():
    FakeTime.ms = 0
    g = {'time': FakeTime}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in want or isinstance(n, ast.Assign) and any(
                getattr(t, 'id', '') in ('_mono', 'net_ok_s', 'net_asked', 'NET_QUIET_S') for t in n.targets):
            exec(compile(ast.Module([n], []), 'app.py', 'exec'), g)
    return g


fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


DAY = 86400


def run_to(g, s, step=10):  # the tasks call mono_s() every few seconds: keep it ticking like they do
    while FakeTime.ms < s * 1000:
        FakeTime.ms = min(s * 1000, FakeTime.ms + step * 1000 + 7)  # (+7 ms: leftovers must add up)
        g['mono_s']()


for days in (1, 7, 8, 13, 20):
    g = load()
    run_to(g, days * DAY)
    q = g['net_quiet_s']()
    ok(abs(q - days * DAY) <= 1, 'no proof since boot, %2d days up: quiet for %.2f days' % (days, q / DAY))
    g['net_proof']()
    run_to(g, days * DAY + 60)
    q = g['net_quiet_s']()
    ok(59 <= q <= 61, '%2d days up, proof a minute ago: quiet %d s' % (days, q))
    ok(g['boot_grace_over'](), '%2d days up: past the 60 s boot grace' % days)
    ok(g['mono_s']() < 1 << 29, '%2d days up: still a small int (no memory needed to count)' % days)

g = load()
run_to(g, 30)
ok(not g['boot_grace_over'](), '30 s after boot: still in the boot grace')

g = load()
run_to(g, 100)
FakeTime.ms += 7 * DAY * 1000  # the whole loop stalled for 7 days (more than half the tick period)
ok(g['mono_s']() >= 100, 'after a stall longer than half the tick period it never counts backwards')

print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
