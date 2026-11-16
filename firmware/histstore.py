"""History file housekeeping (runs on CPython and MicroPython).

A history file is a run of 6-byte records <uint32 epoch, uint16 mm>, sorted by time.
compact() keeps every record newer than `cutoff` and shrinks each older day (UTC) to ONE
record: the median of whatever readings that day has, stamped at midday. So a day with a
Wi-Fi drop or a power blip still gets a figure from the readings it did get; only a day with
no readings at all has no record. Already-compacted days are one record each, so running it
again changes nothing (and then nothing is rewritten, sparing the flash).
"""
import os
import struct

DAY = 86400


def _records(f):
    while True:
        buf = f.read(600)  # 100 records at a time
        if not buf:
            return
        for i in range(0, len(buf) - 5, 6):
            yield struct.unpack_from('<IH', buf, i)


def compact(name, cutoff):
    """Shrink records older than `cutoff` (epoch) to one per day. Returns (records in, out)."""
    try:
        f = open(name, 'rb')
    except OSError:
        return 0, 0
    n_in = n_out = 0
    changed = False
    day, vals = None, []

    def flush(o):
        vals.sort()
        o.write(struct.pack('<IH', day * DAY + DAY // 2, vals[len(vals) // 2]))

    with f, open(name + '.cmp', 'wb') as o:
        for t, mm in _records(f):
            n_in += 1
            if t < cutoff:
                d = t // DAY
                if d != day:
                    if vals:
                        flush(o)
                        n_out += 1
                    day, vals = d, []
                vals.append(mm)
                if len(vals) > 1 or t != d * DAY + DAY // 2:
                    changed = True
                continue
            if vals:
                flush(o)
                n_out += 1
                day, vals = None, []
            o.write(struct.pack('<IH', t, mm))
            n_out += 1
        if vals:
            flush(o)
            n_out += 1
    if changed:
        os.rename(name + '.cmp', name)
    else:
        os.remove(name + '.cmp')
    return n_in, n_out
