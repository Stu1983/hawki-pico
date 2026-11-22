"""Each saved reading's two clocks, per monitor (runs on CPython and MicroPython).

The history (h_*.bin) keeps one time per reading, on the Pico's clock (NTP: the reference). This keeps, beside it,
what the monitor's own clock said, so the two can be compared later (drift, a clock that was reset or set):
<uint32 the reading's time in the history, uint32 when the Pico heard it, uint32 the advert's own time (0: none)>
in c_<last 6 hex of its MAC>.bin, 12 bytes a reading, about 105 KB a year; trimmed to the last CAP records.
After a restart, the last day's (heard - advert time) seeds listen.py's offset, so readings are placed at once.
"""
import os, struct

REC = '<III'
SIZE = 12
CAP = 9000   # records: just over a year of hourly readings
TRIM = 8000  # kept when it reaches CAP (one rewrite every ~6 weeks)


def name(mac):
    return 'c_' + mac.replace(':', '')[-6:] + '.bin'


def _size(mac):
    try:
        return os.stat(name(mac))[6]
    except OSError:
        return 0


def _keep_last(mac, n):
    # rewrite with only the last n whole records (also drops a record cut short by a power cut)
    whole = _size(mac) // SIZE
    left = min(n, whole) * SIZE
    tmp = name(mac) + '.tmp'
    try:
        with open(name(mac), 'rb') as f, open(tmp, 'wb') as o:
            f.seek(whole * SIZE - left)
            while left:  # (in small pieces: a 100 KB read may not fit in the Pico's memory)
                b = f.read(min(left, 64 * SIZE))
                if not b:
                    break
                o.write(b)
                left -= len(b)
    except BaseException:  # (flash full, say: no half-written copy left taking the space; the log as it was)
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    os.rename(tmp, name(mac))  # (over the old one in one step: a power cut leaves one or the other, whole)


def add(mac, at, heard, mts):
    size = _size(mac)
    if size % SIZE:
        _keep_last(mac, size // SIZE)
    elif size >= CAP * SIZE:
        _keep_last(mac, TRIM)
    with open(name(mac), 'ab') as f:
        f.write(struct.pack(REC, int(at) & 0xffffffff, int(heard) & 0xffffffff, int(mts or 0) & 0xffffffff))


def read(mac, last=CAP):
    """[(time in the history, heard, advert time)] oldest first, the last `last` records."""
    try:
        with open(name(mac), 'rb') as f:
            f.seek(0, 2)
            whole = f.tell() // SIZE
            k = min(last, whole)
            f.seek((whole - k) * SIZE)
            b = f.read(k * SIZE)
    except OSError:
        return []
    return [struct.unpack_from(REC, b, i) for i in range(0, len(b) - SIZE + 1, SIZE)]


def offsets(mac, now, n=24, max_off=86400):
    """The last day's (heard - advert time) for readings whose advert time was set, to seed listen.py's offset
    after a restart. Only readings from the last day (an older offset may no longer hold), only while the monitor's
    clock still steps evenly from one to the next (a reset or set clock starts afresh)."""
    out = []
    prev = None
    for at, heard, mts in read(mac, n):
        if not mts or abs(heard - mts) > max_off or now - heard > 86400 or heard > now + 60:
            out, prev = [], None
            continue
        if prev is not None:
            k = int((mts - prev) / 3600 + 0.5)
            if k < 1 or abs(mts - prev - k * 3600) > 360 * k:
                out = []  # (its clock was changed: what came before no longer applies)
        out.append(heard - mts)
        prev = mts
    return out
