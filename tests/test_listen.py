"""python3 tests/test_listen.py - the listening schedule (firmware/listen.py)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'firmware'))
from listen import Listener, BEFORE

fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


A = 'aa:bb:cc:00:00:01'
L = Listener()
T0 = 1_800_000_000 + 50 * 60   # sensor measures at :50
# boot at :20: the advert's reading is old, so nothing is saved, and we keep listening
ok(L.heard(A, 'r0', 700, T0 - 1800) is None, 'reading already there at boot is not saved (unknown age)')
ok(L.due([A], T0 - 1700), 'listens until the first new reading')
# new measurement at :50 (heard 4 s later)
ok(L.heard(A, 'r1', 705, T0 + 4) == (T0 + 4, 705), 'new payload -> saved with the time it appeared')
ok(L.heard(A, 'r1', 705, T0 + 8) is None, 'repeats of the same payload are not saved again')
ok(not L.due([A], T0 + 600), 'radio free in between readings')
ok(not L.due([A], T0 + 4 + 3600 - BEFORE - 5), 'still free just before the window')
ok(L.due([A], T0 + 4 + 3600 - BEFORE + 1), 'listening again shortly before the next reading')
# next reading arrives on time -> free again
ok(L.heard(A, 'r2', 705, T0 + 3604) == (T0 + 3604, 705), 'payload changes even when the level does not -> saved')
ok(not L.due([A], T0 + 3700), 'free again after the reading arrives')
# a missed reading (out of range): stays listening until it turns up, schedule re-learns
ok(L.due([A], T0 + 2 * 3600 + 300), 'overdue -> keeps listening')
ok(L.heard(A, 'r3', 700, T0 + 3 * 3600 + 5) is not None, 'late reading saved')
ok(abs(L.info(A)['period'] - 3600) < 5, 'period not disturbed by the missed hour: %s' % L.info(A)['period'])
ok(not L.due([A], T0 + 3 * 3600 + 100), 'back on schedule')
# two sensors: due while either is due
B = 'aa:bb:cc:00:00:02'
ok(L.due([A, B], T0 + 3 * 3600 + 100), 'an unlearned second sensor keeps the radio listening')
L.heard(B, 's0', 1200, T0 + 3 * 3600 + 110)
L.heard(B, 's1', 1205, T0 + 3 * 3600 + 160)
ok(not L.due([A, B], T0 + 3 * 3600 + 300), 'both learned -> free')
# a sensor whose payload never changes still gets saved hourly
C = 'aa:bb:cc:00:00:03'
M = Listener()
B0 = 1_800_000_000
M.heard(C, 'x', 900, B0)
saved = [t - B0 for t in range(B0 + 4, B0 + 6 * 3600, 4) if M.heard(C, 'x', 900, t)]
ok(len(saved) in (4, 5) and saved[0] >= 2 * 3600, 'unchanging payload: saved hourly after 2 h (%d saves)' % len(saved))
# drifting sensor clock: +20 s an hour is tracked
D = Listener()
D.heard(A, 'p', 1, 1_800_000_000)
t = 1_800_001_000
ok_window = False
for i in range(1, 30):
    t += 3620
    D.heard(A, 'p%d' % i, 1, t)
    ok_window = not D.due([A], t + 3620 - BEFORE - 30) and D.due([A], t + 3620 - 5)
    if not ok_window:
        break
ok(ok_window, 'clock drift of 20 s/h stays inside the window (period %s)' % D.info(A)['period'])
# the clock corrected backwards by a day after a reading: listening resumes instead of waiting a day
E = Listener()
E.heard(A, 'q0', 1, 1_800_100_000)
E.heard(A, 'q1', 1, 1_800_100_004)
ok(E.due([A], 1_800_100_004 - 86400), 'clock moved back a day -> listens again')
# adverts heard before the clock is set must not trigger the 'unchanging payload' save once it is
F = Listener()
F.heard(A, 'z', 700, 5)              # clock not set yet (1970)
F.heard(A, 'z', 700, 1_800_000_000)  # NTP has set it: same payload
ok(F.heard(A, 'z', 700, 1_800_000_060) is None, 'clock set after boot: no spurious save')
ok(F.due([A], 1_800_000_060), 'still listening for the first real reading')
sys.exit(1 if fails else 0)
