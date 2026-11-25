"""Ask a HAWKi to measure now, over Bluetooth, when it is stuck starting up (runs on MicroPython; due() on CPython too).

After a battery change a monitor sends placeholders (its clock at 0, no level or a 1% battery) and, on 2026-11-20,
went 2 hours without measuring until the Pico connected to it. This does what the Magnus app's "measure" does: no
pairing, no magnet. Service 00001923-1322-ffdd-3533-886fdadce133: notifications on TRIGGER_MEASUREMENT (1960), the
byte 0x07 (depth + battery + temperature) to TX_ON_DEMAND (1963); 1960 then notifies 01 initialized, 02 measured,
05 completed, and the next advert carries the reading.
"""
import binascii, time

WAIT_S = 900      # stuck this long before asking (it may just be about to measure)
AGAIN_S = 1800    # ask again after this, while it stays stuck
MOST = 6          # then leave it: a monitor that never answers shouldn't be kept awake
SVC = '00001923-1322-ffdd-3533-886fdadce133'


LATE_S = 4500     # no new measurement for this long (it measures hourly) counts as stuck too


def stuck(d, age=None):
    """Starting up: its clock at 0, and no level yet or no new measurement for over an hour (age: seconds since its
    last new one). Not the 1% placeholder battery alone: that stays after it measures again (seen 2026-11-20)."""
    return d.get('timestamp') == 0 and bool(d.get('isUnknownLevel') or age is not None and age > LATE_S)


def due(d, st, now, age=None):
    """Whether to ask this monitor to measure now. st: this monitor's {'since', 'last', 'n'}, updated here
    (a monitor that stops being stuck starts afresh next time)."""
    if not stuck(d, age):
        st.clear()
        return False
    st.setdefault('since', now)
    if now - st['since'] < WAIT_S or st.get('n', 0) >= MOST or 'last' in st and now - st['last'] < AGAIN_S:
        return False
    return True


async def measure(ble, at, mac, set_hook, asyncio, secs=60):
    """Connect, trigger, wait for 'completed' (or secs), disconnect: tried 3 times. Returns the notification statuses
    seen ('01', '02', '05'...). The caller stops scanning first and starts it again after."""
    return await _tries(ble, at, mac, set_hook, asyncio, lambda *a: _trigger(*a, secs=secs))


async def set_clock(ble, at, mac, set_hook, asyncio, now):
    """Write the time (UTC; now(): epoch s, the Pico's NTP-set clock, read at the moment of writing) to its DATE_TIME
    (1993) and read it back: tried 3 times. Returns (what it read before, what it reads after). Not written if it
    already reads within a day of now (set meanwhile, by the Magnus app say). The caller stops scanning first and
    starts it again after."""
    wrote = []  # (a retry after our own write was read back wrong must write again, not take it as 'already set')
    return await _tries(ble, at, mac, set_hook, asyncio, lambda *a: _write_clock(*a, now=now, wrote=wrote))


async def _tries(ble, at, mac, set_hook, asyncio, work):
    for k in range(3):  # (a monitor just after a battery change dropped the link about half the time)
        try:
            return await _session(ble, at, mac, set_hook, asyncio, work)
        except OSError:
            if k == 2:
                raise
            await asyncio.sleep_ms(3000)


