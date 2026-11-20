"""Each monitor's battery, once a day, kept for the long run (runs on CPython and MicroPython).

Nothing uses it yet: kept so that, after a year or two, a battery's own fall in voltage can say how long it has
left (a new cell settles at about 3.0 V for most of its life, then sags, faster in the cold). One 4-byte record a
day per monitor, about 1.5 KB a year: <uint16 day since 2000-01-01, uint8 battery (the advert's %, of 2.00-3.20 V),
int8 the monitor's temperature in C> in b_<last 6 hex of its MAC>.bin, the first reading of each day.
"""
import os, struct

REC = '<HBb'
SIZE = 4
CAP = 20000  # records (55 years): only a guard


def name(mac):
    return 'b_' + mac.replace(':', '')[-6:] + '.bin'


def last_day(mac):
    try:
        with open(name(mac), 'rb') as f:
            f.seek(0, 2)
            n = f.tell()
            if n < SIZE:
                return None
            f.seek(n - n % SIZE - SIZE)
            return struct.unpack(REC, f.read(SIZE))[0]
    except OSError:
        return None


def _mend(mac):
    # a record cut short (the power went mid-write): drop the stray bytes, or every later record is misaligned
    try:
        n = os.stat(name(mac))[6]
    except OSError:
        return
    if n % SIZE:
        with open(name(mac), 'rb') as f:
            b = f.read(n - n % SIZE)
        with open(name(mac) + '.tmp', 'wb') as f:
            f.write(b)
        os.remove(name(mac))  # (then the rename never has a file in the way)
        os.rename(name(mac) + '.tmp', name(mac))


def add(mac, day, batt, temp):
    """Keep today's battery for this monitor (UTC days), if not kept already. False when there's nothing to keep."""
    if batt is None or not 0 <= batt <= 127 or day <= 0:
        return False
    _mend(mac)
    if (last_day(mac) or 0) >= day:
        return False
    try:
        if os.stat(name(mac))[6] >= CAP * SIZE:
            return False
    except OSError:
        pass
    t = 0 if temp is None else max(-128, min(127, int(temp)))
    with open(name(mac), 'ab') as f:
        f.write(struct.pack(REC, day, batt, t))
    return True


def read(mac, last=1100):
    """[(day, battery %, temperature C)] oldest first: the last `last` days (3 years; memory on the Pico)."""
    try:
        with open(name(mac), 'rb') as f:
            f.seek(0, 2)
            n = f.tell() // SIZE * SIZE
            f.seek(max(0, n - last * SIZE))
            b = f.read(min(n, last * SIZE))
    except OSError:
        return []
    return [struct.unpack_from(REC, b, i) for i in range(0, len(b) - SIZE + 1, SIZE)]
