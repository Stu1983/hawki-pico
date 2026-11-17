"""Readings heard while the clock isn't set yet (a power cut with the internet down), placed once it is.

Until the time comes from the internet the Pico can't say when a reading was taken, so each new hourly
measurement is kept aside in u_<mac>.bin with what IS known: seconds since this start (mono_s), the sensor's
own clock, the level, and which start it was (boot). When the clock is set:
  - this start's readings: time = now - (seconds since start now - seconds since start then), exactly;
  - an earlier start's (the power went again before the time came back): placed by the sensor's own clock,
    which is off from real time by minutes but steps exactly 3600 s between hourly measurements (seen on a
    HAWKi over 42 measurements). One reading after the clock was set gives the offset: time = its time -
    (its sensor time - this one's). Only if that step is a whole number of hours, give or take 10 s.
Every placed reading must fall in the gap: after the last reading saved before the clock was lost, and no
later than when it came back. Anything that can't be placed is dropped, never guessed.
Runs on CPython and MicroPython.
"""
import os, struct

REC = '<IIHH'  # mono_s, sensor time, mm, boot
SIZE = 12
CAP = 500      # per tank (about 3 weeks of hourly readings): a clock that never comes back can't fill the flash
STEP_TOL = 10  # s


def name(mac):
    return 'u_' + mac.replace(':', '')[-6:] + '.bin'


def add(mac, mono, sensor_ts, mm, boot):
    n = name(mac)
    try:
        if os.stat(n)[6] >= CAP * SIZE:
            return False
    except OSError:
        pass
    with open(n, 'ab') as f:
        f.write(struct.pack(REC, int(mono) & 0xffffffff, int(sensor_ts or 0) & 0xffffffff, int(mm), int(boot) & 0xffff))
    return True


def records(mac):
    try:
        with open(name(mac), 'rb') as f:
            b = f.read()
    except OSError:
        return []
    return [struct.unpack_from(REC, b, i) for i in range(0, len(b) - SIZE + 1, SIZE)]


def needs_anchor(recs, boot):
    # are there readings from an earlier start (placed by the sensor's clock)?
    return any(r[3] != boot for r in recs)


def place(recs, boot, now, mono_now, anchor, gap_from, gap_to):
    """[(epoch, mm)] for the readings that can be placed, sorted. anchor: (epoch, sensor time) of a reading
    taken after the clock was set, or None. The gap: gap_from < time <= gap_to."""
    out = []
    for mono, sts, mm, b in recs:
        if b == boot:
            t = now - (mono_now - mono)
        elif anchor and sts and anchor[1]:
            dt = anchor[1] - sts  # how long before the anchor, by the sensor's clock
            hours = (dt + 1800) // 3600
            if dt <= 0 or abs(dt - hours * 3600) > STEP_TOL:
                continue
            t = anchor[0] - dt
        else:
            continue
        t = int(t)
        if gap_from < t <= gap_to:
            out.append((t, mm))
    out.sort()
    keep, last = [], None
    for t, mm in out:  # one per time
        if t != last:
            keep.append((t, mm))
            last = t
    return keep


def clear(mac):
    try:
        os.remove(name(mac))
    except OSError:
        pass
