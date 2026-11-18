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


def _needed(name, cutoff):
    # read-only, and only as far as the cutoff (the file is in time order): is anything older than it not yet one
    # record per day, at midday?
    last = None
    with open(name, 'rb') as f:
        for t, mm in _records(f):
            if t >= cutoff:
                return False
            d = t // DAY
            if d == last or t != d * DAY + DAY // 2:
                return True
            last = d
    return False


def compact(name, cutoff):
    """Shrink records older than `cutoff` (epoch) to one per day. Returns (records in, out)."""
    cutoff -= cutoff % DAY  # whole UTC days only: a day cut part-way would be merged ahead of its own later readings
    try:
        n = os.stat(name)[6] // 6
    except OSError:
        return 0, 0
    if not _needed(name, cutoff):  # (every night and after each restart: no copy of the file written for nothing)
        return n, n
    n_in = n_out = 0
    day, vals = None, []

    def flush(o):
        vals.sort()
        o.write(struct.pack('<IH', day * DAY + DAY // 2, vals[len(vals) // 2]))

    try:
        with open(name, 'rb') as f, open(name + '.cmp', 'wb') as o:
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
    except BaseException:  # (flash full, say: no half-written .cmp left taking the space; the history as it was)
        try:
            os.remove(name + '.cmp')
        except OSError:
            pass
        raise
    os.rename(name + '.cmp', name)
    return n_in, n_out
