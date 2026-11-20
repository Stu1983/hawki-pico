"""python3 tests/test_price.py - oil prices from cheapestoil.co.uk (firmware/price.py)."""
import os, sys, tempfile
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'firmware'))
import price

fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


def err(f, *a):
    try:
        f(*a)
    except ValueError:
        return True
    return False


ok(price.ok_pc(' bt51 ') == 'BT51' and price.ok_pc('BT 5') == 'BT5' and price.ok_pc('') == '', 'postcode districts tidied: BT51, BT5, blank = all NI')
ok(err(price.ok_pc, 'SW1') and err(price.ok_pc, 'BT0') and err(price.ok_pc, 'BT51 2AB') and err(price.ok_pc, 'BT100'), 'not a BT district: refused')
ok(price.path('BT51') == '/homeassistant/oilprice?postcode=BT51' and price.path('') == '/homeassistant/oilprice', 'request path')
r = b'{"cheapest_ppl":0.99,"average_ppl":1.01,"postcode":"BT51","for_litres":900,"last_updated":"2026-11-17T07:31:25Z"}'
ok(price.parse(r) == (99.0, 101.0), 'reply in pounds -> pence a litre: %s' % (price.parse(r),))
ok(err(price.parse, b'{"cheapest_ppl":null,"average_ppl":1.01}') and err(price.parse, b'{"cheapest_ppl":99,"average_ppl":101}'), 'missing or nonsense prices refused')
os.chdir(tempfile.mkdtemp())
price.add(9817, (99.0, 101.0))
price.add(9818, (97.5, 100.2))
d = price.add(9818, (98.1, 100.4))
ok(price.load() == {9817: (99.0, 101.0), 9818: (98.1, 100.4)} and len(open(price.FILE, 'rb').read()) == 12, 'one record a day, 6 bytes each; a second fetch replaces')

# the older prices, downloaded once (into a fresh folder: nothing kept from a failed try)
import struct
good = b''.join(struct.pack('<Hhh', 7671 + i, 600 + i, 620 + i) for i in range(400))
def getter(body, fail=False):
    def g(path, sink, limit):
        assert path == price.HPATH and limit >= len(good)
        sink(body[:len(body) // 2])
        if fail:
            raise OSError('no reply')
        sink(body[len(body) // 2:])
        return len(body)
    return g
os.remove(price.FILE)  # (a Pico with no prices of its own yet)
ok(not price.hist_have(), 'no older prices yet')
try:
    price.hist_fetch(getter(good, fail=True), 7671 + 400)
except OSError:
    pass
ok(not price.hist_have() and not os.path.exists('priceh.tmp'), 'cut off half way: nothing kept, no part file left')
for bad, why in ((good[:-3], 'a part record'), (good[6:12] + good[:6], 'days out of order'), (struct.pack('<Hhh', 9000, 9999, 600), 'a price of 999.9p'), (good[:600], 'cut short on a whole record: ends 300 days back')):
    try:
        price.hist_fetch(getter(bad), 7671 + 400)
        r = False
    except ValueError:
        r = True
    ok(r and not price.hist_have(), 'refused: %s' % why)
price.hist_fetch(getter(good), 7671 + 400)
ok(price.hist_have() and open(price.HFILE, 'rb').read() == good and not os.path.exists('priceh.tmp'), 'a whole, sensible file: kept as priceh.bin')
ok(not price.hist_wanted(), '...no own prices yet to leave a gap before: not wanted again')
price.add(7671 + 400, (60.0, 62.0))
ok(not price.hist_wanted(), 'own prices start the day after it ends: no gap, never fetched again')
os.remove(price.FILE)
price.add(7671 + 405, (60.0, 62.0))
ok(price.hist_wanted(), 'own prices start 5 days after it ends: wanted again (the repo copy may be newer by then)')
os.remove(price.HFILE)
ok(price.hist_wanted(), 'no copy at all: wanted')
repo = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'priceh.bin'), 'rb').read()
ok(price.hist_ok(repo) and len(repo) < 40000, 'the file in the repo (data/priceh.bin) passes the same check (%d days)' % (len(repo) // 6))
sys.exit(1 if fails else 0)
