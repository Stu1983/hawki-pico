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
