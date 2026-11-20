import os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware'))
from hawki_decode import decode, mfr_from_adv

KNOWN = [  # (payload, level, battery, fw, timestamp) - from the Magnus app's own log
    ('438FA4AFD62B00F00113', 701, 62, 19, 1794787572),
]

def test_known():
    for p, lvl, bat, fw, ts in KNOWN:
        d = decode(bytes.fromhex(p))
        assert (d['level'], d['battery'], d['firmwareVersion'], d['timestamp']) == (lvl, bat, fw, ts), d
        assert d['volts'] == round(3 + bat / 100, 2), d  # the battery field: hundredths of a volt over 3 (62 = 3.62 V)

def test_matches_reference():
    ref = sys.argv[1] if len(sys.argv) > 1 else None
    if not ref:
        return
    sys.path.insert(0, os.path.dirname(ref)); import ref_decode
    rnd = random.Random(1)
    for _ in range(20000):
        b = bytes(rnd.randrange(256) for _ in range(10))
        a, r = decode(b), ref_decode.decode(b)
        if 'floatSensorData' in r:
            r['floatSensorData'] = int(r['floatSensorData'], 2)
        assert a == r, (b.hex(), a, r)

def test_mfr():
    adv = bytes.fromhex('110733e1dcda6f883335ddff2213231900000bff438fa4afd62b00f00113')
    assert mfr_from_adv(adv).hex() == '438fa4afd62b00f00113'

if __name__ == '__main__':
    test_known(); test_matches_reference(); test_mfr(); print('all ok')
