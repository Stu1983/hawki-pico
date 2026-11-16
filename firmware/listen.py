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


class Listener:
    def __init__(self):
        self.s = {}  # mac -> {'raw', 'chg' (time of last new measurement), 'period', 'next', 'saved'}

    def heard(self, mac, raw, level, t):
        """A tank sensor's advert. Returns a (time, level) to save, or None."""
        if t < 1700000000:  # clock not set yet (just after boot): times would be meaningless
            return None
        e = self.s.get(mac)
        last = None if e is None else (e['chg'] if e['chg'] is not None else e['first'])
        if e is not None and (t < last or t - last > 7 * 86400):
            e = None  # the clock jumped: start this sensor afresh
        if e is None:  # first advert since boot: its reading is of unknown age; wait for the next one
            self.s[mac] = {'raw': raw, 'chg': None, 'period': PERIOD, 'next': None, 'first': t, 'saved': None}
            return None
        if raw == e['raw']:
            last = e['chg'] if e['chg'] is not None else e['first']
            if t - last >= STUCK and (e['saved'] is None or e['saved'] <= last or t - e['saved'] >= e['period']):
                e['saved'] = t  # payload never changes (other firmware?): keep history going hourly
                return (t, level)
            return None
        e['raw'] = raw
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
        return None if e is None else {'read_at': e['chg'], 'next': e['next'], 'period': e['period']}