async def _session(ble, at, mac, set_hook, asyncio, work):
    st = {'svcs': [], 'chrs': [], 'notes': [], 'rd': {}}

    def h(ev, d):
        if ev == 7:
            st['conn'] = d[0]
        elif ev == 8:
            st['disc'] = True
        elif ev == 9:
            st['svcs'].append((d[1], d[2], str(d[3])))
        elif ev == 11:
            st['chrs'].append((d[2], str(d[4])))
        elif ev == 18:
            n = binascii.hexlify(bytes(d[2])).decode()[:2]
            if n not in st['notes'] and len(st['notes']) < 8:  # (each status once, a few at most)
                st['notes'].append(n)
        elif ev == 15:  # _IRQ_GATTC_READ_RESULT
            st['rd'][d[1]] = bytes(d[2])
        elif ev in (10, 12, 16, 17):
            st['done'] = d[-1]

    async def wait(key, t=8):
        t0 = time.ticks_ms()
        while key not in st:
            if st.get('disc') or time.ticks_diff(time.ticks_ms(), t0) > t * 1000:
                raise OSError('no ' + key)
            await asyncio.sleep_ms(50)
        return st.pop(key) if key == 'done' else st[key]

    set_hook(h)
    c = None
    try:
        try:
            ble.gap_connect(None)
        except Exception:
            pass
        ble.gap_connect(at, binascii.unhexlify(mac.replace(':', '')), 15000)
        c = await wait('conn', 17)
        # asked at once, it lists no services, and when it's ready varies (0.5-3 s, measured 2026-11-20): keep asking
        svc = []
        t0 = time.ticks_ms()
        first = True
        while not svc and time.ticks_diff(time.ticks_ms(), t0) < 6000:
            if not first:  # (asked straight away the first time: left idle half a second, it dropped the link)
                await asyncio.sleep_ms(500)
            first = False
            if st.get('disc'):
                raise OSError('dropped after connecting')
            st['svcs'] = []
            try:
                ble.gattc_discover_services(c)
                await wait('done')
            except OSError as ex:
                if st.get('disc'):
                    raise
                continue  # (not ready for it yet)
            svc = [s for s in st['svcs'] if SVC in s[2]]
        if not svc:
            raise OSError('no measuring service')
        ble.gattc_discover_characteristics(c, svc[0][0], svc[0][1])
        await wait('done')
        ch = {u.split("'")[1][4:8]: vh for vh, u in st['chrs'] if "'" in u}
        return await work(ble, c, ch, st, wait, asyncio)
    finally:
        if c is not None and not st.get('disc'):
            try:
                ble.gap_disconnect(c)
            except Exception:
                pass
        else:
            try:
                ble.gap_connect(None)  # (a connection still being tried: cancelled)
            except Exception:
                pass
        try:
            await asyncio.sleep_ms(500)
        finally:
            set_hook(None)  # (cancelled in the pause too)


async def _trigger(ble, c, ch, st, wait, asyncio, secs=60):
    if '1960' not in ch or '1963' not in ch:
        raise OSError('no trigger')
    ble.gattc_write(c, ch['1960'] + 1, b'\x01\x00', 1)  # its notifications on (the descriptor follows the value)
    await wait('done')
    ble.gattc_write(c, ch['1963'], b'\x07', 1)
    await wait('done')
    t0 = time.time()
    while time.time() - t0 < secs and '05' not in st['notes'] and not st.get('disc'):
        await asyncio.sleep_ms(200)
    if not st['notes']:  # (judged by its answers, not the write's status: that came back 14 every time it worked)
        raise OSError('no answer to the measure command')
    return st['notes']


