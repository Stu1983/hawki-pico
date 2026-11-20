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
    for k in range(3):  # (a monitor just after a battery change dropped the link about half the time)
        try:
            return await _measure(ble, at, mac, set_hook, asyncio, secs)
        except OSError:
            if k == 2:
                raise
            await asyncio.sleep_ms(3000)


async def _measure(ble, at, mac, set_hook, asyncio, secs):
    st = {'svcs': [], 'chrs': [], 'notes': []}

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
        elif ev in (10, 12, 17):
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
