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


def test_cutoff_mid_day():
    # the daily run's cutoff (now - 730 days) falls mid-day: that day must be left whole, never half merged into a
    # midday record written ahead of its own later readings (out of order, and a repeated time on a second run)
    d = tempfile.mkdtemp()
    p = os.path.join(d, 'h.bin')
    base = 1700000000 // DAY * DAY
    recs = [(base + h * H + 600, 700 + h) for h in range(48)]  # two days, hourly
    write(p, recs)
    cut = base + DAY + 3 * H + 30  # day 2, 03:00:30
    compact(p, cut)
    out = read(p)
    assert all(out[i][0] < out[i + 1][0] for i in range(len(out) - 1)), out[:6]
    assert out[0] == (base + DAY // 2, sorted(700 + h for h in range(24))[12]), out[0]  # day 1 compacted
    assert out[1:] == recs[24:], out[1:4]  # day 2 left whole
    compact(p, cut)  # run again the same day (a restart after 03:00)
    assert read(p) == out, 'second run changed it'


def test_nothing_to_do_writes_nothing():
    # every night (and after each restart past 03:00): no copy of the file written when nothing is old enough,
    # or when what is old is already one per day; and a failed write leaves no .cmp behind
    import builtins
    d = tempfile.mkdtemp()
    p = os.path.join(d, 'h.bin')
    base = 1700000000 // DAY * DAY
    recs = [(base + h * H, 700) for h in range(24 * 30)]
    write(p, recs)
    real_open, opened = builtins.open, []

    def spy(n, *a, **k):
        if str(n).endswith('.cmp'):
            opened.append(n)
        return real_open(n, *a, **k)
    builtins.open = spy
    try:
        assert compact(p, base - DAY) == (len(recs), len(recs))
        assert not opened, 'nothing old enough: no copy written'
        compact(p, base + 10 * DAY)  # 10 days compacted
        opened.clear()
        out = read(p)
        assert compact(p, base + 10 * DAY) == (len(out), len(out)) and not opened, 'already compacted: no copy written'
        assert read(p) == out
    finally:
        builtins.open = real_open

    class Full(Exception):
        pass

    def full(n, *a, **k):
        f = real_open(n, *a, **k)
        if str(n).endswith('.cmp'):
            w = f.write

            def wr(b):
                if f.tell() > 600:
                    raise Full()
                return w(b)
            f.write = wr
        return f
    builtins.open = full
    try:
        compact(p, base + 20 * DAY)
        raise AssertionError('no error')
    except Full:
        pass
    finally:
        builtins.open = real_open
    assert not os.path.exists(p + '.cmp') and read(p) == out, 'a failed write leaves no .cmp and the history as it was'


if __name__ == '__main__':
    test_nothing_to_do_writes_nothing()
    test_cutoff_mid_day()
    test_compact()
    print('all ok')
