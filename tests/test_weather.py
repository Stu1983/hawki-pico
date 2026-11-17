"""python3 tests/test_weather.py - outside temperatures (firmware/weather.py)."""
import os, sys, calendar, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'firmware'))
import weather as w
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


ok(all(w.ymd(w._day(s)) == s for s in ('2000-01-01', '2024-02-29', '2026-03-01', '2026-11-17', '2099-12-31')), 'calendar dates round-trip')
ok(w.day_of(calendar.timegm((2026, 11, 17, 23, 59, 0))) == w._day('2026-11-17'), 'a timestamp maps to its UTC day')
body = '{"daily":{"time":["2026-11-15","2026-11-16","2026-11-17"],"temperature_2m_min":[4.5,null,-3.25],"temperature_2m_max":[8.5,5.3,99]}}'
got = w.parse(body)
ok(got == {w._day('2026-11-15'): (4.5, 8.5)}, 'missing and impossible figures are left out')
t = 9800
have = {d: (1, 2) for d in range(t - 100, t - 20)}
p = w.plan(have, t - 120, t)
ok(p == [(t - 20, t), (t - 120, t - 101)], 'fetches only the gaps, plus the last 10 days again, newest first: %s' % p)
ok(all(e - s < 180 for s, e in w.plan({}, t - 1000, t)), 'at most 180 days a request')
ok(w.plan({d: (1, 2) for d in range(t - 50, t + 1)}, t - 50, t) == [(t - 10, t)], 'up to date: just the last 10 days')
f = os.path.join(tempfile.mkdtemp(), 'wx.bin')
w.save({t: (-3.25, 12.04), t - 1: (0.0, 0.1)}, f)
ok(w.load(f) == {t: (-3.2, 12.0), t - 1: (0.0, 0.1)} or w.load(f) == {t: (-3.3, 12.0), t - 1: (0.0, 0.1)}, 'save/load to 0.1 degree: %s' % w.load(f))
ok(os.path.getsize(f) == 12, '6 bytes a day')
ok('start_date=2026-11-10&end_date=2026-11-17' in w.url(55.13, -6.67, w._day('2026-11-10'), w._day('2026-11-17')), 'request dates')
# a day Open-Meteo has no figure for: remembered as missing, not asked for again (unless recent)
h = w.fill({}, {t - 30: (1, 2)}, t - 31, t - 29)
ok(h == {t - 31: None, t - 30: (1, 2), t - 29: None}, 'days with no figure are marked missing')
ok(w.plan({**h, **{d: (1, 2) for d in range(t - 28, t + 1)}}, t - 31, t) == [(t - 10, t)], 'missing old days are not asked for again')
w.save(h, f)
ok(w.load(f) == {t - 31: None, t - 30: (1.0, 2.0), t - 29: None}, 'missing days survive a save')
sys.exit(1 if fails else 0)
