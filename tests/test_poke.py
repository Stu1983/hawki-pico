"""python3 tests/test_poke.py - when the Pico asks a monitor stuck starting up to measure now (firmware/poke.py)."""
import os, sys
FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.append(FW)
import poke

fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


START = {'timestamp': 0, 'isUnknownLevel': True, 'battery': 1}      # just after a battery change (seen 2026-11-20)
HALF = {'timestamp': 0, 'isUnknownLevel': False, 'battery': 1}      # measuring again, clock still 0, battery placeholder
FINE = {'timestamp': 3470333575, 'isUnknownLevel': False, 'battery': 82}
ok(poke.stuck(START) and not poke.stuck(HALF, 600) and poke.stuck(HALF, 4501) and not poke.stuck(FINE, 9000) and not poke.stuck(HALF),
   'stuck: clock 0 with no level, or no new measurement for over an hour; the 1% placeholder alone is not (measuring keeps it)')


def ask(d, st, t, age=None):
    if poke.due(d, st, t, age):
        st['last'] = t
        st['n'] = st.get('n', 0) + 1
        return True
    return False


st = {}
ok(not ask(START, st, 100) and not ask(START, st, 100 + 899), 'not straight away: it may be about to measure by itself')
ok(ask(START, st, 100 + 900), 'stuck 15 minutes: asked (even just after the Pico restarted, its clock near 0)')
ok(not ask(START, st, 100 + 900 + 1799) and ask(HALF, st, 100 + 900 + 1800, 5000), 'again 30 minutes later, while still stuck (measured once, then nothing for over an hour)')
for k in range(10):
    ask(HALF, st, 3000 + 1800 * (k + 1), 5000)
ok(st['n'] == 6, 'at most 6 times (a monitor that never answers is not kept awake): %d' % st['n'])
ok(not ask(HALF, st, 50000, 900) and st == {}, 'once it measures hourly again (clock still 0): forgotten')
ok(not ask(START, st, 60000) and ask(START, st, 60000 + 900), 'stuck again later (another battery change): the same again')
src = open(os.path.join(FW, 'app.py')).read()
ok("(poke_task, 'measure now')" in src and 'poke.measure(ble' in src and 'scan_on[0] = True' in src,
   'the app runs it for its tanks, pausing the scan while connected and always starting it again')
ok("li.get('changed_at') or li.get('heard_from')" in src and "'heard_from': e['first'], 'changed_at': e['chg']" in open(os.path.join(FW, 'listen.py')).read(),
   'no new measurement since the Pico started: timed from when it was first heard (a monitor already stuck at start is still helped)')
ok("radio_busy[0] = True" in src and "if radio_busy[0]:" in src and src.index("radio_busy[0] = True") < src.index("scan_on[0] = False\n                stop_scan()"),
   'a maintenance /run waits while a monitor is connected; the scan is stopped inside the protected part (always started again)')
ok("raise OSError('no answer to the measure command')" in open(os.path.join(FW, 'poke.py')).read(), 'no answer from the monitor at all: a failed try, so the next try follows')
sys.exit(1 if fails else 0)
