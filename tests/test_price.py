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
sys.exit(1 if fails else 0)
