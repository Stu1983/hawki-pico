# HAWKi tank monitor - Pico 2 W firmware (MicroPython)
# Listens passively for Magnus HAWKi oil-tank monitors, decodes their adverts, works out
# litres from each tank's details, and serves a web page + JSON.
#
# config.json (created on first save):
#   {"ssid": "...", "pw": "...", "token": "<ota token>",
#    "tanks": {"<mac>": {"name", "shape", "height_cm", "length_cm", "width_cm", "capacity_l", "windows"}}}
#
# Web/JSON:
#   GET  /                    web page (ui.html)
#   GET  /api/state           tanks + nearby unadded sensors + wifi status
#   POST /api/tank            add/update a tank (JSON body)       POST /api/tank/delete {"mac"}
#   GET  /api/wifi/scan       nearby networks                     POST /api/wifi {"ssid","pw"} -> restart
#   GET  /hawki               decoded readings (+ litres/percent for configured tanks)
#   GET  /history             history + forecast page (hist.html)
#   GET  /api/hist?mac=       that tank's hourly history: 6-byte records <uint32 epoch, uint16 mm>
#   GET  /api/curve?mac=      litres at every 10 mm of distance (the page maps history with it,
#                             so a changed tank shape re-draws the whole history)
#   POST /api/hist?mac=       merge uploaded history records into the tank's file (restore)
#   GET  /api/deliveries      {mac: [{t, litres, supplier, total, ppl, note}]}  (deliv.json)
#   POST /api/delivery        add/edit {mac, t, old_t?, litres?, supplier?, total?, ppl?, note?}
#                             or {mac, old_t, delete: true}
#   POST /api/restore         {tanks: {mac: cfg}, deliveries: {mac: [...]}} from a backup file
#   GET  /api/update/check    newest release on GitHub vs this version (updater.py)
#   POST /api/update/install  download + verify + install it, then restart (rolls back if it won't run)
# Changes (every POST) need a session from the admin PIN:  GET /api/auth, POST /api/pin/login {pin},
#   POST /api/pin/set {pin} (first setup, or signed in), POST /api/pin/logout. Header: X-Auth.
#   Forgot the PIN: hold the Pico's BOOTSEL button for 5 seconds while it's running.
# Maintenance (token, and only if switched on in Software settings - off by default):
#   PUT /file?name=x&t=TOK, GET /reboot?t=TOK, GET /run?name=x.py&t=TOK
# Debug: GET /devices[?name=&addr=], GET /reset
#
# No Wi-Fi configured, or it can't connect for 60 s: the Pico also opens a setup network
# "HAWKi-Setup-XXXX" (password: oiltanks); browse to http://192.168.4.1/
import bluetooth, binascii, json, time, network, machine, asyncio, gc, os, struct
from hawki_decode import decode, mfr_from_adv
from tankcalc import reading, litres, SHAPES, below, above, tank_equiv, total
import histstore
from version import VERSION
from listen import Listener
import notify
import weather
import price
import drops

# HAWKi service UUID 00001923-1322-ffdd-3533-886fdadce133, as it appears in the advert (LE)
HAWKI_UUID = bytes(reversed(binascii.unhexlify('000019231322ffdd3533886fdadce133')))
AP_PASSWORD = 'oiltanks'
MEASURED_KEYS = ('outlet_cm', 'win_bottom_cm', 'win_top_cm', 'win_outer_w_cm', 'win_inner_w_cm',
                 'win_inner_h_cm', 'rib_h_cm', 'rib_depth_cm')
CFG_KEYS = ('shape', 'height_cm', 'length_cm', 'width_cm', 'capacity_l', 'tank_l', 'windows', 'window_model',
            'ribs_cm', 'reserve_l', 'unusable_l') + MEASURED_KEYS


def load_cfg():
    try:
        c = json.load(open('config.json'))
    except Exception:
        c = {}
    c.setdefault('tanks', {})
    if not c.get('token'):
        c['token'] = binascii.hexlify(os.urandom(8)).decode()
        save_cfg(c)
    return c


def save_cfg(c):
    with open('config.tmp', 'w') as f:
        json.dump(c, f)
    os.rename('config.tmp', 'config.json')


cfg = load_cfg()
TOKEN = cfg['token']
led = machine.Pin('LED', machine.Pin.OUT)
hawki = {}   # mac -> latest decoded reading
seen = {}    # mac -> BLE devices heard lately (debug + names); pruned, see prune_seen()
SEEN_MAX = 60
SEEN_AGE = 600  # forget other devices (phones change address every ~15 min) after 10 minutes


def prune_seen(all_others=False):
    # Long-lived little objects scattered through the heap chop it up, and a secure (TLS) connection
    # needs one big unbroken block of ~40 KB: keep this list short.
    old = time.time() - SEEN_AGE
    for k in list(seen):  # a snapshot: the BLE callback can add devices between our steps
        e = seen.get(k)
        if e is not None and k not in cfg['tanks'] and (all_others or e.get('last', 0) < old):
            if k not in hawki:  # (re-checked last: the callback may have just identified it)
                seen.pop(k, None)


def make_room():
    # before a TLS connection: drop the debug list and collect, so the biggest free block is as big as it gets
    try:
        prune_seen(True)
    except Exception:  # even out of memory: carry on with the action
        pass
    gc.collect()


def with_room(fn, *a):
    # one retry when the heap was too chopped up for TLS (MemoryError, or mbedtls' OSError ENOMEM)
    make_room()
    try:
        return fn(*a)
    except Exception as ex:
        if not (isinstance(ex, MemoryError) or getattr(ex, 'errno', None) == 12 or (ex.args and ex.args[0] == 12)):
            raise
    make_room()
    return fn(*a)
boot = time.time()
boot_ms = time.ticks_ms()


def hx(b):
    return binascii.hexlify(bytes(b)).decode()


def name_of(adv):
    i = 0
    while i + 1 < len(adv):
        l = adv[i]
        if l == 0:
            break
        if adv[i + 1] in (8, 9):
            return bytes(adv[i + 2:i + 1 + l]).decode('utf-8', 'replace')
        i += 1 + l
    return ''


def irq(ev, data):
    if ev == 5:  # _IRQ_SCAN_RESULT
        at, addr, adv_type, rssi, adv = data
        k = binascii.hexlify(bytes(addr), ':').decode()
        e = seen.get(k)
        if e is None:
            if (len(seen) >= SEEN_MAX and k not in cfg['tanks'] and k not in hawki
                    and not (adv_type == 0 and HAWKI_UUID in bytes(adv))):  # memory guard (never shuts out a HAWKi, even a new one)
                return
            e = seen[k] = {'at': at, 'n': 0, 'max': rssi, 'name': '', 'adv': {}}
        e['n'] += 1
        e['rssi'] = rssi
        if rssi > e['max']:
            e['max'] = rssi
        e['last'] = time.time()
        n = name_of(adv)
        if n:
            e['name'] = n[:40]
            if k in hawki:
                hawki[k]['name'] = e['name']
        if adv_type == 0 and HAWKI_UUID in bytes(adv):
            m = mfr_from_adv(adv)
            if m:
                d = decode(m)
                d['raw'] = hx(m)
                d['rssi'] = rssi
                d['rx'] = time.time()
                d['name'] = e['name']
                lv = d.get('level')
                prev = hawki.get(k) or {}
                if lv is None or lv == 16383 or lv < MIN_MM:  # no level, or inside the radar's blind zone: a misread
                    d['bad_level'] = lv            # (seen: 0 mm on a cold morning), never real. Keep showing the last good level
                    d['level'] = prev['level'] if prev.get('level') is not None else 16383   # (and its time); don't save it
                    d['good_at'] = prev.get('good_at')
                    if d['good_at'] and d['good_at'] > time.time():
                        d['good_at'] = None  # the clock was put back: that time can't be trusted
                else:  # a good reading: when it first arrived (a repeat of the same measurement keeps that time)
                    now_s = int(time.time())
                    d['good_at'] = None if now_s < 1700000000 else prev.get('good_at') if prev.get('raw') == d['raw'] and prev.get('good_at') and prev['good_at'] <= now_s else now_s  # clock not set: unknown
                hawki[k] = d
                if k in cfg['tanks']:  # new hourly measurement? (its payload changes) -> queue it for saving
                    r = listener.heard(k, d['raw'], 16383 if 'bad_level' in d else d.get('level'), int(time.time()))  # (16383: not saved)
                    if r and r[1] not in (None, 16383):
                        pending.append((k, r[0], r[1]))
        h = hx(adv)
        lst = e['adv'].setdefault(str(adv_type), [])
        if h not in lst:
            lst.append(h)
            if len(lst) > 2:
                lst.pop(0)
    elif ev == 6:  # _IRQ_SCAN_DONE (stopped or mode change): carry on in the wanted mode, if any
        scan_running[0] = False
        start_scan()
    elif hook[0]:
        hook[0](ev, data)


