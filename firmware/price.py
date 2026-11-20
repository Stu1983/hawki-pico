"""Heating oil prices for Northern Ireland from cheapestoil.co.uk (free, no account).

They publish a small JSON reply for Home Assistant: the cheapest and average price for a 900 L order,
for a BT postcode district (or all of Northern Ireland when none is given). They ask for no more than
one request a day. Stored in price.bin with weather.py's 6-byte records: <uint16 day, int16 cheapest,
int16 average> in tenths of a penny per litre. Runs on CPython and MicroPython.
"""
import json
import weather

HOST = 'www.cheapestoil.co.uk'
FILE = 'price.bin'
HFILE = 'priceh.bin'  # older days, same format: Northern Ireland figures imported once from cheapestoil.co.uk's price chart
HPATH = '/Stu1983/hawki-pico/main/data/priceh.bin'  # ...kept in this repo (tools/pricehist.py), downloaded once by a Pico without it


def ok_pc(s):
    """'' (all of Northern Ireland) or a BT postcode district like BT51."""
    s = str(s or '').strip().upper().replace(' ', '')
    if s and not (s.startswith('BT') and 3 <= len(s) <= 4 and s[2:].isdigit() and 1 <= int(s[2:]) <= 99):
        raise ValueError('postcode district: BT and a number, like BT51 (Northern Ireland only)')
    return s


def path(pc):
    return '/homeassistant/oilprice' + ('?postcode=' + pc if pc else '')


def parse(body):
    """-> (cheapest, average) in pence a litre. The reply's *_ppl figures are in pounds."""
    j = json.loads(body)
    out = []
    for k in ('cheapest_ppl', 'average_ppl'):
        v = j.get(k)
        if not isinstance(v, (int, float)) or not 0.1 < v < 10:
            raise ValueError('no price in the reply')
        out.append(round(v * 100, 1))
    return tuple(out)


def fetch(pc, deadline=25):
    return parse(weather.get(HOST, path(ok_pc(pc)), deadline))


def load():
    return weather.load(FILE)


def add(day, prices):
    """Save today's prices (one record a day; a later fetch the same day replaces it)."""
    d = load()
    d[day] = prices
    weather.save(d, FILE)
    return d


def hist_ok(b):
    """A price history file: whole 6-byte records, days in order, prices 5p-500p a litre (or none)."""
    import struct
    if not b or len(b) % 6:
        return False
    last = -1
    for i in range(0, len(b), 6):
        d, c, a = struct.unpack_from('<Hhh', b, i)
        if d <= last or not all(v == weather.NONE or 50 <= v <= 5000 for v in (c, a)):
            return False
        last = d
    return True


def hist_fetch(get, today):
    """Download the older prices once (get = updater._get: HTTPS to GitHub, its certificate checked) into HFILE,
    kept only if the whole file arrives and looks right: ending within 90 days of today (a download cut short ends
    years back; the file in the repo is brought up to date every week)."""
    import os
    try:
        with open('priceh.tmp', 'wb') as f:
            get(HPATH, f.write, 40000)
        with open('priceh.tmp', 'rb') as f:
            good = hist_ok(f.read())
        if good:
            with open('priceh.tmp', 'rb') as f:
                f.seek(-6, 2)
                e = f.read(2)
            good = (e[0] | e[1] << 8) >= today - 90
        if not good:
            raise ValueError('price history: not a price file')
        os.rename('priceh.tmp', HFILE)
    finally:
        try:
            os.remove('priceh.tmp')
        except OSError:
            pass


def hist_have():
    import os
    try:
        return os.stat(HFILE)[6] > 0
    except OSError:
        return False


def hist_wanted():
    """True while the older prices are missing, or stop short of this Pico's own first day (a Pico set up after the
    file in the repo was last brought up to date): the file there is refreshed now and then, so a later copy fills
    the gap. Once the two meet, never again."""
    if not hist_have():
        return True
    with open(HFILE, 'rb') as f:
        f.seek(-6, 2)
        last = f.read(2)
    last = last[0] | last[1] << 8
    own = load()
    return bool(own) and min(own) > last + 1
