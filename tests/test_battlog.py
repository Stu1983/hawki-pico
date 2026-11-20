"""python3 tests/test_battlog.py - each monitor's battery once a day (firmware/battlog.py), and where the app keeps it."""
import os, sys, tempfile
FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.append(FW)
import battlog

fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


os.chdir(tempfile.mkdtemp())
M = 'c0:04:56:c4:0c:71'
ok(battlog.name(M) == 'b_c40c71.bin' and battlog.read(M) == [], 'one file a monitor; nothing yet')
ok(battlog.add(M, 9820, 100, 6) and not battlog.add(M, 9820, 99, 7), 'the first reading of the day is kept; later ones that day are not')
ok(battlog.add(M, 9821, 98, -3) and battlog.read(M) == [(9820, 100, 6), (9821, 98, -3)], 'the next day: kept, with its temperature (frost too)')
ok(not battlog.add(M, 9822, None, 5) and not battlog.add(M, 9819, 90, 5) and len(battlog.read(M)) == 2,
   'nothing for a placeholder battery (None) or a day already past')
ok(os.path.getsize(battlog.name(M)) == 8, '4 bytes a day: about 1.5 KB a year')
with open(battlog.name(M), 'ab') as f:
    f.write(b'\x5d')  # the power went mid-write: one stray byte
ok(battlog.add(M, 9822, 97, 4) and battlog.read(M)[-1] == (9822, 97, 4) and os.path.getsize(battlog.name(M)) == 12 and battlog.add(M, 9823, 97, 4),
   'a record cut short is dropped before the next is added (never misaligned from then on)')
for d in range(9824, 11500):
    battlog.add(M, d, 90, 5)
r = battlog.read(M)
ok(len(r) == 1100 and r[-1][0] == 11499 and r[0][0] == 11499 - 1099, 'it serves the last 3 years at most (memory on the Pico)')
src = open(os.path.join(FW, 'app.py')).read()
ok("battlog.add(mac, weather.day_of(t), batt_of(d), d.get('temperature'))" in src and "path == '/api/battlog'" in src and "if bm in cfg['tanks'] else []" in src and "'%3a'" in src,
   'the app keeps it as each hourly reading is saved (placeholder batteries left out), and serves it at /api/battlog, for its own tanks only')
sys.exit(1 if fails else 0)
