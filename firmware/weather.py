"""Daily min/max outside temperature from Open-Meteo (free, no account), for the tank's location.

Open-Meteo's archive API covers 1940 to today, so the history can be filled in back to the first
reading. Stored in wx.bin as 6-byte records <uint16 day (days since 2000-01-01), int16 min x10,
int16 max x10>, one per day (~2 KB a year). Days are the location's own calendar days
(timezone=auto), the same days the history page groups your use into. Runs on CPython and MicroPython.
"""
import json, socket, ssl, struct, time

HOST = 'archive-api.open-meteo.com'
FHOST = 'api.open-meteo.com'  # the forecast (next 16 days, plus the last week the archive hasn't caught up on)
FILE = 'wx.bin'
FFILE = 'wxf.bin'  # the forecast, same format as wx.bin
NFILE = 'wxn.json'  # the usual weather for each month: average degree days over the last NYEARS full years
NYEARS = 10
BASE = 13.5  # degree days below this daily mean (C): heating needed. 15.5 is the usual base, less the mild days
             # when heating stays off (the same as the built-in UK shape in common.js)
NONE = -32768  # stored for a day Open-Meteo had no figure for, so it isn't asked for again and again
D2000 = 946684800  # 2000-01-01 00:00 UTC


def day_of(t):
    return int((t - D2000) // 86400)


def ymd(day):
    y, m, d = time.gmtime(D2000 + day * 86400)[:3]
    return '%04d-%02d-%02d' % (y, m, d)


def _day(s):
    y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    # days since 2000-01-01 for a calendar date (civil-from-days inverse, no mktime needed)
    y2 = y - (m <= 2)
    era = y2 // 400
    yoe = y2 - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468 - 10957


def load(name=FILE):
    """{day: (min, max)} in degrees C."""
    out = {}
    try:
        with open(name, 'rb') as f:
            b = f.read()
    except OSError:
        return out
    for i in range(0, len(b) - 5, 6):
        d, lo, hi = struct.unpack_from('<Hhh', b, i)
        out[d] = None if lo == NONE else (lo / 10, hi / 10)  # None: asked, but Open-Meteo has no figure
    return out


def save(days, name=FILE):
    with open(name + '.tmp', 'wb') as f:
        for d in sorted(days):
            v = days[d]
            lo, hi = (NONE, NONE) if v is None else (int(round(v[0] * 10)), int(round(v[1] * 10)))
            f.write(struct.pack('<Hhh', d, lo, hi))
    import os
    os.rename(name + '.tmp', name)


def parse(body):
    """Open-Meteo JSON -> {day: (min, max)}; days with a missing figure are left out."""
    j = json.loads(body)['daily']
    out = {}
    for s, lo, hi in zip(j['time'], j['temperature_2m_min'], j['temperature_2m_max']):
        if lo is not None and hi is not None and -60 < lo < 60 and -60 < hi < 60:
            out[_day(s)] = (lo, hi)
    return out


def url(lat, lon, d0, d1):
    return ('/v1/archive?latitude=%.4f&longitude=%.4f&start_date=%s&end_date=%s'
            '&daily=temperature_2m_max,temperature_2m_min&timezone=auto' % (lat, lon, ymd(d0), ymd(d1)))


def fetch(lat, lon, d0, d1, deadline=25):
    """Recorded days d0..d1 (archive)."""
    return parse(get(HOST, url(lat, lon, d0, d1), deadline))


def forecast(lat, lon, deadline=25):
    """The next 16 days, and the last 7 (which the archive only has a few days later)."""
    return parse(get(FHOST, '/v1/forecast?latitude=%.4f&longitude=%.4f&daily=temperature_2m_max,temperature_2m_min'
                            '&timezone=auto&past_days=7&forecast_days=16' % (lat, lon), deadline))


def get(host, path, deadline=25):
    """HTTPS GET, checked against ca.pem (Open-Meteo is Let's Encrypt -> ISRG). Returns the body."""
    t0 = time.time()
    ai = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0]
    s = socket.socket(ai[0], socket.SOCK_STREAM, ai[2])
    s.settimeout(15)
    try:
        s.connect(ai[-1])
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.verify_mode = ssl.CERT_REQUIRED
        with open('ca.pem', 'rb') as f:
            ca = f.read()
        try:
            ctx.load_verify_locations(cadata=ca)
        except Exception:
            ctx.load_verify_locations(cadata=ca.decode())
        s = ctx.wrap_socket(s, server_hostname=host)
        req = 'GET %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: hawki-pico\r\nConnection: close\r\n\r\n' % (path, host)
        (s.write if hasattr(s, 'write') else s.sendall)(req.encode())
        rd = s.read if hasattr(s, 'read') else s.recv
        parts, n = [], 0
        while True:
            if time.time() - t0 > deadline:
                raise OSError('weather took too long')
            c = rd(1024)
            if not c:
                break
            n += len(c)
            if n > 60000:
                raise OSError('weather reply too big')
            parts.append(c)
    finally:
        s.close()
    raw = b''.join(parts)
    head, _, body = raw.partition(b'\r\n\r\n')
    try:
        status = int(head.split(b' ', 2)[1])
    except (IndexError, ValueError):
        raise OSError('no reply from ' + host)
    if status != 200:
        raise OSError('%s said %d' % (host, status))
    return body


