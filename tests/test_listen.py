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
# a monitor whose clock is stuck at 0: the same level and temperature give the same bytes (Tank 1, 2026-11-21)
from listen import GRACE
R = Listener(); T1 = 1_800_000_000 + 7 * 60
R.heard(A, 'p', 761, T1 - 1800, True); R.heard(A, 'q', 761, T1, True)          # learned: measures at :07
ok(R.heard(A, 'q', 761, T1 + 3600 + 30, True) is None, 'repeat payload just after the reading was due: wait a bit')
ok(R.heard(A, 'q', 761, T1 + 3600 + GRACE, True) == (T1 + 3600, 761), 'still the same after the grace: that is the reading, at :07')
i = R.info(A)
ok(i['read_at'] == T1 + 3600 and i['next'] == T1 + 7200, 'shown as read at :07, next due an hour on')
ok(i['changed_at'] == T1 and R.s[A]['chg'] == T1 and R.s[A]['next'] == T1 + 3600, 'the last real change and the schedule stay put')
ok(R.heard(A, 'q', 761, T1 + 3600 + GRACE + 4, True) is None, 'saved once')
ok(R.heard(A, 'q', 761, T1 + 4 * 3600 + 400, True) == (T1 + 4 * 3600, 761), 'heard again after a gap: the latest due one')
r = R.heard(A, 'q', 16383, T1 + 5 * 3600 + 400, True)
ok(r is None or r[1] == 16383, 'never a reading for a level it could not read (16383 is not saved)')
ok(R.info(A)['read_at'] == T1 + 4 * 3600, '... and read at stays put')
ok(R.heard(A, 'r', 766, T1 + 6 * 3600 + 30, True) == (T1 + 6 * 3600 + 30, 766), 'a changed payload still saves at once')
ok(R.info(A)['read_at'] == T1 + 6 * 3600 + 30 and R.s[A]['period'] == 3600, 'and is the reading again; period not disturbed')
# a late real reading (6 min): the repeat is saved at :07, the real one when it comes, and learning uses the real gap
Q = Listener(); Q.heard(A, 'p', 760, T1 - 1800, True); Q.heard(A, 'q', 761, T1, True)
ok(Q.heard(A, 'q', 761, T1 + 3600 + GRACE, True) == (T1 + 3600, 761), 'late: the repeat first')
ok(Q.heard(A, 'r', 766, T1 + 3960, True) == (T1 + 3960, 766), 'then the real one')
ok(Q.s[A]['period'] == round(0.7 * 3600 + 0.3 * 3960), 'period learned from the real changes, not the repeat')
# no double save with the 2-hour fallback; a clock put back past a repeat; a week of identical bytes
D = Listener(); D.heard(A, 'p', 760, T1 - 1800, True); D.heard(A, 'q', 761, T1, True)
got = [r for r in (D.heard(A, 'q', 761, T1 + s, True) for s in range(4, 4 * 3600, 4)) if r]
ok(got == [(T1 + h * 3600, 761) for h in (1, 2, 3)], 'unchanged for hours: exactly one save per hour, at :07 ' + str(len(got)))
D.heard(A, 'q', 761, T1 + 3 * 3600 + 400, True)
ok(D.heard(A, 'q', 761, T1 + 3600 + 100, True) is None and D.info(A)['read_at'] == T1, 'clock put back: the future repeat is forgotten')
W = Listener(); W.heard(A, 'p', 760, T1 - 1800, True); W.heard(A, 'q', 761, T1, True)
for h in range(1, 8 * 24 + 1):
    W.heard(A, 'q', 761, T1 + h * 3600 + GRACE, True)
ok(W.s[A]['chg'] == T1 and W.info(A)['read_at'] == T1 + 8 * 24 * 3600, 'a week of identical bytes is not a clock jump')
N = Listener(); N.heard(A, 'p', 761, T1 - 1800); N.heard(A, 'q', 761, T1)
ok(N.heard(A, 'q', 761, T1 + 3600 + GRACE) is None, 'a ticking-clock monitor: an unchanged payload is not a reading')
sys.exit(1 if fails else 0)
