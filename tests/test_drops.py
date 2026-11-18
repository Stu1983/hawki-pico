"""python3 tests/test_drops.py - the sudden-drop (leak/theft) check (firmware/drops.py)."""
import os, sys, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'firmware'))
from drops import check

fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


H = 3600
STEP = 5.1  # litres per 5 mm step


def series(uses, start=600.0, noise=0.0, seed=1):
    """hourly readings: litres used in each hour, quantised to 5 mm steps, +- temperature wobble."""
    r = random.Random(seed)
    L, out = start, []
    for i, u in enumerate(uses):
        L -= u
        wob = r.uniform(-noise, noise)
        out.append((i * H, round((L + wob) / STEP) * STEP))
    return out


def alerts(rec, cap=6.0):
    """run the check as readings arrive; hours at which it would alert"""
    return [i for i in range(len(rec)) if check(rec[max(0, i - 8):i + 1], cap)]


# a hard-working burner: 3 L/h for 12 h, with steps and +-3 L temperature wobble -> never alerts
ok(alerts(series([3.0] * 48, noise=3.0)) == [], 'busy burner, 5 L steps, temperature wobble: no alert')
# a burner at its full 6 L/h all day: no alert
ok(alerts(series([6.0] * 24, noise=3.0, seed=2)) == [], 'burner flat out at the 6 L/h limit: no alert')
# theft: 300 L gone in one hour at hour 10 -> alert at hour 11 (confirmed by the next reading)
rec = series([1.0] * 10 + [300.0] + [1.0] * 10)
al = alerts(rec)
ok(al[:1] == [11], 'theft of 300 L: alert on the next reading (hours %s)' % al[:3])
lost = check(rec[3:12], 6.0)
ok(lost and 290 < lost[0] < 320, 'message gives the size of the drop: %s L' % (lost and round(lost[0])))
# a leak of 12 L/h on top of normal use: caught within a few hours
al = alerts(series([1.0] * 10 + [13.0] * 8))
ok(al and al[0] <= 13, 'leak of 12 L/h: alert by hour %s' % (al and al[0]))
# one bad low reading, then back to normal: no alert
rec = series([1.0] * 20)
rec[10] = (rec[10][0], rec[10][1] - 200)
ok(alerts(rec) == [], 'one glitchy low reading: no alert')
# a delivery (level goes UP) then normal use: no alert
ok(alerts(series([1.0] * 5 + [-500.0] + [1.0] * 10)) == [], 'a delivery: no alert')
# a missing hour (gap) during normal use: no alert
rec = series([2.0] * 20)
del rec[8:11]
ok(alerts(rec) == [], 'missed readings during normal use: no alert')
# one bad HIGH reading, then normal: no alert (Codex: 600, 800, 598, 597 used to alert)
ok(check([(0, 600.0), (H, 800.0), (2 * H, 598.0), (3 * H, 597.0)], 6.0) is None, 'one glitchy HIGH reading: no alert')
rec = series([1.0] * 20)
rec[10] = (rec[10][0], rec[10][1] + 200)
ok(alerts(rec) == [], 'one glitchy high reading in a series: no alert')
# on a ~6000 L tank one 5 mm step is ~27 L: an ordinary step mustn't read as a leak (slack scaled to the step)
import drops as _d
t0 = 1795400000
flat = [(t0 + h * 3600, 1000.0) for h in range(4)] + [(t0 + 4 * 3600, 972.5), (t0 + 5 * 3600, 972.5)]
ok(check(flat, 6) is not None, 'one 27.5 L step with the fixed 15 L slack: an alert (as before)')
ok(check(flat, 6, slack=2.5 * 27.5) is None, 'with the slack scaled to the tank (27.5 L a step): no alert')
big = flat[:4] + [(t0 + 4 * 3600, 800.0), (t0 + 5 * 3600, 800.0)]
ok(check(big, 6, slack=2.5 * 27.5) is not None, 'a real 200 L drop on that tank still alerts')
ok(type(_d.WINDOW) is int, 'the window is an int (epoch arithmetic never through a float)')
sys.exit(1 if fails else 0)