def clock_parse(s):
    """'DD.MM.YYYY HH:MM:SS' (UTC) -> epoch s, or None."""
    try:
        d, mo, y = [int(x) for x in s[:10].split('.')]
        h, mi, se = [int(x) for x in s[11:19].split(':')]
    except (ValueError, IndexError):
        return None
    if not (1 <= mo <= 12 and 1 <= d <= 31 and h < 24 and mi < 60 and se < 60 and len(s) >= 19):
        return None
    y2 = y - (mo <= 2)  # days from 1970-01-01 (proleptic Gregorian)
    era = y2 // 400
    yoe = y2 - era * 400
    doy = (153 * (mo + (-3 if mo > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return (era * 146097 + doe - 719468) * 86400 + h * 3600 + mi * 60 + se


def clock_text(now):
    """The monitor's DATE_TIME format: 'DD.MM.YYYY HH:MM:SS', UTC (what the Magnus app writes when installing)."""
    y, mo, d, h, mi, se = time.gmtime(int(now))[:6]
    return '%02d.%02d.%04d %02d:%02d:%02d' % (d, mo, y, h, mi, se)


async def _write_clock(ble, c, ch, st, wait, asyncio, now=None, wrote=None):
    wrote = [] if wrote is None else wrote
    if '1993' not in ch:
        raise OSError('no clock')

    async def read():
        st['rd'].pop(ch['1993'], None)
        ble.gattc_read(c, ch['1993'])
        await wait('done')
        return (st['rd'].get(ch['1993']) or b'').decode()

    before = await read()
    b = clock_parse(before)
    if not wrote and b is not None and abs(b - now()) <= CLOCK_OFF_S:  # (already set, meanwhile: not moved again)
        return before, before
    wrote.append(1)
    ble.gattc_write(c, ch['1993'], clock_text(now() + 1).encode(), 1)  # (+1: the write itself takes a moment)
    await wait('done')
    await asyncio.sleep_ms(300)
    after = await read()
    a = clock_parse(after)
    if a is None or abs(a - now()) > 120:  # (judged by reading it back, not the write's status)
        raise OSError('clock not taken: ' + after)
    return before, after


CLOCK_WAIT_S = 600       # its clock looks unset this long before it's set (one bad advert is not enough)
CLOCK_AGAIN_S = 6 * 3600  # set again after this if it still looks unset
CLOCK_MOST = 4           # then leave it until it looks right again (or the Pico restarts)
CLOCK_OFF_S = 86400      # an advert time further than this from the Pico's (NTP) time: the clock isn't set


def clock_bad(d, now):
    """Its clock is unset: the advert's time is 0 (just after a battery change) or more than a day from the Pico's.
    A clock that is merely minutes out (an app-installed one ran 4-30 min off) is left alone: readings are placed by
    the Pico's own time anyway (listen.py), and setting a clock moves the monitor's hourly slot."""
    ts = d.get('timestamp')
    return ts is not None and (ts == 0 or abs(now - ts) > CLOCK_OFF_S)


def clock_due(d, st, now, mono):
    """Whether to set this monitor's clock now. now: the Pico's epoch time (must be set: NTP); mono: seconds since
    start. st: this monitor's {'since', 'last', 'n'}, updated here (cleared once its clock looks right)."""
    if now < 1700000000:
        return False
    if not clock_bad(d, now):
        st.clear()
        return False
    st.setdefault('since', mono)
    if mono - st['since'] < CLOCK_WAIT_S or st.get('n', 0) >= CLOCK_MOST or 'last' in st and mono - st['last'] < CLOCK_AGAIN_S:
        return False
    return True


# The offset typed into the Magnus app when a tank is added ("monitor offset": the filling point to the monitor, 0-80
# cm) is written INTO the monitor: RANGE_START (1964) becomes its built-in INTERNAL_OFFSET (1978) plus that, and the
# distance it sends is short by the difference. The Pico wants the real distance (the tank's own heights place the
# monitor), so it reads the two and adds the difference back. One byte each (low byte first if ever two), in cm:
# Stu's monitors 2026-11-24, no offset set: 1978 = 2, 1964 = 2; Conor's 5 cm cut his readings by 50-55 mm.
def le_num(b):
    b = bytes(b or b'')
    if not 1 <= len(b) <= 2:
        raise ValueError('odd value ' + binascii.hexlify(b).decode())
    return b[0] + (b[1] << 8 if len(b) > 1 else 0)


def offset_cm(start, internal):
    """The Magnus app's offset, cm, from RANGE_START and INTERNAL_OFFSET (the app allows 0-80)."""
    d = start - internal
    if not 0 <= d <= 100:
        raise ValueError('odd offset: range start %d, internal %d' % (start, internal))
    return d


def ascii_num(b):
    """RANGE_STOP (1965): ASCII digits, cm, NUL-ended ("0138\\0"; Stu's two monitors 2026-11-25: 0138 and 0126)."""
    t = bytes(b or b'').split(b'\x00')[0]
    if not 1 <= len(t) <= 5 or any(not 48 <= c <= 57 for c in t):
        raise ValueError('odd value ' + binascii.hexlify(bytes(b or b'')).decode())
    return int(t)


# The Magnus app writes two more that matter (seen in its code, 2026-11-25): picking a tank model sets RANGE_STOP
# (1965) to RANGE_START + the model's height less its bottom dead zone, and an offset moves it with RANGE_START; past it
# the monitor reports 'nearly empty' (16382; the app's isNearlyEmpty) instead of a distance. And an offset taking
# RANGE_START past 11 cm raises MIN_MEASURABLE_DISTANCE (1967, one byte, cm; 11 on Stu's) to it: nearer than that,
# no distance. Both read here when the monitor has them (None when not, or odd): the page warns when they cut the tank.
async def read_offset(ble, at, mac, set_hook, asyncio):
    """Connect, read RANGE_START and INTERNAL_OFFSET (and RANGE_STOP, MIN_MEASURABLE_DISTANCE if there), disconnect
    (tried 3 times). Returns (offset cm, start, internal, stop or None, min distance or None). Writes nothing. The
    caller stops scanning first and starts it again after."""
    async def work(ble, c, ch, st, wait, asyncio):
        v = []
        for k, f, need in (('1964', le_num, 1), ('1978', le_num, 1), ('1965', ascii_num, 0), ('1967', le_num, 0)):
            if k not in ch:
                if need:
                    raise OSError('no ' + k)
                v.append(None)
                continue
            try:
                st['rd'].pop(ch[k], None)
                ble.gattc_read(c, ch[k])
                await wait('done')
                v.append(f(st['rd'].get(ch[k])))
            except Exception:  # (an optional one failing never costs the offset)
                if need:
                    raise
                v.append(None)
        return (offset_cm(v[0], v[1]),) + tuple(v)
    return await _tries(ble, at, mac, set_hook, asyncio, work)
