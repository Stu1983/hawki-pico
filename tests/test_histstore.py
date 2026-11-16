import os, struct, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware'))
from histstore import compact, DAY

H = 3600


def write(p, recs):
    with open(p, 'wb') as f:
        for t, mm in recs:
            f.write(struct.pack('<IH', t, mm))


def read(p):
    b = open(p, 'rb').read()
    return [struct.unpack_from('<IH', b, i) for i in range(0, len(b), 6)]


def test_compact():
    d = tempfile.mkdtemp()
    p = os.path.join(d, 'h.bin')
    base = 1700000000 // DAY * DAY  # a UTC midnight
    recs = []
    # day 0: full day, a warm afternoon bump (median ignores it)
    recs += [(base + h * H + 1800, 700 - (5 if 12 <= h <= 16 else 0)) for h in range(24)]
    # day 1: Wi-Fi drop, only 5 readings
    recs += [(base + DAY + h * H + 1800, 710) for h in (0, 1, 2, 22, 23)]
    # day 2: a single reading
    recs += [(base + 2 * DAY + 7 * H, 720)]
    # day 3: nothing at all (Pico off)
    # day 4..: recent, must stay hourly
    recent = [(base + 4 * DAY + h * H, 730) for h in range(30)]
    write(p, recs + recent)
    cutoff = base + 4 * DAY
    n_in, n_out = compact(p, cutoff)
    out = read(p)
    assert n_in == len(recs) + len(recent) and n_out == len(out)
    old = [r for r in out if r[0] < cutoff]
    assert old == [(base + DAY // 2, 700), (base + DAY + DAY // 2, 710), (base + 2 * DAY + DAY // 2, 720)], old
    assert [r for r in out if r[0] >= cutoff] == recent
    # idempotent: nothing to do -> file untouched
    m = os.path.getmtime(p)
    assert compact(p, cutoff) == (len(out), len(out)) and read(p) == out and os.path.getmtime(p) == m
    assert not os.path.exists(p + '.cmp')
    # cutoff moves on: the old recent days compact too
    compact(p, cutoff + 2 * DAY)
    assert read(p)[-2:] == [(base + 4 * DAY + DAY // 2, 730), (base + 5 * DAY + DAY // 2, 730)]
    # missing file is fine
    assert compact(os.path.join(d, 'none.bin'), cutoff) == (0, 0)


if __name__ == '__main__':
    test_compact()
    print('all ok')
