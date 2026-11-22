"""When to listen for the tanks' sensors (runs on CPython and MicroPython).

A HAWKi monitor measures once an hour at its own fixed minute, then repeats that reading in every
advert (~4 s apart) until the next one; the advert's bytes change with each new measurement. So:
  - each new measurement is noticed by its payload changing, and saved with the time it appeared;
  - once a sensor's next measurement time is known, the Pico only needs to listen from shortly
    before it until it arrives, leaving the shared Wi-Fi/Bluetooth radio to Wi-Fi the rest of the hour;
  - if a reading is late (clock drift, out of range), listening simply continues until it arrives
    and the schedule re-learns from there.
"""

BEFORE = 90          # start listening this long before a reading is due (s)
PERIOD = 3600        # measurement interval until learned
STUCK = 2 * 3600     # payload unchanged this long while heard: save the level anyway, hourly
GRACE = 300          # repeats=True: the same payload still heard this long after a reading was due is that reading


class Listener:
    def __init__(self):
        self.s = {}  # mac -> {'raw', 'chg' (time of last new measurement), 'period', 'next', 'saved'}

    def heard(self, mac, raw, level, t, repeats=False):
        """A tank sensor's advert. Returns a (time, level) to save, or None.
        repeats: its payload can repeat between measurements (a monitor whose clock is stuck at 0 after a battery
        change sends the same bytes when level and temperature come out the same). A good reading still heard
        unchanged after a measurement was due is then saved as that measurement, at the time it was due, and kept
        in 'rep' only: 'chg' (the last payload change: schedule, period learning, stuck/silent checks) stays put,
        so a monitor that really stopped measuring is still noticed."""
        if t < 1700000000:  # clock not set yet (just after boot): times would be meaningless
            return None
        e = self.s.get(mac)
        last = None if e is None else (e['chg'] if e['chg'] is not None else e['first'])
        if e is not None and (t < last or t - (e.get('rep') or last) > 7 * 86400):
            e = None  # the clock jumped: start this sensor afresh
        elif e is not None and e.get('rep') and t < e['rep']:
            e['rep'] = e['saved'] = None  # the clock was put back past a repeat: forget it (never a future reading)
        if e is None:  # first advert since boot: its reading is of unknown age; wait for the next one
            self.s[mac] = {'raw': raw, 'chg': None, 'period': PERIOD, 'next': None, 'first': t, 'saved': None}
            return None
        if raw == e['raw']:
            if repeats and level not in (None, 16383) and e['chg'] is not None:  # (this, not the fallback below)
                p = e['period']
                at = e['chg'] + (t - GRACE - e['chg']) // p * p  # (the latest one due)
                if at > max(e['chg'], e.get('rep') or 0):
                    e['rep'] = e['saved'] = at
                    return (at, level)
                return None
            last = e['chg'] if e['chg'] is not None else e['first']
            if t - last >= STUCK and (e['saved'] is None or e['saved'] <= last or t - e['saved'] >= e['period']):
                e['saved'] = t  # payload never changes (other firmware?): keep history going hourly
                return (t, level)
            return None
        e['raw'] = raw
        e['rep'] = None
        if e['chg'] is not None:
            gap = t - e['chg']
            p = e['period']
            if 0.75 * p <= gap <= 1.25 * p:  # a normal interval (not one after a missed reading): refine it
                e['period'] = round(0.7 * p + 0.3 * gap)
            elif 600 <= gap < 0.75 * p and e.get('short', 0) >= 2:
                e['period'] = gap  # it really does measure more often
            e['short'] = e.get('short', 0) + 1 if 600 <= gap < 0.75 * p else 0
        e['chg'] = t
        e['saved'] = t
        e['next'] = t + e['period']
        return (t, level)

    def due(self, macs, t):
        """True while any of these sensors' next reading is due or overdue (or not learned yet)."""
        for mac in macs:
            e = self.s.get(mac)
            # not learned, due/overdue, or a 'next' far off because the clock was corrected backwards
            if e is None or e['next'] is None or t >= e['next'] - BEFORE or e['next'] - t > 2 * e['period']:
                return True
        return False

    def info(self, mac):
        e = self.s.get(mac)
        if e is None:
            return None
        rep = e.get('rep')  # (a repeat taken as a measurement: shown as one, but changed_at is the last real change)
        return {'read_at': rep or e['chg'], 'next': rep + e['period'] if rep else e['next'], 'period': e['period'],
                'heard_from': e['first'], 'changed_at': e['chg']}