def fill(have, got, d0, d1):
    """Merge a reply for days d0..d1; days it had no figure for are marked missing (None), except
    the last 10 days, which are asked for again (recent figures arrive late)."""
    for d in range(d0, d1 + 1):
        if d in got:
            have[d] = got[d]
        elif d not in have:
            have[d] = None
    return have


def plan(have, first_day, today, chunk=180):
    """Which (start, end) day ranges to fetch: everything from first_day missing, plus the last 10 days
    again (recent figures settle), at most `chunk` days per request, NEWEST first (so old gaps can
    never hold up recent days)."""
    want = []
    d = first_day
    while d <= today:
        if d not in have or d >= today - 10:
            e = d
            while e + 1 <= today and e + 1 - d < chunk and (e + 1 not in have or e + 1 >= today - 10):
                e += 1
            want.append((d, e))
            d = e + 1
        else:
            d += 1
    return want[::-1]


# ---------- the usual weather for each month (for forecasting beyond the 16-day forecast) ----------
def dd(v):
    """Degree days for one day's (min, max)."""
    return max(0.0, BASE - (v[0] + v[1]) / 2)


def norm_load(lat, lon, name=NFILE):
    """{'at': [lat, lon], 'y': {'2025': [[12 sums of daily degree days], [12 day counts]], ...}}"""
    try:
        with open(name) as f:
            n = json.load(f)
        if n.get('at') == [lat, lon] and isinstance(n.get('y'), dict):
            return n
    except (OSError, ValueError):
        pass
    return {'at': [lat, lon], 'y': {}}


def _window(this_year):
    return range(this_year - 1, this_year - 1 - NYEARS, -1)  # the last NYEARS full years, newest first


def norm_add(n, year, got, this_year):
    """Add one full year's recorded days; years that have dropped out of the window are let go."""
    s, c = [0.0] * 12, [0] * 12
    for d, v in got.items():
        m = time.gmtime(D2000 + d * 86400)[1] - 1
        s[m] += dd(v)
        c[m] += 1
    n['y'][str(year)] = [s, c]
    keep = set(str(y) for y in _window(this_year))
    for k in list(n['y']):
        if k not in keep:
            del n['y'][k]
    return n


def norm_save(n, name=NFILE):
    with open(name + '.tmp', 'w') as f:
        json.dump(n, f)
    import os
    os.rename(name + '.tmp', name)


def norm_next(n, this_year):
    """The next full year to fetch (newest first), or None when all NYEARS are in."""
    for y in _window(this_year):
        if str(y) not in n['y']:
            return y
    return None


def norm_view(n, this_year):
    """Average degree days a day for each month over the years in the window, once 3+ are in (else None)."""
    ys = [n['y'][str(y)] for y in _window(this_year) if str(y) in n['y']]
    if len(ys) < 3:
        return None
    out = []
    for m in range(12):
        c = sum(y[1][m] for y in ys)
        if c < 28 * 3:
            return None
        out.append(round(sum(y[0][m] for y in ys) / c, 2))
    return out