scan_on = [True]   # False while /run experiments do GATT work
scan_mode = [None]  # None (radio left to Wi-Fi), 'passive' (tank readings), 'active' (also asks for names)
scan_running = [False]
hook = [None]  # experiments (/run) receive every non-scan BLE event here
listener = Listener()
pending = []  # (mac, time, level) new measurements, saved by recorder()
MIN_MM = 30  # closer than this to the sensor can't be a real reading (radar blind zone)
discover_until = [None]  # ticks_ms: listen actively (names, new sensors) until then; None when off

ble = bluetooth.BLE()
ble.active(True)
ble.irq(irq)


def start_scan():
    if scan_mode[0] and scan_on[0] and not scan_running[0]:
        scan_running[0] = True
        try:
            ble.gap_scan(0, 60000, 30000, scan_mode[0] == 'active')  # until stopped, 50% duty
        except Exception as ex:
            scan_running[0] = False  # the scheduler tries again in 2 s
            print('scan start err', ex)


def stop_scan():
    try:
        ble.gap_scan(None)  # SCAN_DONE then restarts it in the wanted mode (or leaves it off)
    except Exception as ex:
        print('scan stop err', ex)  # still running: the scheduler tries again in 2 s


def want_scan(mode):
    if mode != scan_mode[0]:
        scan_mode[0] = mode
        if scan_running[0]:
            return stop_scan()
    if mode is None:
        if scan_running[0]:
            stop_scan()  # a stop that failed (or SCAN_DONE not in yet): ask again
    else:
        start_scan()  # (re)start if it stopped


def discover(secs):
    discover_until[0] = time.ticks_add(time.ticks_ms(), secs * 1000)


pruned = [0]


async def scan_scheduler():
    # Listen only when it's useful: while a tank's hourly reading is due (until it arrives), and
    # actively while looking for sensors (first minutes after boot, or the Sensors nearby list is open).
    discover(180)
    while True:
        try:
            tanks = list(cfg['tanks'])
            if discover_until[0] is not None and time.ticks_diff(discover_until[0], time.ticks_ms()) <= 0:
                discover_until[0] = None  # expired: clear it, so the tick counter wrapping can't revive it
            if not tanks or discover_until[0] is not None:
                mode = 'active'
            elif listener.due(tanks, int(time.time())):
                mode = 'passive'
            else:
                mode = None
            want_scan(mode)
            if time.ticks_diff(time.ticks_ms(), pruned[0]) > 60000:
                pruned[0] = time.ticks_ms()
                prune_seen()
        except Exception as ex:
            print('scan err', ex)
        await asyncio.sleep(2)

def ok_hostname(h):
    h = str(h or '').strip().lower()
    if not (1 <= len(h) <= 32 and h[0] != '-' and h[-1] != '-' and all(c.isdigit() or 'a' <= c <= 'z' or c == '-' for c in h)):
        raise ValueError('use 1 to 32 letters, digits or hyphens (not at the start or end)')
    return h


HOSTNAME = cfg.get('hostname') or 'hawki-pico'
try:
    network.hostname(HOSTNAME)  # what the router lists; http://<name>.local/ where mDNS works
except Exception:
    pass
wlan = network.WLAN(network.STA_IF)
ap = network.WLAN(network.AP_IF)
AP_NAME = 'HAWKi-Setup-' + hx(machine.unique_id())[-4:].upper()


async def ntp_sync():
    import ntptime
    for host in ('pool.ntp.org', 'time.google.com'):
        try:
            ntptime.host = host
            ntptime.settime()
            return True
        except Exception as ex:
            print('ntp err', host, ex)
        await asyncio.sleep(0)
    return False


def ap_on():
    if not ap.active():
        ap.config(essid=AP_NAME, password=AP_PASSWORD)
        ap.active(True)
        print('setup AP', AP_NAME)


async def wifi_keeper():
    wlan.active(True)
    wlan.config(pm=0xa11140)  # power-save off: steadier for BLE coexistence + HTTP
    while True:
        if cfg.get('ssid') and not wlan.isconnected():
            try:
                wlan.connect(cfg['ssid'], cfg.get('pw', ''))
            except Exception as ex:
                print('wifi err', ex)
            for _ in range(20):
                if wlan.isconnected():
                    print('wifi ok', wlan.ifconfig())
                    await ntp_sync()
                    break
                led.toggle()
                await asyncio.sleep(0.5)
        if wlan.isconnected():
            led.value(1)
            if ap.active():
                ap.active(False)
            if time.time() < 1700000000:
                await ntp_sync()  # clock still unset; retry
        else:
            led.value(0)
            if not cfg.get('ssid') or time.ticks_diff(time.ticks_ms(), boot_ms) > 60000:
                ap_on()
        await asyncio.sleep(10)


# ---------- history ----------
# Each new hourly measurement (listen.py) is appended to h_<last 6 hex of mac>.bin as
# <uint32 epoch (when it appeared), uint16 mm>: 52 KB a year
# per tank. Distances, not litres, so changing a tank's shape re-maps the whole history.
# Daily at 03:00 UTC, readings older than KEEP_HOURLY_DAYS shrink to one per day (that day's
# median; histstore.py), so history stays ~110 KB per tank for good.
KEEP_HOURLY_DAYS = 730


def hist_name(mac):
    return 'h_' + mac.replace(':', '')[-6:] + '.bin'


async def compact_all(now):
    for mac in list(cfg['tanks']):  # ~2 s per 2-year file; let BLE/HTTP run in between
        try:
            print('compact', mac, histstore.compact(hist_name(mac), now - KEEP_HOURLY_DAYS * 86400))
        except Exception as ex:
            print('compact err', mac, ex)
        await asyncio.sleep(0)


