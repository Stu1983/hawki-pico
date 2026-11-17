"""python3 tests/test_unset.py - readings heard while the clock wasn't set are placed once it is (firmware/unset.py)."""
import os, sys, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware'))
import unset

fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


os.chdir(tempfile.mkdtemp())
M = 'c0:04:56:c4:0c:71'
H = 3600
SYNC = 1795400000           # when the clock came back
LAST = SYNC - 30 * H        # the last reading saved before it was lost
OFF = 1700                  # the sensor's clock runs this far ahead of real time

# this start: up 12 h before the clock came; readings every hour from mono 600
for i in range(10):
    unset.add(M, 600 + i * H, SYNC - (12 * H - 600 - i * H) + OFF, 700 + i, boot=7)
recs = unset.records(M)
ok(len(recs) == 10 and recs[0][3] == 7, 'kept aside with the time since start, the sensor time and the start number')
mono_now = 12 * H
got = unset.place(recs, 7, SYNC, mono_now, None, LAST, SYNC)
ok([t for t, _ in got] == [SYNC - (12 * H - 600 - i * H) for i in range(10)], 'this start: placed exactly (now - time since)')
ok([mm for _, mm in got] == list(range(700, 710)), '...with their levels')

# an earlier start that never got the time (power went again): placed by the sensor's clock
unset.clear(M)
for i in range(5):
    real = LAST + (i + 2) * H + 17       # hourly measurements in the gap
    unset.add(M, 300 + i * H, real + OFF, 650 + i, boot=6)
anchor = (SYNC + 2 * H + 17, SYNC + 2 * H + 17 + OFF)  # a reading heard after the clock came back
got = unset.place(unset.records(M), 7, SYNC + 3 * H, 5 * H, anchor, LAST, SYNC)
ok([t for t, _ in got] == [LAST + (i + 2) * H + 17 for i in range(5)], 'an earlier start: placed by the sensor\'s clock, exactly')
ok(unset.place(unset.records(M), 7, SYNC + 3 * H, 5 * H, None, LAST, SYNC) == [], '...and dropped while there is no reading after the clock came back')

# a sensor clock that isn't steady (Tank 2's sticks on two values): dropped, never guessed
unset.clear(M)
unset.add(M, 300, 661424963, 1228, boot=6)
unset.add(M, 3900, 3470333575, 1233, boot=6)
ok(unset.place(unset.records(M), 7, SYNC + 3 * H, 5 * H, (SYNC + 2 * H, 661424963), LAST, SYNC) == [],
   'a sensor clock that jumps about: nothing placed')
unset.clear(M)
unset.add(M, 300, anchor[1] - 2 * H - 1234, 680, boot=6)  # not a whole number of hours before the anchor
ok(unset.place(unset.records(M), 7, SYNC + 3 * H, 5 * H, anchor, LAST, SYNC) == [], 'not a whole number of hours apart: dropped')

# nothing outside the gap
unset.clear(M)
unset.add(M, 300, anchor[1] - 40 * H, 600, boot=6)   # would land before the last reading saved
unset.add(M, 100, 0, 610, boot=7)                     # this start, but before... (mono 100 at 12 h up: 11.97 h before sync)
got = unset.place(unset.records(M), 7, SYNC, 12 * H, anchor, LAST, SYNC)
ok(all(LAST < t <= SYNC for t, _ in got) and len(got) == 1, 'only readings that fall in the gap are placed (%d)' % len(got))

# bounded
unset.clear(M)
n = sum(unset.add(M, i, 0, 700, 7) for i in range(unset.CAP + 50))
ok(n == unset.CAP and len(unset.records(M)) == unset.CAP, 'at most %d kept per tank' % unset.CAP)
unset.clear(M)
ok(unset.records(M) == [], 'cleared once placed')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
