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
# the day's mean wind, kept beside the temperatures (wxw.bin)
body = '{"daily":{"time":["2026-11-15","2026-11-16","2026-11-17"],"temperature_2m_min":[4.5,1,2],"temperature_2m_max":[8.5,5.3,9],"wind_speed_10m_mean":[23.4,null,-1]}}'
ok(w.parse_w(body) == {w._day('2026-11-15'): 23.4} and w.parse_w('{"daily":{"time":["2026-11-15"]}}') == {}, 'wind: missing and impossible figures left out, none asked for: none')
fw = os.path.join(tempfile.mkdtemp(), 'wxw.bin')
w.save_w({t: 23.44, t - 1: None, t - 2: 0.0}, fw)
ok(w.load_w(fw) == {t: 23.4, t - 1: None, t - 2: 0.0} and os.path.getsize(fw) == 12, 'wind save/load to 0.1 km/h, 4 bytes a day, missing kept')
ok(w.load_w(os.path.join(tempfile.mkdtemp(), 'none.bin')) == {}, 'no wind file yet: none')
full = {d: (1, 2) for d in range(t - 50, t + 1)}
ok(w.plan(full, t - 50, t, wind={d: 5 for d in range(t - 20, t + 1)}) == [(t - 10, t), (t - 50, t - 21)], 'days kept from before the wind was: fetched again for it')
ok(w.plan(full, t - 50, t, wind={d: (5 if d % 2 else None) for d in range(t - 50, t + 1)}) == [(t - 10, t)], 'a day with no wind figure is not asked for again')
ok('wind_speed_10m_mean' in w.url(55.13, -6.67, t - 5, t, True) and 'wind' not in w.url(55.13, -6.67, t - 5, t), 'wind asked for only when wanted (the normals need none)')
# the usual weather for each month (normals), one full year at a time
import os as _os, tempfile as _tf
weather = w
nm = weather.norm_load(55.1, -6.6, name=_os.path.join(_tf.mkdtemp(), 'none.json'))
ok(nm['y'] == {} and weather.norm_next(nm, 2026) == 2025, 'normals start with last year')
ok(weather.norm_view(nm, 2026) is None, 'no averages until 3 years are in')
def year(y, jan=(2.0, 8.0)):
    d0, d1 = weather._day('%d-01-01' % y), weather._day('%d-12-31' % y)
    return {d: jan if weather.ymd(d)[5:7] == '01' else (10.0, 20.0) for d in range(d0, d1 + 1)}
for y in (2025, 2024, 2023):
    weather.norm_add(nm, y, year(y), 2026)
v = weather.norm_view(nm, 2026)
ok(v and abs(v[0] - (weather.BASE - 5)) < 1e-9 and v[6] == 0, 'January %.1f degree days a day (base %.1f, mean 5 C), July 0' % (v[0], weather.BASE))
ok(weather.norm_next(nm, 2026) == 2022, 'then the year before')
for y in range(2016, 2023):
    weather.norm_add(nm, y, year(y), 2026)
ok(weather.norm_next(nm, 2026) is None and len(nm['y']) == 10, 'done after %d years' % weather.NYEARS)
# a new year: 2026 comes in, 2016 drops out, so it stays the last 10 years
ok(weather.norm_next(nm, 2027) == 2026, 'in 2027, 2026 is fetched')
weather.norm_add(nm, 2026, year(2026, jan=(12.0, 14.0)), 2027)
ok(len(nm['y']) == 10 and '2016' not in nm['y'], 'and 2016 dropped: still 10 years')
v = weather.norm_view(nm, 2027)
ok(abs(v[0] - ((weather.BASE - 5) * 9 + 0.5) / 10) < 1e-6, 'January averaged over the 10 years: %.2f' % v[0])
# the usual wind for each month, kept with the normals (years saved before it: fetched again)
nw = weather.norm_load(55.1, -6.6, name=_os.path.join(_tf.mkdtemp(), 'none.json'))
nw['y']['2025'] = [[0.0] * 12, [31] * 12]
ok(weather.norm_next(nw, 2026) == 2025, 'a year saved before the wind was kept: fetched again')
for y in (2025, 2024, 2023):
    yd = year(y)
    weather.norm_add(nw, y, yd, 2026, {d: (30.0 if weather.ymd(d)[5:7] == '01' else 10.0) for d in yd})
ok(weather.norm_wind(nw, 2026) == [30.0] + [10.0] * 11 and weather.norm_next(nw, 2026) == 2022, 'usual wind by month once 3 years have it: %s' % weather.norm_wind(nw, 2026))
nw2 = weather.norm_load(55.1, -6.6, name=_os.path.join(_tf.mkdtemp(), 'none.json'))
for y in (2025, 2024, 2023):
    weather.norm_add(nw2, y, year(y), 2026)
ok(weather.norm_wind(nw2, 2026) is None and weather.norm_view(nw2, 2026), 'no wind figures: no usual wind (temperatures as before)')
p2 = _os.path.join(_tf.mkdtemp(), 'n.json'); weather.norm_save(nm, p2)
ok(weather.norm_load(55.1, -6.6, p2)['y'] == nm['y'] and weather.norm_load(55.2, -6.6, p2)['y'] == {}, 'saved per place: another place starts again')
sys.exit(1 if fails else 0)