async def recorder():
    # Save each new measurement with the time it appeared (one per sensor per hour).
    done_day = None
    while True:
        await asyncio.sleep(10)
        now = time.time()
        while len(pending) > 100:  # bound: a stuck flash can't eat the memory
            pending.pop(0)
        while pending:
            mac, t, lvl = pending[0]
            if t >= 1700000000 and mac in cfg['tanks']:  # clock set, tank still configured
                try:
                    with open(hist_name(mac), 'ab') as f:
                        f.write(struct.pack('<IH', t, lvl))
                    if mac not in last_saved or last_saved[mac] is None or t >= last_saved[mac][0]:
                        last_saved[mac] = (t, lvl)
                except Exception as ex:
                    print('hist err', ex)
                    break  # keep it; try again next time
                pending.pop(0)
                try:
                    await drop_check(mac, t, lvl)
                except Exception as ex:
                    print('drop check err', ex)
                continue
            pending.pop(0)
        if now >= 1700000000 and (now // 3600) % 24 >= 3 and done_day != now // 86400:
            done_day = now // 86400
            await compact_all(now)


def curve(t):
    H = float(t['height_cm']) * 10
    n = int(H // 10)
    out = [round(litres(t, min(H, i * 10)), 1) for i in range(n + 1)]
    if n * 10 < H:
        out.append(0.0)
    return {'step': 10, 'h': H, 'l': out}


# ---------- admin PIN + sessions ----------
# The PIN is stored salted + hashed; sessions are random tokens kept (hashed) in config.json so a
# restart doesn't sign everyone out. Wrong PINs lock sign-in for 30 s after 5 tries, doubling to 1 h.
lock = {'fails': 0, 'until': 0, 'wait': 30}


def _sha(s):
    import hashlib
    return binascii.hexlify(hashlib.sha256(s.encode()).digest()).decode()


def pin_ok(pin):
    return bool(cfg.get('pin')) and _sha(cfg.get('pin_salt', '') + str(pin)) == cfg['pin']


def new_session():
    tok = binascii.hexlify(os.urandom(16)).decode()
    cfg['sessions'] = (cfg.get('sessions') or [])[-7:] + [_sha(tok)]
    save_cfg(cfg)
    return tok


def authed(tok):
    return bool(tok) and bool(cfg.get('pin')) and _sha(tok) in (cfg.get('sessions') or [])


def set_pin(pin):
    pin = str(pin or '')
    if not 4 <= len(pin) <= 12:
        raise ValueError('use 4 to 12 characters')
    cfg['pin_salt'] = binascii.hexlify(os.urandom(8)).decode()
    cfg['pin'] = _sha(cfg['pin_salt'] + pin)
    cfg['sessions'] = []  # everyone else has to sign in with the new PIN
    return new_session()


FIRST_PIN_SECS = 1800


first_pin_window = [True]


async def close_first_pin_window():
    await asyncio.sleep(FIRST_PIN_SECS)
    first_pin_window[0] = False


def may_set_first_pin(peer):
    # Without a PIN, whoever sets one first owns the Pico. So a FIRST PIN can only be set from the
    # setup network (while it's actually up), or within 30 minutes of the Pico starting.
    on_setup_ap = ap.active() and peer.startswith(ap.ifconfig()[0].rsplit('.', 1)[0] + '.')
    return on_setup_ap or first_pin_window[0]


def try_login(pin):
    now = time.time()
    if now < lock['until']:
        raise ValueError('too many wrong PINs: try again in %d seconds' % (lock['until'] - now))
    if pin_ok(pin):
        lock.update(fails=0, wait=30)
        return new_session()
    lock['fails'] += 1
    if lock['fails'] >= 5:
        lock['until'] = now + lock['wait']
        lock['wait'] = min(3600, lock['wait'] * 2)
        lock['fails'] = 0
    raise ValueError('wrong PIN')


async def bootsel_reset():
    # Physical PIN reset: hold BOOTSEL for 5 s (needs someone at the Pico).
    try:
        import rp2
        rp2.bootsel_button()
    except Exception:
        return
    held = 0
    while True:
        await asyncio.sleep(0.5)
        held = held + 1 if rp2.bootsel_button() else 0
        if held == 10:
            for k in ('pin', 'pin_salt', 'sessions'):
                cfg.pop(k, None)
            save_cfg(cfg)
            print('PIN cleared by BOOTSEL')
            for _ in range(10):
                led.toggle()
                await asyncio.sleep(0.1)


def free_bytes():
    st = os.statvfs('/')
    return st[0] * st[3]


async def read_body_to(r, name, clen, pre=b'', secs=120):
    pre = pre[:clen]
    got, dl = len(pre), time.ticks_add(time.ticks_ms(), secs * 1000)
    with open(name, 'wb') as fh:
        fh.write(pre)
        while got < clen:
            left = time.ticks_diff(dl, time.ticks_ms())
            if left <= 0:
                raise OSError('upload too slow')
            chunk = await asyncio.wait_for(r.read(min(1024, clen - got)), left / 1000)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
    return got


def rm(name):
    try:
        os.remove(name)
    except OSError:
        pass


MUTATING = ('/api/tank', '/api/tank/delete', '/api/wifi', '/api/delivery', '/api/restore', '/api/hist',
            '/api/update/install', '/api/maint', '/api/primary', '/api/hostname', '/api/notify', '/api/notify/test', '/api/location', '/api/price')


# ---------- views ----------

last_saved = {}  # mac -> (epoch, mm): the newest reading in its history file (read once, then kept up to date)


def saved_last(mac):
    if mac not in last_saved:
        last_saved[mac] = None
        try:
            n = os.stat(hist_name(mac))[6] // 6
            if n:
                with open(hist_name(mac), 'rb') as f:
                    f.seek((n - 1) * 6)
                    last_saved[mac] = struct.unpack('<IH', f.read(6))
        except Exception:
            pass
    return last_saved[mac]


def tank_view(mac, t, now):
    d = hawki.get(mac) or {}
    lvl = d.get('level')
    if lvl in (None, 16383):  # nothing heard yet since a restart, or only a misread: the last saved reading,
        s = saved_last(mac)   # with its own time (so it's never passed off as fresh, and alerts don't use it)
        if s and 1700000000 < now and s[0] <= now + 60:  # (not one dated ahead of a clock that was put back)
            d = dict(d, good_at=s[0], bad_level=d.get('bad_level')) if 'bad_level' in d else dict(d, good_at=s[0], saved=True)
            lvl = s[1]
    lit, pct = reading(t, lvl) if lvl is not None else (None, None)
    std = tot = tot_std = None  # Magnus-style standard model, for comparison; and all the oil (floor up)
    try:
        if lvl is not None:
            tot = total(t, lvl)
            if t.get('window_model') == 'measured':
                std = reading(dict(t, window_model='standard'), lvl)[0]
                tot_std = total(dict(t, window_model='standard'), lvl)
    except Exception:  # odd stored values must never break /api/state
        pass
    r1 = lambda v: None if v is None else round(v, 1)
    return {'mac': mac, 'name': t.get('name', mac), 'level': lvl, 'litres': lit, 'percent': pct,
            # misread: the rejected reading (-1: no level at all), or None
            'misread': (-1 if d['bad_level'] is None else d['bad_level']) if 'bad_level' in d else None, 'good_at': d.get('good_at'), 'saved': bool(d.get('saved')), 'litres_standard': std, 'total': r1(tot), 'total_standard': r1(tot_std), 'unusable': unusable(t), 'listen': listener.info(mac),
            'battery': d.get('battery'), 'rssi': d.get('rssi'),
            'age': (now - d['good_at'] if d.get('good_at') else None) if 'bad_level' in d or d.get('saved') else (now - d['rx']) if d.get('rx') else None,  # after a misread: the shown level's own age
            'cfg': cfg_view(t)}


_equiv = {}


def cfg_view(t):
    c = {k: t.get(k) for k in CFG_KEYS}
    if c.get('tank_l') is None:  # older settings: suggest the equivalent whole-tank capacity to the form
        try:
            key = repr(sorted(t.items()))  # (worked out once per setting, not on every /api/state)
            if key not in _equiv:
                if len(_equiv) > 8:
                    _equiv.clear()
                v = tank_equiv(t)
                _equiv[key] = None if v is None else round(v, 1)
            c['tank_l_equiv'] = _equiv[key]
        except Exception:  # never let a suggestion break /api/state
            pass  # a separate key, so a backup never converts settings by itself
    return c


def unusable(t):
    """Oil below the top of the outlet, which the boiler can't draw: [litres, 'set'|'estimate'] or None."""
    try:  # the whole-tank model knows it (and takes precedence over an old hand-entered figure)
        if t.get('tank_l') is not None:
            return [round(below(t)), 'estimate']
    except Exception:
        pass
    if t.get('unusable_l') is not None:
        return [t['unusable_l'], 'set']
    try:  # a cuboid with a measured outlet height: footprint x outlet height
        if t.get('shape') == 'cuboid' and t.get('outlet_cm'):
            return [round(float(t['length_cm']) * float(t['width_cm']) * float(t['outlet_cm']) / 1000), 'estimate']
    except Exception:  # odd stored values must never break /api/state
        pass
    return None


# ---------- notifications ----------
# cfg['notify'] = {po_user, po_token, ntfy_topic, ntfy_host, reorder (bool)}; secrets never leave the Pico.
# cfg['alerted'][mac] = {'reorder': epoch}: what has been sent, so a restart doesn't repeat it.
REARM_L = 100  # an alert re-arms once the tank is this far back above its level (i.e. after a delivery)


def notify_view():
    n = cfg.get('notify') or {}
    t = n.get('ntfy_topic') or ''
    return {'channels': notify.channels(n), 'po_user': bool(n.get('po_user')), 'po_token': bool(n.get('po_token')),
            'ntfy_topic': (t[:3] + '…') if t else '', 'ntfy_host': n.get('ntfy_host') or 'ntfy.sh',
            'reorder': n.get('reorder', True), 'drops': n.get('drops', True), 'battery': n.get('battery', True), 'silent': n.get('silent', True),
            'burner_lph': n.get('burner_lph', 6)}


def set_notify(b):
    n = dict(cfg.get('notify') or {})
    if 'po_user' in b:
        n['po_user'] = notify.ok_key(b['po_user'], 'Pushover user key')
    if 'po_token' in b:
        n['po_token'] = notify.ok_key(b['po_token'], 'Pushover app token')
    if 'ntfy_topic' in b:
        n['ntfy_topic'] = notify.ok_topic(b['ntfy_topic'])
    if 'ntfy_host' in b:
        n['ntfy_host'] = notify.ok_host(b['ntfy_host'])
    for k in ('reorder', 'drops', 'battery', 'silent'):
        if k in b:
            n[k] = bool(b[k])
    if b.get('burner_lph') not in (None, ''):
        n['burner_lph'] = num(b['burner_lph'], 1, 30)
    cfg['notify'] = {k: v for k, v in n.items() if v not in ('', None)}
    save_cfg(cfg)


async def send_alert(title, msg, urgent=False):
    await asyncio.sleep(0)
    make_room()
    res = notify.send(cfg.get('notify'), title, msg, urgent)  # blocks ~1-2 s per channel (TLS)
    print('notify', title, res)
    return res


recent = {}  # mac -> [(epoch, mm)] of the last few hours, for the sudden-drop check (distances, so a tank edit re-maps them)


def seed_recent(mac):
    # after a restart: the last few saved readings, so a drop isn't missed across a reboot
    try:
        n = os.stat(hist_name(mac))[6] // 6
        with open(hist_name(mac), 'rb') as f:
            f.seek(max(0, n - 8) * 6)
            raw = f.read()
        recent[mac] = [(ts, mm) for ts, mm in (struct.unpack('<IH', raw[i:i + 6]) for i in range(0, len(raw) - 5, 6))
                       if mm != 16383 and ts > time.time() - drops.WINDOW]
    except Exception:
        recent[mac] = []


async def drop_check(mac, t, lvl):
    # a new reading: oil going faster than the burner could burn it -> urgent alert (at most every 12 h)
    tank = cfg['tanks'].get(mac)
    if tank is None:
        return
    if mac not in recent:
        seed_recent(mac)
    r = recent[mac]
    if not r or r[-1][0] != t:  # (just after a restart the seed already holds this reading)
        r.append((t, lvl))
    r[:] = [x for x in r if t - x[0] <= drops.WINDOW][-10:]
    n = cfg.get('notify') or {}
    if not (n.get('drops', True) and notify.channels(n)):
        return
    hit = drops.check([(ts, reading(tank, mm)[0]) for ts, mm in r], float(n.get('burner_lph', 6)))  # current shape
    a = cfg.setdefault('alerted', {}).setdefault(mac, {})
    if hit and time.time() - a.get('drop', 0) > 12 * 3600:
        res = await send_alert('%s: oil dropping fast' % tank.get('name', mac),
                               '%d L gone in %.0f hours, more than the burner can use (%s L/h). Check for a leak or theft.'
                               % (hit[0], max(1, hit[1]), n.get('burner_lph', 6)), urgent=True)
        if 'ok' in res.values():
            a['drop'] = int(time.time())
            save_cfg(cfg)


BATT_LOW = 20     # % : tell the phone once at or below this
BATT_REARM = 40   # % : a new battery (back above this) arms it again
batt_seen = {}    # mac -> [last payload counted, lows in a row, highs in a row]


async def battery_check(n, mac, t, d, a):
    # Counts MEASUREMENTS (the monitor repeats each hourly one in between), so it takes three hourly
    # readings in a row to alert (one cold reading doesn't), and three good ones to re-arm.
    b = d.get('battery')
    if b is None:
        return
    st = batt_seen.setdefault(mac, [None, 0, 0])
    if d.get('raw') is not None and d.get('raw') == st[0]:
        return  # the same measurement again
    st[0] = d.get('raw')
    st[1] = st[1] + 1 if b <= BATT_LOW else 0
    st[2] = st[2] + 1 if b >= BATT_REARM else 0
    if a.get('battery') and st[2] >= 3:
        a.pop('battery')  # new battery
        save_cfg(cfg)
    if n.get('battery', True) and not a.get('battery') and st[1] >= 3:
        res = await send_alert('%s: monitor battery low' % t.get('name', mac),
                               'The HAWKi monitor reports %d%% battery. Replace it soon, or readings will stop.' % b)
        if 'ok' in res.values():
            a['battery'] = int(time.time())
            save_cfg(cfg)


SILENT_H = 6  # hours with no new measurement before saying so
quiet_clock = {'start': None, 'prev': None}  # when the clock-based count began; the previous check's time


def quiet_since_start(now):
    # The moment silence is counted from at the earliest: the first check with a set clock, and again after
    # the clock jumps (an NTP correction), so neither a restart nor a correction looks like hours of silence.
    q = quiet_clock
    if q['start'] is None or q['prev'] is None or not 0 <= now - q['prev'] <= 900:  # checks come every 5 min
        q['start'] = now
    q['prev'] = now
    return q['start']


async def silent_check(n, mac, t, e, now, start, a):
    # e: the listener's record for this monitor (None if not heard since boot). A new measurement every hour
    # is normal; none for SILENT_H hours means a flat battery, a fault, or out of range. Once, until it's back.
    if now < 1.7e9:
        return  # clock not set yet
    chg = None if e is None else e.get('chg')  # a genuinely new measurement (not just heard again after a restart)
    if a.get('silent') and chg is not None and e.get('raw') != a.get('silent_raw'):
        a.pop('silent')  # a different reading from the one we were stuck on: arm it again
        a.pop('silent_raw', None)
        save_cfg(cfg)
    last = None if e is None else (chg or e.get('first'))
    since = max(last or 0, start)
    if n.get('silent', True) and not a.get('silent') and now - since > SILENT_H * 3600:
        res = await send_alert('%s: no readings' % t.get('name', mac),
                               'Nothing new from the monitor for %d hours. Its battery may be flat, or it may be out of '
                               'range of the Pico.' % ((now - since) // 3600))
        if 'ok' in res.values():
            a['silent'] = int(now)
            if e is not None:
                a['silent_raw'] = e.get('raw')
            save_cfg(cfg)


async def alerts():
    # Every few minutes: tell the phone(s) once when a tank reaches its reorder level, a monitor's battery is low,
    # or a monitor has gone quiet.
    await asyncio.sleep(120)
    while True:
        try:
            n = cfg.get('notify') or {}
            if notify.channels(n) and wlan.isconnected():
                al = cfg.setdefault('alerted', {})
                start = quiet_since_start(time.time())
                for mac, t in list(cfg['tanks'].items()):
                    d = hawki.get(mac) or {}
                    a = al.setdefault(mac, {})
                    fresh = time.time() - d.get('rx', 0) <= 3 * 3600  # (judged before any slow send below)
                    try:
                        await silent_check(n, mac, t, listener.s.get(mac), time.time(), start, a)
                    except Exception as ex:
                        print('silent alert err', ex)
                    if not fresh:
                        continue  # not heard lately: nothing current to go on
                    try:  # (its own try: it must never stop the reorder check)
                        await battery_check(n, mac, t, d, a)
                    except Exception as ex:
                        print('battery alert err', ex)
                    lvl = d.get('level')
                    if lvl in (None, 16383) or 'bad_level' in d:
                        continue  # no reading, or the latest was a misread (the level shown is an older one)
                    lit = reading(t, lvl)[0]
                    if lit is None:
                        continue
                    reserve = float(t['reserve_l']) if t.get('reserve_l') is not None else 200.0
                    if a.get('reorder') and lit >= reserve + REARM_L:
                        a.pop('reorder')  # topped up: arm it again
                        save_cfg(cfg)
                    elif n.get('reorder', True) and not a.get('reorder') and lit <= reserve:
                        res = await send_alert('%s: time to order oil' % t.get('name', mac),
                                               '%d L left, at or below your reorder level of %d L.' % (lit, reserve))
                        if 'ok' in res.values():
                            a['reorder'] = int(time.time())
                            save_cfg(cfg)
        except Exception as ex:
            print('alerts err', ex)
        await asyncio.sleep(300)


def update_info():
    try:
        last = json.load(open('upd.last'))
    except (OSError, ValueError):
        last = None
    try:
        os.stat('upd.pending')
        pending = True
    except OSError:
        pending = False
    return {'version': VERSION, 'last': last, 'pending': pending}


async def update_guard():
    # Confirm a fresh update once it has run for 2 minutes with Wi-Fi up (or no Wi-Fi set up yet).
    # If it can't get onto the Wi-Fi it used to join within 10 minutes, put the old version back.
    if not update_info()['pending']:
        return
    import updater
    for i in range(60):
        await asyncio.sleep(10)
        if i >= 11 and (wlan.isconnected() or not cfg.get('ssid')):
            print('update confirmed', updater.commit())
            return
    import rollback
    rollback.undo('no Wi-Fi after the update')
    machine.reset()


manifest = [None]


def name_key(name):
    """Natural sort: 'Tank 2' before 'Tank 10', case ignored."""
    out, num = [], ''
    for c in str(name).lower() + ' ':
        if c.isdigit():
            num += c
            continue
        if num:
            out.append((0, int(num), ''))
            num = ''
        out.append((1, 0, c))
    return out


def state():
    now = time.time()
    tanks = sorted((tank_view(m, t, now) for m, t in cfg['tanks'].items()), key=lambda v: name_key(v['name']))
    found = []
    for m, d in hawki.items():
        if m in cfg['tanks'] or now - d['rx'] > 900:
            continue
        found.append({'mac': m, 'name': d.get('name', ''), 'rssi': d.get('rssi'),
                      'age': now - d['rx'], 'level': d.get('level')})
    found.sort(key=lambda f: -(f['rssi'] or -999))
    return {'tanks': tanks, 'found': found,
            'ssid': cfg.get('ssid') if wlan.isconnected() else None,
            'ip': wlan.ifconfig()[0] if wlan.isconnected() else None,
            'wifi_rssi': wlan.status('rssi') if wlan.isconnected() else None,
            'ap': AP_NAME if ap.active() else None, 'update': update_info(),
            'pin_set': bool(cfg.get('pin')), 'maint': bool(cfg.get('maint')),
            'primary': cfg.get('primary') if cfg.get('primary') in cfg['tanks'] or cfg.get('primary') == 'all' and len(tanks) > 1
                       else (tanks[0]['mac'] if tanks else None),
            'hostname': HOSTNAME, 'scan': scan_mode[0], 'notify': notify_view(), 'wx': wx_view(), 'price': price_view(), 'mac': ':'.join('%02x' % c for c in wlan.config('mac'))}


def num(v, lo, hi):
    v = float(v)
    if not (lo <= v <= hi):
        raise ValueError('out of range')
    return v


def set_tank(b, restore=False):
    mac = str(b.get('mac', '')).lower()
    if len(mac) != 17 or not restore and mac not in hawki and mac not in cfg['tanks']:
        raise ValueError('unknown sensor')
    shape = b.get('shape', 'cuboid')
    if shape not in SHAPES:
        raise ValueError('bad shape')
    t = {'name': (str(b.get('name') or '').strip() or mac)[:24], 'shape': shape,
         'height_cm': num(b['height_cm'], 10, 500),
         'windows': int(num(b.get('windows', 0), 0, 2))}
    for k in ('reserve_l', 'unusable_l'):
        if b.get(k) not in (None, ''):
            t[k] = num(b[k], 0, 100000)
    if b.get('isolated'):
        t['isolated'] = True  # valve closed: its oil counts in the total, its readings never count as use
    if b.get('outlet_cm') not in (None, ''):  # ground to the top of the outlet (any shape)
        t['outlet_cm'] = num(b['outlet_cm'], 0, 1000)
    if shape == 'cuboid':
        t['length_cm'] = num(b['length_cm'], 1, 2000)
        t['width_cm'] = num(b['width_cm'], 1, 2000)
        if b.get('window_model') == 'measured':
            t['window_model'] = 'measured'
            for k in MEASURED_KEYS:
                if b.get(k) not in (None, ''):
                    t[k] = num(b[k], 0, 1000)
            ribs = b.get('ribs_cm') or []
            if isinstance(ribs, str):
                ribs = [x for x in ribs.replace(';', ',').split(',') if x.strip()]
            t['ribs_cm'] = [num(x, 0, 1000) for x in ribs][:6]
            if t['windows'] and not ('win_bottom_cm' in t and 'win_top_cm' in t and 'win_outer_w_cm' in t):
                raise ValueError('measured windows need bottom, top and outer width')
    if b.get('tank_l') not in (None, ''):
        # the whole tank (spec sheet): the usable part above the outlet is worked out from the shape
        t['tank_l'] = num(b['tank_l'], 1, 200000)
        t['capacity_l'] = round(above(t), 1)
        if t['capacity_l'] < 1:
            raise ValueError('the capacity is too small for that outlet height')
    else:
        t['capacity_l'] = num(b['capacity_l'], 1, 100000)
    cfg['tanks'][mac] = t
    if not restore:
        save_cfg(cfg)


# ---------- deliveries (supplier + price per fill) ----------

def load_deliv():
    try:
        return json.load(open('deliv.json'))
    except Exception:
        return {}


def save_deliv(d):
    with open('deliv.tmp', 'w') as f:
        json.dump(d, f)
    os.rename('deliv.tmp', 'deliv.json')


def opt(b, k, lo, hi):
    v = b.get(k)
    return None if v in (None, '') else num(v, lo, hi)


def clean_delivery(b):
    t = int(b['t'])  # keep it an int: the Pico's floats are single precision (would round to 128 s)
    if not 1500000000 <= t <= (time.time() + 2 * 86400 if time.time() > 1700000000 else 4000000000):
        raise ValueError('bad date')
    return {'t': t, 'litres': opt(b, 'litres', 0, 100000), 'total': opt(b, 'total', 0, 1000000),
            'ppl': opt(b, 'ppl', 0, 100000), 'supplier': str(b.get('supplier') or '').strip()[:40],
            'note': str(b.get('note') or '').strip()[:80]}


def set_delivery(b):
    mac = str(b.get('mac', '')).lower()
    if mac not in cfg['tanks']:
        raise ValueError('unknown tank')
    d = load_deliv()
    old = b.get('old_t')
    old = int(old) if old not in (None, '') else None
    lst = [x for x in d.get(mac, []) if x['t'] != old]
    if not b.get('delete'):
        rec = clean_delivery(b)
        lst = [x for x in lst if x['t'] != rec['t']] + [rec]
    lst.sort(key=lambda x: x['t'])
    d[mac] = lst[-200:]
    save_deliv(d)


def restore(b):
    tanks = b.get('tanks') or {}
    for mac, t in tanks.items():
        set_tank(dict(t, mac=mac), restore=True)
    save_cfg(cfg)
    d = load_deliv()
    for mac, lst in (b.get('deliveries') or {}).items():
        mac = mac.lower()
        if mac in cfg['tanks']:
            d[mac] = sorted([clean_delivery(x) for x in lst], key=lambda x: x['t'])[-200:]
    save_deliv(d)
    return len(tanks)


def merge_hist(name, tmp):
    # both files are sorted by time: two-pointer merge, low memory; existing records win on ties
    def nxt(f):
        if f is None:
            return None
        r = f.read(6)
        return struct.unpack('<IH', r) if len(r) == 6 else None
    try:
        a = open(name, 'rb')
    except OSError:
        a = None
    n, last = 0, -1
    with open(tmp, 'rb') as b, open(name + '.new', 'wb') as o:
        ra, rb = nxt(a), nxt(b)
        while ra or rb:
            if rb is None or (ra is not None and ra[0] <= rb[0]):
                r, ra = ra, nxt(a)
            else:
                r, rb = rb, nxt(b)
            if r[0] != last and r[1] not in (16383, 0xffff):  # skip 'unknown level' readings
                o.write(struct.pack('<IH', r[0], r[1]))
                last, n = r[0], n + 1
    if a:
        a.close()
    os.rename(name + '.new', name)
    os.remove(tmp)
    return n


def hawki_json():
    now = time.time()
    tanks = {m: tank_view(m, t, now) for m, t in cfg['tanks'].items()}
    return json.dumps({'now': now, 'sensors': hawki, 'tanks': tanks})


# ---------- http ----------

def parse_q(path):
    q = {}
    if '?' in path:
        path, qs = path.split('?', 1)
        for kv in qs.split('&'):
            if '=' in kv:
                k, v = kv.split('=', 1)
                q[k] = v
    return path, q


async def send(w, code, body, ctype='application/json'):
    b = body.encode() if isinstance(body, str) else body
    w.write(('HTTP/1.0 %d OK\r\nContent-Type: %s\r\nContent-Length: %d\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n'
             % (code, ctype, len(b))).encode())
    w.write(b)
    await asyncio.wait_for(w.drain(), 20)  # a client that stops reading can't hold a slot forever


async def send_file(w, name, ctype):
    size = os.stat(name)[6]
    w.write(('HTTP/1.0 200 OK\r\nContent-Type: %s\r\nContent-Length: %d\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n' % (ctype, size)).encode())
    with open(name, 'rb') as f:
        while True:
            chunk = f.read(1024)
            if not chunk:
                break
            w.write(chunk)
            await asyncio.wait_for(w.drain(), 20)


conns = [0]
installing = [False]
hist_busy = [False]


async def handle(r, w):
    conns[0] += 1
    try:
        if conns[0] > 6:  # don't let a pile of idle connections starve the Pico
            return
        dl = time.ticks_add(time.ticks_ms(), 15000)  # the whole request line + headers within 15 s

        buf = [b'']

        async def rl():  # our own readline: never buffers more than ~2 KB per line
            while b'\n' not in buf[0]:
                if len(buf[0]) > 2048:
                    raise OSError('header too long')
                left = time.ticks_diff(dl, time.ticks_ms())
                if left <= 0:
                    raise OSError('slow request')
                c = await asyncio.wait_for(r.read(256), left / 1000)
                if not c:
                    ln, buf[0] = buf[0], b''
                    return ln
                buf[0] += c
            i = buf[0].index(b'\n') + 1
            if i > 2048:
                raise OSError('header too long')
            ln, buf[0] = buf[0][:i], buf[0][i:]
            return ln
        try:
            peer = w.get_extra_info('peername')[0]
        except Exception:
            peer = ''
        line = (await rl()).decode()
        method, path, _ = line.split(' ', 2)
        clen, auth = 0, ''
        for _ in range(40):
            h = await rl()
            if h in (b'\r\n', b'\n', b''):
                break
            hl = h.lower()
            if hl.startswith(b'content-length:'):
                clen = int(h.split(b':')[1])
                if clen < 0:
                    raise ValueError('bad length')
            elif hl.startswith(b'x-auth:'):
                auth = h.split(b':', 1)[1].strip().decode()
        path, q = parse_q(path)
        maint = bool(cfg.get('maint')) and q.get('t') == TOKEN
        if method == 'PUT' and path == '/file' and maint:
            # stream uploads straight to flash: big files don't fit in one read
            name = q.get('name', '')
            if not name or '/' in name or clen > free_bytes() - 60000:
                return await send(w, 400, '"bad name or not enough space"')
            try:
                got = await read_body_to(r, name + '.part', clen, buf[0])
                if got != clen:
                    return await send(w, 400, '"short upload %d/%d"' % (got, clen))
                os.rename(name + '.part', name)
            finally:
                rm(name + '.part')
            return await send(w, 200, '"wrote %d"' % got)
        if method == 'POST' and path in MUTATING and not authed(auth):
            return await send(w, 401, json.dumps({'auth': 'login' if cfg.get('pin') else 'setup'}))
        if method == 'POST' and path == '/api/hist':
            mac = q.get('mac', '').replace('%3A', ':').replace('%3a', ':').lower()
            if mac not in cfg['tanks'] or clen % 6:
                return await send(w, 400, '"bad history upload"')
            try:
                have = os.stat(hist_name(mac))[6]
            except OSError:
                have = 0
            # upload copy + merged copy (up to have + clen) + headroom for everything else
            if clen > 600000 or 2 * clen + have + 150000 > free_bytes():
                return await send(w, 413, '"history too large for the space left on the Pico"')
            if hist_busy[0]:  # one at a time: they share hist.up and the space check
                return await send(w, 409, '"another history upload is running"')
            hist_busy[0] = True
            try:
                got = await read_body_to(r, 'hist.up', clen, buf[0])
                if got != clen:
                    return await send(w, 400, '"short upload"')
                n = merge_hist(hist_name(mac), 'hist.up')
                last_saved.pop(mac, None)  # the file changed: read its newest reading again
                return await send(w, 200, json.dumps(n))
            finally:
                hist_busy[0] = False
                rm('hist.up')
                rm(hist_name(mac) + '.new')
        if clen > (16000 if path in ('/api/restore', '/api/delivery') else 4000):
            return await send(w, 413, '"too large"')
        body = b''
        if clen and method == 'POST':
            body = buf[0][:clen]
            if len(body) < clen:
                body += await asyncio.wait_for(r.readexactly(clen - len(body)), 20)

        if path in ('/', '/index.html'):
            return await send_file(w, 'ui.html', 'text/html; charset=utf-8')
        if path == '/api/state':
            return await send(w, 200, json.dumps(state()))
        if path == '/api/auth':
            return await send(w, 200, json.dumps({'pin_set': bool(cfg.get('pin')), 'ok': authed(auth)}))
        if path in ('/api/pin/login', '/api/pin/set', '/api/pin/logout') and method == 'POST':
            try:
                b = json.loads(body or '{}')
                if path == '/api/pin/login':
                    return await send(w, 200, json.dumps({'session': try_login(b.get('pin'))}))
                if path == '/api/pin/set':
                    if cfg.get('pin') and not authed(auth):
                        return await send(w, 401, json.dumps({'auth': 'login'}))
                    if not cfg.get('pin') and not may_set_first_pin(peer):
                        return await send(w, 403, json.dumps(
                            'for safety a first PIN can only be set within 30 minutes of the Pico starting, or from '
                            'its setup network. Unplug the Pico, plug it back in, then try again'))
                    tok = set_pin(b.get('pin'))
                    return await send(w, 200, json.dumps({'session': tok}))
                if authed(auth):
                    cfg['sessions'] = [x for x in cfg.get('sessions', []) if x != _sha(auth)]
                    save_cfg(cfg)
                return await send(w, 200, '"ok"')
            except Exception as ex:
                return await send(w, 400, json.dumps(str(ex)))
        if path == '/api/maint' and method == 'POST':
            cfg['maint'] = bool(json.loads(body or '{}').get('on'))
            save_cfg(cfg)
            return await send(w, 200, json.dumps(cfg['maint']))
        if path == '/api/hostname' and method == 'POST':
            try:
                cfg['hostname'] = ok_hostname(json.loads(body or '{}').get('hostname'))
            except Exception as ex:
                return await send(w, 400, json.dumps(str(ex)))
            save_cfg(cfg)
            await send(w, 200, '"ok"')
            await asyncio.sleep(1)
            machine.reset()
        if path in ('/api/notify', '/api/notify/test') and method == 'POST':
            try:
                b = json.loads(body or '{}')
                if path == '/api/notify':
                    set_notify(b)
                    return await send(w, 200, json.dumps(notify_view()))
                if not notify.channels(cfg.get('notify')):
                    raise ValueError('set up Pushover or ntfy first')
                res = await send_alert('Oil Monitor test', 'Notifications from %s are working.' % HOSTNAME)
                return await send(w, 200, json.dumps(res))
            except Exception as ex:
                return await send(w, 400, json.dumps(str(ex)))
        if path == '/api/location' and method == 'POST':
            try:
                set_location(json.loads(body or '{}'))
                return await send(w, 200, json.dumps(wx_view()))
            except Exception as ex:
                return await send(w, 400, json.dumps(str(ex)))
        if path == '/api/price' and method == 'POST':
            try:
                set_price(json.loads(body or '{}'))
                return await send(w, 200, json.dumps(price_view()))
            except Exception as ex:
                return await send(w, 400, json.dumps(str(ex)))
        if path == '/api/prices':
            try:
                return await send_file(w, price.HFILE if q.get('h') == '1' else price.FILE, 'application/octet-stream')
            except OSError:
                return await send(w, 200, b'', 'application/octet-stream')
        if path == '/api/weather':
            try:
                return await send_file(w, weather.FFILE if q.get('f') == '1' else weather.FILE, 'application/octet-stream')
            except OSError:
                return await send(w, 200, b'', 'application/octet-stream')
        if path == '/api/primary' and method == 'POST':
            mac = str(json.loads(body or '{}').get('mac', '')).lower()
            if mac not in cfg['tanks'] and not (mac == 'all' and len(cfg['tanks']) > 1):  # 'all' = both tanks together
                return await send(w, 400, '"unknown tank"')
            cfg['primary'] = mac
            save_cfg(cfg)
            return await send(w, 200, '"ok"')
        if path == '/api/tank' and method == 'POST':
            try:
                set_tank(json.loads(body))
            except Exception as ex:
                return await send(w, 400, json.dumps('Could not save: %s' % ex))
            return await send(w, 200, '"ok"')
        if path == '/api/update/check':
            try:
                import updater
                res = with_room(updater.check, VERSION)
                manifest[0] = res.pop('manifest')
            except Exception as ex:
                res = {'current': VERSION, 'error': str(ex) or repr(ex)}
            gc.collect()
            return await send(w, 200, json.dumps(res))
        if path == '/api/update/install' and method == 'POST':
            if installing[0]:
                return await send(w, 409, json.dumps('An update is already being installed'))
            installing[0] = True
            try:
                import updater
                m = manifest[0] or with_room(updater.check, VERSION)['manifest']
                if updater.vtuple(m['version']) <= updater.vtuple(VERSION):
                    installing[0] = False
                    return await send(w, 400, json.dumps('Already up to date'))
                make_room()
                v = updater.install(m, VERSION)
            except Exception as ex:
                gc.collect()
                installing[0] = False  # updater.install() undoes its own half-done swap
                return await send(w, 400, json.dumps('Update failed, nothing was changed: %s' % (str(ex) or repr(ex))))
            try:
                await send(w, 200, json.dumps(v))
            except Exception:
                pass  # the browser went away: restart onto the new version anyway
            await asyncio.sleep(1)
            machine.reset()
        if path == '/api/deliveries':
            try:
                return await send_file(w, 'deliv.json', 'application/json')
            except OSError:
                return await send(w, 200, '{}')
        if path in ('/api/delivery', '/api/restore') and method == 'POST':
            try:
                b = json.loads(body)
                res = set_delivery(b) if path == '/api/delivery' else restore(b)
            except Exception as ex:
                return await send(w, 400, json.dumps('Could not save: %s' % ex))
            return await send(w, 200, json.dumps(res if res is not None else 'ok'))
        if path == '/api/tank/delete' and method == 'POST':
            dm = str(json.loads(body).get('mac', '')).lower()
            cfg['tanks'].pop(dm, None)
            last_saved.pop(dm, None)
            save_cfg(cfg)
            return await send(w, 200, '"ok"')
        if path == '/api/wifi/scan':
            nets = {}
            for n in wlan.scan():
                s = n[0].decode('utf-8', 'replace')
                if s and (s not in nets or n[3] > nets[s]):
                    nets[s] = n[3]
            return await send(w, 200, json.dumps([{'ssid': s, 'rssi': v} for s, v in
                                                  sorted(nets.items(), key=lambda x: -x[1])]))
        if path == '/api/wifi' and method == 'POST':
            b = json.loads(body)
            if not b.get('ssid'):
                return await send(w, 400, '"Pick a network"')
            cfg['ssid'], cfg['pw'] = b['ssid'], b.get('pw', '')
            save_cfg(cfg)
            await send(w, 200, '"ok"')
            await asyncio.sleep(1)
            machine.reset()
        if path == '/api/discover':  # the Sensors nearby list is open: listen actively for a while
            discover(120)
            return await send(w, 200, '"ok"')
        if path == '/hawki':
            return await send(w, 200, hawki_json())
        if path == '/history':
            return await send_file(w, 'hist.html', 'text/html; charset=utf-8')
        if path == '/common.js':
            return await send_file(w, 'common.js.html', 'text/javascript; charset=utf-8')
        if path in ('/api/hist', '/api/curve'):
            mac = q.get('mac', '').replace('%3A', ':').replace('%3a', ':').lower()
            if mac not in cfg['tanks']:
                return await send(w, 404, '"unknown tank"')
            if path == '/api/curve':
                t = cfg['tanks'][mac]
                if q.get('tank_l'):  # a trial whole-tank capacity (the history page fits it to receipts)
                    try:
                        t = dict(t, tank_l=num(q['tank_l'], 1, 200000))
                    except ValueError:
                        return await send(w, 400, '"bad tank_l"')
                return await send(w, 200, json.dumps(curve(t)))
            try:
                return await send_file(w, hist_name(mac), 'application/octet-stream')
            except OSError:
                return await send(w, 200, b'', 'application/octet-stream')
        if path == '/devices':
            f, a = q.get('name', '').lower(), q.get('addr', '').lower()
            out = {k: v for k, v in seen.items()
                   if (not f or f in v['name'].lower()) and (not a or k.startswith(a))}
            return await send(w, 200, json.dumps({'uptime': time.ticks_diff(time.ticks_ms(), boot_ms) // 1000, 'now': time.time(),
                                                  'count': len(seen), 'mem': gc.mem_free(), 'devices': out}))
        if maint:
            if path == '/reset':
                seen.clear()
                return await send(w, 200, '"ok"')
            if path == '/reboot':
                await send(w, 200, '"rebooting"')
                await asyncio.sleep(0.5)
                machine.reset()
            if path == '/run':
                g = {'ble': ble, 'seen': seen, 'start_scan': start_scan, 'scan_on': scan_on,
                     'hook': hook, 'asyncio': asyncio}
                try:
                    exec(open(q['name']).read(), g)
                    res = json.dumps(await g['run'](q))
                except Exception as ex:
                    res = json.dumps({'error': repr(ex)})
                finally:
                    hook[0] = None
                    if not scan_on[0]:
                        scan_on[0] = True
                        start_scan()
                return await send(w, 200, res)
        await send(w, 404, '"not found"')
    except Exception as ex:
        print('http err', ex)
    finally:
        conns[0] -= 1
        try:
            w.close()
            await w.wait_closed()
        except Exception:
            pass
        gc.collect()


# ---------- outside temperature (Open-Meteo), to compare use with the weather ----------
wx_state = {'done': None, 'errs': {}, 'fat': 0, 'norm': None, 'norm_y': None}  # day the history was last
# brought up to date; the last error of each part; when the forecast was last fetched; the usual degree days
# for each month and the year they were worked out for (norm_y set once all 10 years are in)


def wx_err(part, ex):
    if ex is None:
        wx_state['errs'].pop(part, None)
    else:
        wx_state['errs'][part] = str(ex) or repr(ex)
        print('weather', part, ex)


def wx_view():
    w = cfg.get('wx') or {}
    e = wx_state['errs']
    return {'name': w.get('name'), 'lat': w.get('lat'), 'lon': w.get('lon'),
            'err': '; '.join('%s: %s' % (k, e[k]) for k in sorted(e)) or None, 'norm': wx_state['norm']}


def set_location(b):
    if b.get('clear'):
        cfg.pop('wx', None)
    else:
        name = ''.join(c for c in str(b.get('name') or '') if ' ' <= c and c != '\x7f')[:60]
        cfg['wx'] = {'lat': num(b.get('lat'), -90, 90), 'lon': num(b.get('lon'), -180, 180), 'name': name}
    for f in (weather.FILE, weather.FFILE, weather.NFILE):
        rm(f)  # a new place (or none): its history, forecast and usual weather are fetched afresh
    wx_state['done'] = None
    wx_state['errs'] = {}
    wx_state['fat'] = 0
    wx_state['norm'] = None
    wx_state['norm_y'] = None
    save_cfg(cfg)


def first_reading():
    # the oldest saved reading across the tanks (the weather is filled in back to here)
    best = None
    for mac in cfg['tanks']:
        try:
            with open(hist_name(mac), 'rb') as f:
                b = f.read(6)
            if len(b) == 6:
                t = struct.unpack('<IH', b)[0]
                best = t if best is None or t < best else best
        except OSError:
            pass
    return best


async def weather_task():
    # Three parts, each with its own error so one failing can't hold up the others:
    #  archive: once a day (and soon after a location is set), fill in any missing days back to the first
    #           reading and refresh the last 10 (recent figures settle). ~9 KB a year per request.
    #  forecast: every 6 hours, the next 16 days (they drive the start of the oil forecast).
    #  normals: the usual weather for each month, one full year a request, the last 10 years, once per place.
    for _ in range(18):  # the saved averages count as soon as the clock is set after a restart, not after
        w = cfg.get('wx')  # the first round of fetching
        if w and wx_state['norm'] is None and time.time() > 1.7e9:
            try:
                wx_state['norm'] = weather.norm_view(weather.norm_load(w['lat'], w['lon']), time.gmtime()[0])
            except Exception as ex:
                print('weather normals', ex)
                break
        await asyncio.sleep(5)
    while True:
        w = cfg.get('wx')
        now = time.time()
        today = weather.day_of(now)
        yr = time.gmtime(now)[0]
        ready = w and now > 1.7e9 and wlan.isconnected()
        if ready and wx_state['done'] != today:
            have = None
            try:
                have = weather.load()
                first = first_reading()
                d0 = weather.day_of(first) if first else today - 30
                todo = weather.plan(have, max(d0, today - 3650), today)
                for a, b in todo[:6]:  # at most 6 requests a go; the rest 10 minutes later
                    got = with_room(weather.fetch, w['lat'], w['lon'], a, b)
                    if cfg.get('wx') is not w:
                        break  # the location changed meanwhile: drop this
                    weather.fill(have, got, a, b)
                    weather.save(have)  # keep each batch, so an error later loses nothing
                    await asyncio.sleep(1)
                if cfg.get('wx') is w and len(todo) <= 6:
                    wx_state['done'] = today
                wx_err('archive', None)
            except Exception as ex:
                wx_err('archive', ex)
            have = got = None
            gc.collect()
        if ready and cfg.get('wx') is w and time.time() - wx_state['fat'] > 6 * 3600:
            try:
                got = with_room(weather.forecast, w['lat'], w['lon'])
                if cfg.get('wx') is w and got:
                    weather.save(got, weather.FFILE)
                    wx_state['fat'] = time.time()
                wx_err('forecast', None)
            except Exception as ex:
                wx_err('forecast', ex)
            got = None
            gc.collect()
        if ready and cfg.get('wx') is w and (wx_state['norm_y'] != yr or wx_state['norm'] is None):
            nm = None
            try:
                nm = weather.norm_load(w['lat'], w['lon'])
                wx_state['norm'] = weather.norm_view(nm, yr)  # what's saved counts now, even if a fetch fails
                for _ in range(2):
                    y = weather.norm_next(nm, yr)
                    if y is None:
                        break
                    got = with_room(weather.fetch, w['lat'], w['lon'], weather._day('%d-01-01' % y), weather._day('%d-12-31' % y))
                    if cfg.get('wx') is not w:
                        break
                    weather.norm_save(weather.norm_add(nm, y, got, yr))
                    await asyncio.sleep(1)
                if cfg.get('wx') is w:
                    wx_state['norm'] = weather.norm_view(nm, yr)  # re-worked each year, so old years drop out
                    if weather.norm_next(nm, yr) is None:
                        wx_state['norm_y'] = yr  # all 10 years in: nothing more until next year
                wx_err('normals', None)
            except Exception as ex:
                wx_err('normals', ex)
            nm = got = None
            gc.collect()
        await asyncio.sleep(600)


# ---------- oil prices (cheapestoil.co.uk, Northern Ireland) ----------
price_state = {'day': None, 'tried': 0, 'err': None, 'now': None, 'pc': None}  # day last fetched; when last tried;
# last error; the newest saved [day, cheapest, average]


def price_view():
    p = cfg.get('price')
    return {'on': p is not None, 'pc': p and p.get('pc'), 'now': price_state['now'], 'err': price_state['err']}


def set_price(b):
    if b.get('off'):
        cfg.pop('price', None)
    else:
        pc = price.ok_pc(b.get('pc'))
        cfg['price'] = {'pc': pc}
        if pc != price_state['pc']:  # a different area: fetch it (the saved history is kept); the same one
            price_state['day'] = None  # again keeps today's fetch, so saving never breaks the once-a-day limit
            price_state['tried'] = 0
    price_state['err'] = None
    save_cfg(cfg)


async def price_task():
    # once a day, after 09:00 UTC (their figures update early morning); a failure is retried after 30 minutes
    await asyncio.sleep(120)
    while True:
        try:
            now = time.time()
            today = weather.day_of(now)
            if price_state['now'] is None:
                d = price.load()
                if d:
                    last = max(d)
                    price_state['now'] = [last] + list(d[last] or (None, None))
                    if last == today:
                        price_state['day'] = today  # already fetched today (before a restart)
                        price_state['pc'] = (cfg.get('price') or {}).get('pc')
                d = None
            p = cfg.get('price')
            if (p is not None and now > 1.7e9 and wlan.isconnected() and price_state['day'] != today
                    and now - price_state['tried'] > 1800 and time.gmtime(now)[3] >= 9):
                price_state['tried'] = now
                try:
                    got = with_room(price.fetch, p['pc'])
                    if cfg.get('price') is p:
                        price.add(today, got)
                        price_state['day'] = today
                        price_state['now'] = [today, got[0], got[1]]
                        price_state['pc'] = p['pc']
                        price_state['err'] = None
                except Exception as ex:
                    price_state['err'] = str(ex) or repr(ex)
                    print('price err', ex)
                gc.collect()
        except Exception as ex:
            print('price task', ex)
        await asyncio.sleep(600)


async def main():
    asyncio.create_task(wifi_keeper())
    asyncio.create_task(recorder())
    asyncio.create_task(scan_scheduler())
    asyncio.create_task(alerts())
    asyncio.create_task(weather_task())
    asyncio.create_task(price_task())
    asyncio.create_task(update_guard())
    asyncio.create_task(bootsel_reset())
    asyncio.create_task(close_first_pin_window())
    await asyncio.start_server(handle, '0.0.0.0', 80)
    while True:
        await asyncio.sleep(60)
        gc.collect()


asyncio.run(main())
