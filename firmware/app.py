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
#   Forgot the PIN: hold the Pico's BOOTSEL button for 5 seconds while it's running (also returns a fixed
#   address to automatic).
# Maintenance (token, and only if switched on in Software settings - off by default):
#   PUT /file?name=x&t=TOK, GET /reboot?t=TOK, GET /run?name=x.py&t=TOK
# Debug: GET /devices[?name=&addr=] (signed in, or maintenance on + &t=TOK), GET /reset
#
# No Wi-Fi configured, or it can't connect for 60 s: the Pico also opens a setup network
# "HAWKi-Setup-XXXX" (password: oiltanks); browse to http://192.168.4.1/
import bluetooth, binascii, json, time, network, machine, asyncio, gc, os, struct
from hawki_decode import decode, mfr_from_adv
from tankcalc import reading, litres, litres_many, link, restore_groups, SHAPES, below, above, tank_equiv, total, whole
import histstore
from version import VERSION
from listen import Listener
import notify
import weather
import price
import netcfg
import unset
import mqtt
import drops

# HAWKi service UUID 00001923-1322-ffdd-3533-886fdadce133, as it appears in the advert (LE)
HAWKI_UUID = bytes(reversed(binascii.unhexlify('000019231322ffdd3533886fdadce133')))
AP_PASSWORD = 'oiltanks'
MEASURED_KEYS = ('outlet_cm', 'win_bottom_cm', 'win_top_cm', 'win_outer_w_cm', 'win_inner_w_cm',
                 'win_inner_h_cm', 'rib_h_cm', 'rib_depth_cm')
CFG_KEYS = ('shape', 'height_cm', 'length_cm', 'width_cm', 'capacity_l', 'tank_l', 'windows', 'window_model',
            'ribs_cm', 'reserve_l', 'unusable_l', 'group', 'isolated', 'mode') + MEASURED_KEYS


def load_json(name, bad):
    # A settings file as a dict. Only a MISSING file means none yet ({}). A read error is tried again and, if it
    # won't go away, raised (the file is left alone: saving over it would lose everything in it). Damaged
    # contents are kept as `bad`, then it starts afresh.
    for attempt in range(3):
        try:
            with open(name) as f:
                c = json.load(f)  # (streamed: no file-sized string in memory)
        except ValueError:
            c = None
        except (OSError, MemoryError) as ex:
            if isinstance(ex, OSError) and ex.args and ex.args[0] == 2:  # ENOENT
                return {}
            gc.collect()
            if attempt == 2:
                raise
            continue
        if isinstance(c, dict):
            return c
        print(name, 'is damaged: kept as', bad)
        try:
            os.remove(bad)
        except OSError:
            pass
        os.rename(name, bad)
        return {}


def load_cfg():
    # (a lasting read error stops the app here; main.py then starts the rescue server, config.json untouched)
    c = load_json('config.json', 'config.bad')
    c.setdefault('tanks', {})
    if not c.get('token'):
        c['token'] = binascii.hexlify(os.urandom(8)).decode()
        save_cfg(c)
    return c


cfg_gen = [0]  # counts settings saves (e.g. a changed shape or mode works the switch hint out again)


def save_cfg(c):
    cfg_gen[0] += 1
    with open('config.tmp', 'w') as f:
        json.dump(c, f)
    os.rename('config.tmp', 'config.json')


cfg = load_cfg()
TOKEN = cfg['token']
try:
    BOOT = (int(cfg.get('boots') or 0) + 1) & 0xffff  # which start this is (readings kept while the clock is unset)
except (TypeError, ValueError):
    BOOT = 1
cfg['boots'] = BOOT
save_cfg(cfg)
led = machine.Pin('LED', machine.Pin.OUT)
hawki = {}   # mac -> latest decoded reading
seen = {}    # mac -> BLE devices heard lately (debug + names); pruned, see prune_seen()
SEEN_MAX = 60
SEEN_AGE = 600  # forget other devices (phones change address every ~15 min) after 10 minutes
HAWKI_MAX = 8    # HAWKis that aren't set up as tanks (the Sensors nearby list): at most this many...
HAWKI_AGE = 900  # ...each forgotten 15 minutes after it was last heard (set-up tanks never are)


def prune_seen(all_others=False):
    # Long-lived little objects scattered through the heap chop it up, and a secure (TLS) connection
    # needs one big unbroken block of ~40 KB: keep this list short.
    now = time.time()
    for k in list(hawki):  # HAWKis that aren't tanks (a sensor nearby, or someone sending its id): not heard lately
        d = hawki.get(k)
        if d is not None and k not in cfg['tanks'] and now - d.get('rx', 0) > HAWKI_AGE:
            hawki.pop(k, None)
    old = now - SEEN_AGE
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
# Seconds since boot that never wrap. ticks_ms wraps every 12.4 days and ticks_diff of two values more than
# 6.2 days apart comes out negative, so no elapsed time may keep a ticks value for long: this adds up the short
# steps between calls instead (the Wi-Fi keeper and the scan scheduler call it every few seconds). Whole seconds
# stay a small int for 34 years (milliseconds would need a long int, so memory, after 12 days).
_mono = [0, 0, time.ticks_ms()]  # whole seconds, leftover ms, ticks at the last call


def mono_s():
    t = time.ticks_ms()
    ms = _mono[1] + time.ticks_diff(t, _mono[2])
    _mono[2] = t
    if ms > 0:  # (never backwards, even after a stall long enough to wrap)
        _mono[0] += ms // 1000
        _mono[1] = ms % 1000
    return _mono[0]


def boot_grace_over():
    return mono_s() > 60

# A fetch over HTTPS (weather, prices) holds up everything else for 1-3 s while it runs, so a page opened
# then sat waiting (10+ s after a restart, with several in a row). Background fetches wait until nobody has
# opened a page for a minute (polls of /api/state don't count: a late refresh isn't noticed).
LOADS = ('/', '/index.html', '/history', '/common.js', '/api/hist', '/api/curve', '/api/deliveries', '/api/weather', '/api/prices')
page_s = [None]  # mono_s() of the last page / chart data served


async def web_quiet(most=600):
    # wait (at most `most` seconds) until no page has loaded for 60 s
    t0 = time.ticks_ms()
    while page_s[0] is not None and time.ticks_diff(time.ticks_ms(), t0) < most * 1000:
        age = mono_s() - page_s[0]
        if not 0 <= age < 60:  # quiet
            page_s[0] = None
            break
        await asyncio.sleep(2)


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


def hawki_room():
    # make room for another HAWKi that isn't set up as a tank: when there are HAWKI_MAX already, the one heard
    # longest ago goes (a real sensor adverts every 4 s, so someone sending its id from many addresses can't
    # keep a new one out). Set-up tanks never count or go.
    n, old = len(hawki), None
    for t in cfg['tanks']:
        if t in hawki:
            n -= 1
    if n < HAWKI_MAX:
        return
    for k, d in hawki.items():
        if k not in cfg['tanks'] and (old is None or d.get('rx', 0) < hawki[old].get('rx', 0)):
            old = k
    if old is not None:
        hawki.pop(old, None)
        seen.pop(old, None)


def irq(ev, data):
    if ev == 5:  # _IRQ_SCAN_RESULT
        at, addr, adv_type, rssi, adv = data
        k = binascii.hexlify(bytes(addr), ':').decode()
        e = seen.get(k)
        if e is None:
            if (len(seen) >= SEEN_MAX and k not in cfg['tanks'] and k not in hawki
                    and not (adv_type == 0 and HAWKI_UUID in bytes(adv) and mfr_from_adv(adv))):
                return  # memory guard (a new HAWKi still gets in: hawki_room() below keeps that list short)
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
            if m and k not in hawki and k not in cfg['tanks']:
                hawki_room()
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
                if k in cfg['tanks'] and 'bad_level' not in d:
                    if time.time() < 1700000000:
                        if k in unset_raw and unset_raw[k] != d['raw'] and len(pending_unset) < 50:
                            pending_unset.append((k, time.ticks_ms(), d.get('timestamp') or 0, d['level']))  # (unset.py)
                        unset_raw[k] = d['raw']  # (the first one after a start may be one already saved: only a baseline)
                    elif k not in anchor:  # the first NEW measurement once the clock is set: it places earlier starts'
                        base = unset_raw.get(k) or anchor_base.setdefault(k, d['raw'])  # readings (never a repeat of
                        if d['raw'] != base:                                              # one from before the sync)
                            anchor[k] = (int(time.time()), d.get('timestamp') or 0)
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
pending_unset = []  # (mac, ticks_ms, sensor time, level) heard while the clock isn't set (unset.py)
unset_raw = {}      # mac -> payload last heard while the clock isn't set
clock_set_at = [None]  # epoch when the clock came back this start (the end of the gap)
gap_from = {}  # mac -> its last reading saved before the clock was lost (the start of the gap), fixed when it came back
clock_mono = [None]  # mono_s() at that moment: this start's readings are placed by that one mapping
anchor = {}       # mac -> (epoch, sensor time) of its first new measurement once the clock was set
anchor_base = {}  # mac -> payload when the clock was set, if none was heard before (an anchor must differ from it)
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
            mono_s()  # (keeps the never-wrapping clock counting even when nothing else asks it)
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

# ---------- fixed (static) address ----------
# cfg['net'] = {ip, mask, gw, dns} once proven; a new one is tried for one boot only (netcfg.py).
# Applied with wlan.ifconfig((..)) before joining: tested on the Pico 2 W to survive Wi-Fi drops and rejoins.
# (wifi_keeper is the ONLY thing that calls wlan.connect: a second connect on top of it knocked the Pico offline.)
net_trial = [netcfg.take_try()]   # settings on trial this boot (with their key 'k'), else None
net_ok_s = [None]                 # mono_s() of the last proof the network works: a request served over Wi-Fi (not
                                  # the setup network), the clock set from the internet, or the router answering
net_kept = [None]                 # key of the trial kept on this boot (so asking twice still says yes)
net_gen = [0]                     # counts address changes asked for: one that was overtaken while it waited gives way
net_restart = [False]             # an address change is decided and the restart is on its way: nothing else may start


def net_now():
    return net_trial[0] or cfg.get('net')


def net_apply():
    n = net_now()
    if n:
        try:
            if tuple(wlan.ifconfig()) != netcfg.tup(n):
                wlan.ifconfig(netcfg.tup(n))
            # MicroPython 1.29: ifconfig((..)) reports the DNS server but leaves the resolver unable to use it
            # (every name lookup then fails after 6 s, which also stalls this web server). Setting it again this
            # way makes it work; measured on the Pico 2 W.
            network.ipconfig(dns=n['dns'])
        except Exception as ex:
            print('net apply err', ex)


def net_view():
    n = net_now()
    ic = wlan.ifconfig() if wlan.isconnected() else None
    return {'static': bool(n), 'trial': bool(net_trial[0]), 'online': time.time() > 1700000000,  # (the clock is set from the internet)
            'ip': ic and ic[0], 'mask': ic and ic[1], 'gw': ic and ic[2], 'dns': ic and ic[3]}


async def answers(ip, port, secs=2):
    # Does a device answer at ip:port? Accepting OR refusing the connection both mean something is there; only
    # silence means no. Never blocks the other tasks. (Best effort: a device that ignores the port looks absent.)
    # A non-blocking connect, asked again every 100 ms. Measured on the Pico 2 W (MicroPython 1.29): first
    # EINPROGRESS (115); then EALREADY (114) for as long as nothing answers, EISCONN (106) once accepted, and
    # EBADF (9) once refused (the refusal tears the socket down).
    import socket
    s = None
    try:
        s = socket.socket()  # (inside the try: out of sockets is "no answer", never a dead Wi-Fi keeper)
        s.setblocking(False)
        try:
            s.connect((ip, port))
            return True
        except OSError as ex:
            if not ex.args or ex.args[0] != 115:
                return False  # no route to it at all
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < secs * 1000:
            await asyncio.sleep_ms(100)
            try:
                s.connect((ip, port))
                return True
            except OSError as ex:
                e = ex.args[0] if ex.args else 0
                if e != 114:
                    return e in (106, 9)
        return False
    except Exception:
        return False
    finally:
        if s is not None:
            s.close()


def net_proof():
    net_ok_s[0] = mono_s()


NET_QUIET_S = 15 * 60
net_asked = [0]  # mono_s() when the router was last asked (MicroPython functions can't carry attributes)


def net_quiet_s():
    # how long since anything showed the network works (from boot, if nothing has yet)
    return mono_s() - (net_ok_s[0] if net_ok_s[0] is not None else 0)


async def net_check():
    # A saved fixed address that reaches nothing (a new router, a changed network): joined, but for 15 minutes
    # no browser has got through, and the router doesn't answer. Then the setup network comes up, so the address
    # can be put right from a phone. Returns True while cut off. Asks the router at most every 5 minutes.
    if not cfg.get('net') or net_trial[0]:
        return False
    if net_quiet_s() > 5 * 60 and mono_s() - net_asked[0] > 5 * 60:
        net_asked[0] = mono_s()
        for port in (53, 80, 443):
            if await answers(cfg['net']['gw'], port):
                net_proof()
                break
    return net_quiet_s() > NET_QUIET_S



async def net_trial_guard():
    # a trial nobody confirmed: restart, which comes back with the settings from before (the trial file is gone)
    if not net_trial[0]:
        return
    await asyncio.sleep(netcfg.TRIAL_SECS)
    if net_trial[0]:
        print('fixed address not confirmed: going back')
        await asyncio.sleep(1)
        restart()
AP_NAME = 'HAWKi-Setup-' + hx(machine.unique_id())[-4:].upper()


# Each NTP try looks up a host name, which blocks everything else (for seconds when DNS is down). So while the
# clock can't be set, tries back off (10 s, 1 min, 5 min, then every 15 min) and skip while a page is loading;
# a success or a fresh Wi-Fi join starts again from 10 s.
NTP_BACKOFF = (10, 60, 300, 900)
ntp_wait = [0, 0]  # mono_s() of the next try, step in NTP_BACKOFF


def web_busy():
    return page_s[0] is not None and 0 <= mono_s() - page_s[0] < 60


def ntp_due():
    late = mono_s() - ntp_wait[0]
    return late >= 0 and (not web_busy() or late >= 300)  # (a page open for good can't put it off for ever)


async def ntp_sync():
    import ntptime
    for host in ('pool.ntp.org', 'time.google.com'):
        try:
            ntptime.host = host
            ntptime.settime()
            net_proof()
            ntp_wait[1] = 0
            return True
        except Exception as ex:
            print('ntp err', host, ex)
        await asyncio.sleep(0)
    ntp_wait[0] = mono_s() + NTP_BACKOFF[ntp_wait[1]]
    ntp_wait[1] = min(ntp_wait[1] + 1, len(NTP_BACKOFF) - 1)
    return False


def ap_on():
    if not ap.active():
        ap.config(essid=AP_NAME, password=AP_PASSWORD)
        ap.active(True)
        print('setup AP', AP_NAME)


async def wifi_keeper():
    wlan.active(True)
    wlan.config(pm=0xa11140)  # power-save off: steadier for BLE coexistence + HTTP
    net_apply()
    while True:
        mono_s()
        if cfg.get('ssid') and not wlan.isconnected():
            try:
                net_apply()
                wlan.connect(cfg['ssid'], cfg.get('pw', ''))
            except Exception as ex:
                print('wifi err', ex)
            for _ in range(20):
                if wlan.isconnected():
                    print('wifi ok', wlan.ifconfig())
                    ntp_wait[0] = ntp_wait[1] = 0  # (a fresh join: try straight away)
                    await ntp_sync()
                    break
                led.toggle()
                await asyncio.sleep(0.5)
        if wlan.isconnected():
            led.value(1)
            if await net_check():
                ap_on()
            elif ap.active():
                ap.active(False)
            if time.time() < 1700000000 and ntp_due():
                await ntp_sync()  # clock still unset; retry (backing off)
        else:
            led.value(0)
            if not cfg.get('ssid') or boot_grace_over():
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
        try:
            note_clock(now)  # (before any reading heard since the clock came back is saved: the gap is fixed first)
        except Exception as ex:
            print('unset err', ex)
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
        try:
            unset_step(now)
        except Exception as ex:
            print('unset err', ex)
        if now >= 1700000000 and (now // 3600) % 24 >= 3 and done_day != now // 86400:
            done_day = now // 86400
            await compact_all(now)


def save_pending():
    # write queued readings now, a planned restart is coming (the recorder only gets to them every 10 s, and after
    # the restart the same reading is only a baseline: that hour would be missing)
    while pending:
        mac, t, lvl = pending.pop(0)
        if t >= 1700000000 and mac in cfg['tanks']:
            try:
                with open(hist_name(mac), 'ab') as f:
                    f.write(struct.pack('<IH', t, lvl))
            except Exception as ex:
                print('hist err', ex)
    while pending_unset:
        mac, tk, sts, mm = pending_unset.pop(0)
        try:
            unset.add(mac, mono_s() - time.ticks_diff(time.ticks_ms(), tk) // 1000, sts, mm, BOOT)
        except Exception as ex:
            print('unset err', ex)


def restart():
    # every planned restart (not the watchdog's: the loop is stuck then)
    try:
        save_pending()
    except Exception as ex:
        print('save err', ex)
    machine.reset()


def note_clock(now):
    # the moment the clock is first set this start: the end of the gap, and its start for each tank (the last
    # reading saved before it was lost), fixed before anything else is saved or placed
    if now < 1700000000 or clock_set_at[0] is not None:
        return
    clock_set_at[0], clock_mono[0] = int(now), mono_s()
    for mac in cfg['tanks']:
        gap_from[mac] = max([t for t, mm in hist_tail(mac, 60) if t < clock_set_at[0]] or [0])


def unset_step(now):
    # readings heard while the clock wasn't set: keep them aside; once it is, place them in the gap (unset.py)
    while pending_unset:
        mac, tk, sts, mm = pending_unset.pop(0)
        unset.add(mac, mono_s() - time.ticks_diff(time.ticks_ms(), tk) // 1000, sts, mm, BOOT)
    if now < 1700000000 or clock_set_at[0] is None:
        return
    for mac in list(cfg['tanks']):
        recs = unset.records(mac)
        if not recs or hist_busy[0]:
            continue
        a = anchor.get(mac)
        if unset.needs_anchor(recs, BOOT) and a is None and now - clock_set_at[0] < 2 * 3600:
            continue  # (wait up to 2 hours for a new measurement to tell the sensor's clock from real time)
        placed = unset.place(recs, BOOT, clock_set_at[0], clock_mono[0], a, gap_from.get(mac, 0), clock_set_at[0])
        if placed:
            with open('u.up', 'wb') as f:
                for t, mm in placed:
                    f.write(struct.pack('<IH', t, mm))
            unset.clear(mac)  # (first: a power cut after this can lose them, but never add them twice)
            hist_busy[0] = True
            try:
                merge_hist(hist_name(mac), 'u.up')
            except ValueError as ex:  # (refused: dropped, rather than tried again every 10 s)
                print('unset merge refused', ex)
            finally:
                hist_busy[0] = False
                rm('u.up')
            last_saved.pop(mac, None)
        print('unset: %s placed %d of %d' % (mac, len(placed), len(recs)))
        unset.clear(mac)


def curve(t):
    H = float(t['height_cm']) * 10
    n = int(H // 10)
    out = [round(v, 1) for v in litres_many(t, [min(H, i * 10) for i in range(n + 1)])]
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


first_pin_until = [FIRST_PIN_SECS]  # mono_s(): a first PIN may be set until then (30 min after start or a BOOTSEL reset)


def on_ap(peer):
    # the request came in over the setup network (not the home Wi-Fi)
    return ap.active() and peer.startswith(ap.ifconfig()[0].rsplit('.', 1)[0] + '.')


def may_set_first_pin(peer):
    # Without a PIN, whoever sets one first owns the Pico. So a FIRST PIN can only be set from the
    # setup network (while it's actually up), or within 30 minutes of the Pico starting.
    return on_ap(peer) or mono_s() < first_pin_until[0]


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


def pin_reset():
    # forget the PIN and every session, and let a new PIN be set for the next 30 minutes (on automatic
    # addressing there's no restart, so the window from start-up would long have closed)
    for k in ('pin', 'pin_salt', 'sessions'):
        cfg.pop(k, None)
    first_pin_until[0] = mono_s() + FIRST_PIN_SECS
    lock.update(fails=0, wait=30, until=0)  # (wrong tries with the old PIN mustn't lock out the new one)
    save_cfg(cfg)


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
            was_fixed = bool(cfg.get('net')) or bool(net_trial[0])
            net_trial[0] = None  # (before anything waits: nothing on trial can be kept from here on)
            net_gen[0] += 1
            rm(netcfg.TRY)
            cfg.pop('net', None)
            pin_reset()
            print('PIN cleared by BOOTSEL')
            for _ in range(10):
                led.toggle()
                await asyncio.sleep(0.1)
            if was_fixed:  # and back to an automatic address (needs a restart)
                restart()


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
            '/api/update/install', '/api/maint', '/api/primary', '/api/hostname', '/api/notify', '/api/notify/test', '/api/location', '/api/price', '/api/net', '/api/mqtt')


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


def hist_tail(mac, n):
    # the newest n saved readings [(t, mm), ...]
    try:
        k = os.stat(hist_name(mac))[6] // 6
        with open(hist_name(mac), 'rb') as f:
            f.seek(max(0, k - n) * 6)
            raw = f.read()
        return [struct.unpack('<IH', raw[i:i + 6]) for i in range(0, len(raw) - 5, 6)]
    except Exception:
        return []


def fell_in_a_day(mac, t, now, since=0):
    # litres the tank went down over about the last day, counting only readings from `since` (when it went on
    # standby); median of 5 readings at each end (5 mm steps jitter, and one misread mustn't tip it). None without
    # a reading in the last 3 hours and 5 from 20+ hours before it
    recs = [r for r in hist_tail(mac, 60) if r[0] >= since]
    if len(recs) < 10 or now - recs[-1][0] > 3 * 3600:
        return None
    old = [r for r in recs if r[0] <= recs[-1][0] - 20 * 3600][-5:]
    if len(old) < 5:
        return None
    med = lambda rs: sorted(r[1] for r in rs)[2]
    a, b = reading(t, med(old))[0], reading(t, med(recs[-5:]))[0]
    return None if a is None or b is None else a - b


SWITCH_FELL_L = 8.0   # a standby tank down this much in a day...
SWITCH_STEADY_L = 3.0  # ...while the tank in use moved less than this (either way): the valves were probably switched
_hint = [None, None]  # (what it was worked out from, the hint)


def switch_hint(now):
    # "Looks like you've switched to Tank 2": only ever shown as a hint; the modes are the user's to change
    use = [m for m, t in cfg['tanks'].items() if mode_of(t) == 'use']
    sb = [m for m, t in cfg['tanks'].items() if mode_of(t) == 'standby']
    if len(use) != 1 or not sb:
        return None
    key = (now // 600, cfg_gen[0]) + tuple(saved_last(m) for m in use + sb)
    if _hint[0] != key:  # (every 10 minutes at most: a few hundred bytes read per tank)
        h = None
        try:  # (never let a hint break /api/state)
            u = fell_in_a_day(use[0], cfg['tanks'][use[0]], now)
            if u is not None and abs(u) < SWITCH_STEADY_L:
                fell = []
                for m in sb:
                    iso = cfg['tanks'][m].get('isolated')
                    f = fell_in_a_day(m, cfg['tanks'][m], now, iso if type(iso) is int else 0)
                    if f is not None and f >= SWITCH_FELL_L:
                        fell.append((m, f))
                if len(fell) == 1:  # (two standby tanks going down: can't tell which)
                    h = {'from': use[0], 'to': fell[0][0], 'fell': round(fell[0][1])}
        except Exception as ex:
            print('switch hint err', ex)
        _hint[0], _hint[1] = key, h
    return _hint[1]


# ---------- the order date, for Home Assistant ----------
# The forecast (seasons, weather, your own years) runs in the browser: too heavy for the Pico. Whenever the
# dashboard works it out it sends it here: from t0 (its last reading) the litres it expects to have been used by
# the end of each day after, for 400 days (running totals, so rounding never adds up). The Pico then steps from its
# own latest reading the same way the dashboard does (a day at a time until the reorder level), so with the same
# reading it gives the same date, and it keeps up as new readings come in between visits.
FC_FILE = 'fc.json'
forecasts = {}  # 'all' or a tank's mac -> {'t0', 'cur' (the dashboard's start level), 'cum': [...], 'at'}
fc_saved = [0]  # mono_s() of the last save (at most hourly: the dashboard sends every 10 minutes while open)


def load_forecasts():
    try:
        f = load_json(FC_FILE, FC_FILE + '.bad')
        forecasts.update({k: v for k, v in f.items() if isinstance(v, dict) and isinstance(v.get('cum'), list)})
    except Exception as ex:
        print('forecast load err', ex)


def set_forecast(b):
    key = str(b.get('mac', '')).lower()
    if key != 'all' and key not in cfg['tanks']:
        raise ValueError('unknown tank')
    now = time.time()
    t0 = int(b['t0'])  # (an int: single-precision floats would round it to 128 s)
    if now < 1700000000 or not now - 3 * 86400 <= t0 <= now + 3600:
        raise ValueError('bad time')
    cum = b.get('cum')
    if not isinstance(cum, list) or not 1 <= len(cum) <= 400:
        raise ValueError('bad forecast')
    cum = [num(x, 0, 1000000) for x in cum]
    if any(cum[i] < cum[i - 1] for i in range(1, len(cum))):
        raise ValueError('bad forecast')
    new = key not in forecasts
    # (the reorder level is never taken from the request: the Pico's own settings, so a made-up forecast from
    # someone on the Wi-Fi can't set it)
    forecasts[key] = {'t0': t0, 'cur': num(b['cur'], 0, 1000000), 'cum': cum, 'at': int(now)}
    if key == 'all':  # (which tanks it covers: switch one off or delete it, and it no longer applies)
        forecasts[key]['tanks'] = active_tanks()
    if new or mono_s() - fc_saved[0] > 3600:
        with open(FC_FILE + '.tmp', 'w') as f:
            json.dump(forecasts, f)
        os.rename(FC_FILE + '.tmp', FC_FILE)
        fc_saved[0] = mono_s()


def order_by(f, litres, at, reserve):
    # epoch of the day the oil reaches `reserve`, stepping like the dashboard from `litres` read at `at`; None
    # without a reading, or not within the 400 days the forecast covers
    if litres is None or at is None:
        return None
    cum, t0 = f['cum'], f['t0']
    if litres <= reserve:
        return int(at)
    j0 = max(0, int((at - t0) // 86400))  # (whole days since the dashboard's reading)
    if j0 >= len(cum):
        return None
    base = cum[j0 - 1] if j0 else 0.0
    for j in range(j0, len(cum)):
        if litres - (cum[j] - base) <= reserve:
            return int(at) + (j - j0 + 1) * 86400
    return None


REFILL_L = 30.0  # (as common.js: a rise bigger than this is a delivery)


_lvl = {}  # mac -> (what it was worked out from, result): read again only after a new reading or a settings save


def level_now(mac, t):
    # the start level the dashboard would use: median of the last 3 saved readings, none from before a delivery
    # (with fewer than 3 since one, the newest); and the newest reading's time
    key = (saved_last(mac), cfg_gen[0])
    c = _lvl.get(mac)
    if c is None or c[0] != key:
        c = _lvl[mac] = (key, _level_now(mac, t))
    return c[1]


def _level_now(mac, t):
    ls = [(ts, reading(t, mm)[0]) for ts, mm in hist_tail(mac, 4)]
    ls = [x for x in ls if x[1] is not None]
    if not ls:
        return None, None
    for i in range(len(ls) - 1, 0, -1):
        if ls[i][1] - ls[i - 1][1] > REFILL_L:
            ls = ls[i:]
            break
    v = [x[1] for x in ls]
    return (v[-1] if len(v) < 3 else sorted(v[-3:])[1]), ls[-1][0]


def active_tanks():
    return sorted(m for m, t2 in cfg['tanks'].items() if mode_of(t2) != 'off')


def order_by_iso(mac, t, v=None):
    # the order date for a tank's Home Assistant sensor: the newest of its own forecast and (a tank in use) the
    # all-tanks one; none for an off tank
    if mode_of(t) == 'off':
        return None
    own, al = forecasts.get(mac), forecasts.get('all') if mode_of(t) == 'use' else None
    if al and al.get('tanks') != active_tanks():
        al = None  # (made for another set of tanks: the dashboard sends a new one next time it's open)
    f, key = (al, 'all') if al and (not own or al['at'] > own['at']) else (own, mac)
    if not f:
        return None
    macs = [mac] if key == mac else [m for m, t2 in cfg['tanks'].items() if mode_of(t2) != 'off']
    lit, last = 0.0, 0
    for m in macs:
        c, ts = level_now(m, cfg['tanks'][m])
        if c is None:
            return None
        lit, last = lit + c, max(last, ts)
    if last <= f['t0']:  # nothing newer than the reading the dashboard used: its own start level, exactly
        lit, last = f['cur'], f['t0']
    reserve = reserve_of(t) if key == mac else max(reserve_of(cfg['tanks'][m]) for m in macs)
    e = order_by(f, lit, last, reserve)
    if e is None:
        return None
    y, mo, d, h, mi, s = time.gmtime(e)[:6]
    return '%04d-%02d-%02dT%02d:%02d:%02d+00:00' % (y, mo, d, h, mi, s)


_tm = {}  # mac -> ((level, settings saved count), results): /api/state and MQTT (every 10 s) ask far more often


def tank_maths(mac, t, lvl):
    # litres, %, all the oil, the standard model's figures and the unusable part for this level: they only change
    # with the level or the settings (every settings change goes through save_cfg, which counts cfg_gen)
    key = (lvl, cfg_gen[0])
    c = _tm.get(mac)
    if c is not None and c[0] == key:
        return c[1]
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
    r = (lit, pct, tot, std, tot_std, unusable(t))
    _tm[mac] = (key, r)
    return r


def tank_view(mac, t, now):
    d = hawki.get(mac) or {}
    lvl = d.get('level')
    if lvl in (None, 16383):  # nothing heard yet since a restart, or only a misread: the last saved reading,
        s = saved_last(mac)   # with its own time (so it's never passed off as fresh, and alerts don't use it)
        if s and 1700000000 < now and s[0] <= now + 60:  # (not one dated ahead of a clock that was put back)
            d = dict(d, good_at=s[0], bad_level=d.get('bad_level')) if 'bad_level' in d else dict(d, good_at=s[0], saved=True)
            lvl = s[1]
    lit, pct, tot, std, tot_std, un = tank_maths(mac, t, lvl)
    r1 = lambda v: None if v is None else round(v, 1)
    try:
        ob = order_by_iso(mac, t)
    except Exception:  # (never let it break /api/state)
        ob = None
    return {'mac': mac, 'name': t.get('name', mac), 'level': lvl, 'litres': lit, 'percent': pct, 'order_by': ob,
            # misread: the rejected reading (-1: no level at all), or None
            'misread': (-1 if d['bad_level'] is None else d['bad_level']) if 'bad_level' in d else None, 'good_at': d.get('good_at'), 'saved': bool(d.get('saved')), 'litres_standard': std, 'total': r1(tot), 'total_standard': r1(tot_std), 'unusable': list(un) if un else un, 'listen': listener.info(mac),
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


alert_back = [0, 0]  # after a send where every channel failed: mono_s() of the next try, and the wait


async def send_alert(title, msg, urgent=False, force=False):
    # a failed send is tried again by the caller every 5 minutes; while the internet is down each try blocks the
    # Pico on DNS and TLS for nothing, so after a failure wait 5 minutes, doubling to 30 (the test button: always)
    if not (force or urgent) and mono_s() < alert_back[0]:  # (urgent: a sudden drop is only checked on new readings, so never held)
        return {'held': 'waiting after a failed send'}
    await asyncio.sleep(0)
    make_room()
    res = notify.send(cfg.get('notify'), title, msg, urgent)  # blocks ~1-2 s per channel (TLS)
    print('notify', title, res)
    if 'ok' in res.values():
        alert_back[0] = alert_back[1] = 0
    elif res:
        alert_back[1] = min(1800, max(300, alert_back[1] * 2))
        alert_back[0] = mono_s() + alert_back[1]
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
    if tank is None or mode_of(tank) == 'off':  # (off: not watched)
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
    try:  # the tank's litres in a 5 mm step, on average: on a big tank one ordinary step is more than 15 L
        slack = max(drops.SLACK, 2.5 * above(tank) / (float(tank['height_cm']) * 10) * 5)
    except Exception:
        slack = drops.SLACK
    hit = drops.check([(ts, reading(tank, mm)[0]) for ts, mm in r], float(n.get('burner_lph', 6)), slack)  # current shape
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


low_seen = {}  # mac -> [payload of the last reading counted, low readings in a row, when it first read low]


def low_confirmed(mac, raw, low, now):
    # two hourly readings in a row at or below the reorder level before warning (like the battery and drop checks:
    # one bad reading mustn't send "time to order oil"); the same reading repeats every 4 s and counts once. Or low
    # for 70 minutes on end (a sensor whose payload stopped changing). Not low now: starts again (a changed reorder
    # level or tank shape counts at once).
    e = low_seen.setdefault(mac, [None, 0, None])
    if not low:
        e[0], e[1], e[2] = raw, 0, None
        return False
    if raw != e[0]:
        e[0], e[1] = raw, e[1] + 1
    if e[2] is None:
        e[2] = now
    return e[1] >= 2 or now - e[2] >= 70 * 60


def mode_of(t):
    m = t.get('mode')
    return m if m in MODES else 'standby' if t.get('isolated') else 'use'


def reserve_of(t):
    return float(t['reserve_l']) if t.get('reserve_l') is not None else 200.0


def reorder_alert(mac, t, lit):
    # (title, message) for an in-use tank at its reorder level: switch to a standby tank that still has oil above
    # its own reorder level (the fullest), or order oil when there is none
    name, reserve, spare = t.get('name', mac), reserve_of(t), None
    for m2, t2 in cfg['tanks'].items():
        if m2 == mac or mode_of(t2) != 'standby':
            continue
        d2 = hawki.get(m2) or {}
        if d2.get('level') in (None, 16383) or 'bad_level' in d2 or time.time() - d2.get('rx', 0) > 3 * 3600:
            continue  # (no fresh, good reading: can't say it has oil)
        l2 = reading(t2, d2['level'])[0]
        if l2 is not None and l2 > reserve_of(t2) and (spare is None or l2 > spare[1]):
            spare = (t2.get('name', m2), l2)
    if spare:
        return ('%s is low - switch to %s' % (name, spare[0]),
                '%d L left in %s. %s has %d L ready.' % (lit, name, spare[0], spare[1]))
    return ('%s: time to order oil' % name, '%d L left, at or below your reorder level of %d L.' % (lit, reserve))


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
                    if mode_of(t) == 'off':
                        continue  # off: no warnings at all, not even about its monitor
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
                    reserve = reserve_of(t)
                    low2 = low_confirmed(mac, d.get('raw'), lit <= reserve, time.time())
                    if a.get('reorder') and lit >= reserve + REARM_L:
                        a.pop('reorder')  # topped up (in any mode): arm it again
                        save_cfg(cfg)
                    elif mode_of(t) == 'use' and n.get('reorder', True) and not a.get('reorder') and lit <= reserve and low2:  # (standby: no warning of its own)
                        res = await send_alert(*reorder_alert(mac, t, lit))
                        if 'ok' in res.values():
                            a['reorder'] = int(time.time())
                            save_cfg(cfg)
        except Exception as ex:
            print('alerts err', ex)
        await asyncio.sleep(300)


UPD_CACHE_S = 600
upd_cache = [None, None]  # the last check's answer (good or not) and mono_s() when


def update_check(fresh):
    # Checking means a blocking HTTPS fetch (seconds, ~40 KB): answered from the last 10 minutes unless the signed-in
    # owner asks (fresh), and even then not more than every 10 s; a failure is remembered too
    age = None if upd_cache[1] is None else mono_s() - upd_cache[1]
    if age is not None and (age < 10 or not fresh and age < UPD_CACHE_S):
        return dict(upd_cache[0], age=age)  # (the page says how long ago it was checked)
    try:
        import updater
        res = with_room(updater.check, VERSION)
        manifest[0] = res.pop('manifest')
    except Exception as ex:
        manifest[0] = None
        res = {'current': VERSION, 'error': str(ex) or repr(ex)}
    gc.collect()
    upd_cache[0], upd_cache[1] = res, mono_s()
    return dict(res, age=0)


def manifest_fresh():
    # Install uses the release the last check found, if that check is under 10 minutes old; else it checks again
    return manifest[0] is not None and upd_cache[1] is not None and mono_s() - upd_cache[1] < UPD_CACHE_S


def may_setup(auth, peer):
    # slow or revealing requests: signed in, or setting up (no PIN yet, or over the setup network)
    return authed(auth) or not cfg.get('pin') or on_ap(peer)


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


class _Req:  # a request handed straight to handle(), no network (the update self-check)
    def __init__(self, data):
        self.d = data

    async def read(self, n):
        b, self.d = self.d[:n], self.d[n:]
        return b


class _Resp:  # ...and its answer: the headers kept, the rest only counted
    def __init__(self):
        self.head, self.n = b'', 0

    def get_extra_info(self, k):
        return ('127.0.0.1', 0)

    def write(self, b):
        self.n += len(b)
        if len(self.head) < 400:
            self.head += bytes(b[:400])

    def complete(self):
        # a 200 whose body is all there (Content-Length): a page cut off part-way doesn't count
        i = self.head.find(b'\r\n\r\n')
        if not self.head.startswith(b'HTTP/1.0 200') or i < 0:
            return False
        for ln in self.head[:i].split(b'\r\n'):
            if ln.lower().startswith(b'content-length:'):
                return self.n - i - 4 == int(ln.split(b':')[1].decode().strip()) > 100
        return False

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


async def web_ok(secs=30):
    # Does the web side of this version work? The state API and the main page, through the real handle()
    # (the Pico can't connect to itself over the network: tested on the Pico 2 W, both its own address and
    # 127.0.0.1 fail). Measured there: both answer 200 in under 0.2 s.
    for path in ('/api/state', '/'):
        w = _Resp()
        await asyncio.wait_for(handle(_Req(('GET %s HTTP/1.0\r\n\r\n' % path).encode()), w), max(1, secs))
        if not w.complete():
            return False
    return True


async def update_guard():
    # Confirm a fresh update once it has run for 2 minutes with Wi-Fi up (or no Wi-Fi set up yet) AND its web
    # pages work: a version that imports and joins the Wi-Fi but whose page is broken could never be updated again
    # from that page. Otherwise, after 10 minutes, put the old version back.
    if not update_info()['pending']:
        try:  # a power cut during a download leaves its .new files (only load the updater if there are any)
            if any(n.endswith('.new') or n == 'upd.tmp' for n in os.listdir()):
                import updater
                updater.tidy()
        except Exception as ex:
            print('tidy err', ex)
        return
    import updater
    why, t0 = 'no Wi-Fi after the update', mono_s()
    while mono_s() - t0 < 600:  # (10 minutes by the clock: slow checks can't stretch it)
        await asyncio.sleep(10)
        if mono_s() - t0 >= 120 and (wlan.isconnected() or not cfg.get('ssid')):
            try:
                good = await web_ok(min(30, 600 - (mono_s() - t0)))
            except Exception as ex:
                print('web check err', repr(ex))
                good = False
            if good:
                print('update confirmed', updater.commit())
                return
            why = 'the web page of the new version is not working'
    import rollback
    if rollback.undo(why):  # (not finished: the journal stays and the next boot tries again;
        restart()     # restarting now would only loop)


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
    return {'tanks': tanks, 'found': found, 'switch': switch_hint(now),
            'ssid': cfg.get('ssid') if wlan.isconnected() else None,
            'ip': wlan.ifconfig()[0] if wlan.isconnected() else None,
            'wifi_rssi': wlan.status('rssi') if wlan.isconnected() else None,
            'ap': AP_NAME if ap.active() else None, 'update': update_info(),
            'pin_set': bool(cfg.get('pin')), 'maint': bool(cfg.get('maint')),
            'primary': cfg.get('primary') if cfg.get('primary') in cfg['tanks'] or cfg.get('primary') == 'all' and len(tanks) > 1
                       else (tanks[0]['mac'] if tanks else None),
            'hostname': HOSTNAME, 'net': net_view(), 'scan': scan_mode[0], 'notify': notify_view(), 'wx': wx_view(), 'price': price_view(), 'mqtt': mqtt_view(), 'mac': ':'.join('%02x' % c for c in wlan.config('mac'))}


def num(v, lo, hi):
    v = float(v)
    if not (lo <= v <= hi):
        raise ValueError('out of range')
    return v


MODES = ('use', 'standby', 'off')


def isolated_since(new, old):
    # When the valve was closed (epoch), so only readings after it are held: marking a tank isolated today must
    # not rewrite the use it had before. The form sends true; a backup sends the time. True = since ever (older
    # settings, or the clock not set yet).
    now = time.time()
    clock = now >= 1700000000  # (not set yet just after boot: then it can't say a time is in the future)
    for v in (new, old):
        if type(v) is int and 1500000000 <= v and (not clock or v <= now + 86400):
            return v
    return int(now) if clock else True


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
    # In use (no 'mode'): counted, warns. Standby (valve shut, oil waiting): its oil counts in the total, its readings
    # from 'isolated' (when it stopped being in use) never count as use, no reorder warning of its own. Off (empty, or
    # just not wanted): left out of totals, forecasts and warnings; its readings are still saved. (Older settings:
    # 'isolated' without a mode = standby.)
    old = cfg['tanks'].get(mac) or {}
    mode = b.get('mode') or (('off' if old.get('mode') == 'off' else 'standby') if b.get('isolated') else 'use')
    if mode not in MODES:  # (a form without modes ticks Isolated for an off tank too: it stays off)
        raise ValueError('bad mode')
    if mode != 'use':
        t['mode'] = mode
        t['isolated'] = isolated_since(b.get('isolated'), old.get('isolated'))
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
    if not restore:  # (a backup is taken as it was saved: refusing it would refuse the whole import)
        check_shape(t)
    link(cfg['tanks'], mac, t, b, restore)
    if not restore:
        save_cfg(cfg)


def check_shape(t):
    # Each setting is checked on its own range, but some combinations break the model so the litres go DOWN as the
    # oil rises (window widths typed in mm, a capacity far below the box's size): refuse those
    shapes = [t]
    if t.get('tank_l') not in (None, ''):  # and the whole tank, floor to monitor (the part below the outlet too)
        shapes.append(whole(t))
    for s in shapes:
        H, low = int(float(s['height_cm']) * 10), None
        for x in litres_many(s, range(0, H + 1, 5)):  # distance from the monitor: 0 = full, so litres only go down
            if x is None:
                continue
            if low is not None and x > low + 0.5:  # (against the lowest so far: small steps up add up)
                if t.get('window_model') == 'measured':
                    raise ValueError('with these window sizes the oil would go down as it rises: check they are in cm')
                raise ValueError('with this capacity the oil would go down as it rises: check the capacity and the sizes')
            low = x if low is None else min(low, x)


# ---------- deliveries (supplier + price per fill) ----------

def load_deliv():
    return load_json('deliv.json', 'deliv.bad')  # (a read error raises: the caller's save must not go ahead)


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


def restore_deliveries(dl, known):
    # {mac: [records]} from a backup, every record checked before anything is saved
    out = {}
    for mac, lst in (dl or {}).items():
        mac = str(mac).lower()
        if mac not in known:
            raise ValueError('deliveries for a tank that is not set up: %s' % mac)
        if not isinstance(lst, list):
            raise ValueError('bad deliveries for %s' % mac)
        out[mac] = [clean_delivery(x) for x in lst]
    return out


STAGE = 'deliv.stage'  # a backup's deliveries, sent in batches, held here until the import's final request


def restore(b):
    # Settings + deliveries from a backup, all or nothing. A tank's 200 receipts don't fit one request, so the
    # page first sends deliveries in batches ('part': 'first' starts, 'more' adds) which only go into STAGE (each
    # checked as it comes); then the settings with 'staged': true, and only then is anything replaced: settings
    # and every staged tank's deliveries together, after all of it has been checked. A failed batch changes nothing.
    d = load_deliv()  # (a read error stops here, before anything changed)
    imp = str(b.get('import') or '')[:40]  # which import the batches belong to (two at once must not mix)
    if b.get('part') in ('first', 'more'):
        st = {'id': imp, 'd': {}} if b['part'] == 'first' else load_json(STAGE, STAGE + '.bad')
        if st.get('id') != imp:
            raise ValueError('another import is running: try again in a minute')
        n = 0
        for mac, lst in (b.get('deliveries') or {}).items():
            if not isinstance(lst, list):
                raise ValueError('bad deliveries for %s' % mac)
            st['d'].setdefault(str(mac).lower(), []).extend(clean_delivery(x) for x in lst)
            n += len(lst)
        with open(STAGE + '.tmp', 'w') as f:
            json.dump(st, f)
        os.rename(STAGE + '.tmp', STAGE)
        return n
    tanks = restore_groups(cfg['tanks'], {str(k).lower(): v for k, v in (b.get('tanks') or {}).items()})
    dl = {str(k).lower(): v for k, v in (b.get('deliveries') or {}).items()}
    if b.get('staged'):
        st = load_json(STAGE, STAGE + '.bad')
        if st.get('id') != imp:
            raise ValueError('another import is running: try again in a minute')
        dl.update(st.get('d') or {})
    new = restore_deliveries(dl, set(cfg['tanks']) | set(tanks))
    was = json.dumps(cfg['tanks'])
    try:
        for mac, t in tanks.items():
            set_tank(dict(t, mac=mac), restore=True)
    except Exception:  # a bad tank in the backup leaves the settings as they were
        cfg['tanks'] = json.loads(was)
        raise
    save_cfg(cfg)
    for mac, lst in new.items():
        d[mac] = sorted({x['t']: x for x in lst}.values(), key=lambda x: x['t'])[-200:]  # (one per time: the last)
    save_deliv(d)
    rm(STAGE)
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
    n, last, prev_b = 0, -1, 0
    hi = time.time() + 2 * 86400 if time.time() > 1700000000 else 4000000000
    try:
        with open(tmp, 'rb') as b, open(name + '.new', 'wb') as o:
            ra, rb = nxt(a), nxt(b)
            while ra or rb:
                if rb is None or (ra is not None and ra[0] <= rb[0]):
                    r, ra = ra, nxt(a)
                else:
                    r, rb = rb, nxt(b)
                    if not (1500000000 <= r[0] <= hi and r[0] >= prev_b):  # (the upload: sorted, sane times)
                        raise ValueError('the uploaded history is out of order or has a bad time')
                    prev_b = r[0]
                if r[0] != last and r[1] not in (16383, 0xffff):  # skip 'unknown level' readings
                    o.write(struct.pack('<IH', r[0], r[1]))
                    last, n = r[0], n + 1
    except Exception:
        try:
            os.remove(name + '.new')
        except OSError:
            pass
        raise
    finally:
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


async def send_file(w, name, ctype, cache='no-store', etag=None):
    size = os.stat(name)[6]
    w.write(('HTTP/1.0 200 OK\r\nContent-Type: %s\r\nContent-Length: %d\r\nCache-Control: %s\r\n%sConnection: close\r\n\r\n'
             % (ctype, size, cache, 'ETag: %s\r\n' % etag if etag else '')).encode())
    with open(name, 'rb') as f:
        while True:
            chunk = f.read(1024)
            if not chunk:
                break
            w.write(chunk)
            await asyncio.wait_for(w.drain(), 20)


async def send_page(w, name, ctype, inm=''):
    # the pages and common.js only change with an update: the browser keeps its copy and asks each time
    # (no-cache + ETag), and gets a tiny 304 instead of up to 87 KB over weak Wi-Fi when nothing changed
    st = os.stat(name)  # (version, size and modified time: a file put on by maintenance, or swapped in by an update
    tag = '"%s-%d-%d"' % (VERSION, st[6], st[8])  # before the restart, gets a new tag; littlefs keeps mtimes, checked on the Pico)
    if inm and (tag in inm or inm.strip() == '*'):  # (a W/ weak tag or a list of them match too)
        w.write(('HTTP/1.0 304 Not Modified\r\nETag: %s\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n' % tag).encode())
        await asyncio.wait_for(w.drain(), 20)
        return
    await send_file(w, name, ctype, 'no-cache', tag)


class BadRequest(Exception):
    pass


def jb(body):
    # a request's JSON object, or a 400 (not a dropped connection) when it isn't one
    try:
        b = json.loads(body or '{}')
    except ValueError:
        raise BadRequest('not JSON')
    if not isinstance(b, dict):
        raise BadRequest('not a JSON object')
    return b


conns = [0]
installing = [False]
hist_busy = [False]


async def handle(r, w):
    conns[0] += 1
    me = isinstance(w, _Resp)  # the Pico checking its own pages after an update (web_ok): no side effects
    try:
        if conns[0] > 6 and not me:  # don't let a pile of idle connections starve the Pico
            return
        dl = time.ticks_add(time.ticks_ms(), 15000)  # the whole request line + headers within 15 s

        buf = [b'']

        skip, got = [None], [0]

        async def rl():  # our own readline: never buffers more than ~2 KB per line
            while b'\n' not in buf[0]:
                if len(buf[0]) > 2048:  # an over-long line (a big Cookie: from other sites on the same host name)
                    if skip[0] is None:  # is dropped, not the whole request; but never one of the headers read below
                        skip[0] = buf[0][:16].lower()
                    buf[0] = b''
                left = time.ticks_diff(dl, time.ticks_ms())
                if left <= 0:
                    raise OSError('slow request')
                c = await asyncio.wait_for(r.read(256), left / 1000)
                if not c:
                    ln, buf[0] = buf[0], b''
                    return ln
                got[0] += len(c)
                if got[0] > 16384:  # (the request line and headers, all of them, however they arrive)
                    raise OSError('headers too long')
                buf[0] += c
            i = buf[0].index(b'\n') + 1
            ln, buf[0] = buf[0][:i], buf[0][i:]
            if skip[0] is not None or i > 2048:
                hd, skip[0] = skip[0] if skip[0] is not None else ln[:16].lower(), None
                if hd.startswith((b'content-length', b'x-auth', b'if-none-match')):
                    raise OSError('header too long')  # (dropping one of these would change what the request does)
                return b'X-Dropped: 1\r\n'  # (a header nobody reads)
            return ln
        try:
            peer = w.get_extra_info('peername')[0]
        except Exception:
            peer = ''
        line = (await rl()).decode()
        method, path, _ = line.split(' ', 2)
        clen, auth, inm = 0, '', ''
        for _ in range(100):
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
            elif hl.startswith(b'if-none-match:'):
                inm = h.split(b':', 1)[1].strip().decode()
        else:  # (no blank line after 100: never take headers for the body)
            return await send(w, 431, '"too many headers"')
        path, q = parse_q(path)
        if peer and not on_ap(peer) and not me:
            net_proof()
        if path in LOADS and not me:
            page_s[0] = mono_s()
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
                wd_hold[0] += 1
                try:
                    n = merge_hist(hist_name(mac), 'hist.up')
                finally:
                    wd_hold[0] -= 1
                last_saved.pop(mac, None)  # the file changed: read its newest reading again
                return await send(w, 200, json.dumps(n))
            finally:
                hist_busy[0] = False
                rm('hist.up')
                rm(hist_name(mac) + '.new')
        if clen > (16000 if path in ('/api/restore', '/api/delivery') else 8000 if path == '/api/forecast' else 4000):
            return await send(w, 413, '"too large"')
        body = b''
        if clen and method == 'POST':
            body = buf[0][:clen]
            if len(body) < clen:
                body += await asyncio.wait_for(r.readexactly(clen - len(body)), 20)

        if path in ('/', '/index.html'):
            return await send_page(w, 'ui.html', 'text/html; charset=utf-8', inm)
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
            cfg['maint'] = bool(jb(body).get('on'))
            save_cfg(cfg)
            return await send(w, 200, json.dumps(cfg['maint']))
        if path == '/api/net' and method == 'POST':
            try:
                b = json.loads(body or '{}')
                net_gen[0] += 1
                gen = net_gen[0]

                def clear_to_go():  # (asked again after every wait below)
                    if net_restart[0] or installing[0]:
                        raise ValueError('the Pico is about to restart: try again in a minute')
                    if update_info()['pending']:  # restarts now would count against the new version
                        raise ValueError('an update is still settling in: try again in a couple of minutes')
                    if gen != net_gen[0]:
                        raise ValueError('another address change was made meanwhile')
                clear_to_go()
                if not b.get('static'):  # automatic again: always works, so no trial
                    net_trial[0] = None  # (and nothing on trial can be kept from here on)
                    rm(netcfg.TRY)
                    cfg.pop('net', None)
                    save_cfg(cfg)
                    out = {'static': False}
                else:
                    if not wlan.isconnected():
                        raise ValueError('join the Wi-Fi first, then fix the address')
                    n = netcfg.clean(b)
                    if n['ip'] != wlan.ifconfig()[0] and (await answers(n['ip'], 80, 1.5) or await answers(n['ip'], 443, 1.5)):
                        raise ValueError('address: another device is already using ' + n['ip'])
                    clear_to_go()
                    key = binascii.hexlify(os.urandom(8)).decode()
                    net_trial[0] = None  # a trial already running is over: this one replaces it
                    netcfg.write_try(n, key)
                    out = {'static': True, 'ip': n['ip'], 'net': n, 'k': key, 'secs': netcfg.TRIAL_SECS}
            except Exception as ex:
                return await send(w, 400, json.dumps(str(ex)))
            net_gen[0] += 1  # decided: nothing else may change the address (or start an update) before the restart
            net_restart[0] = True
            try:
                await send(w, 200, json.dumps(out))
                await asyncio.sleep(1)
            finally:
                restart()  # decided: restart even if the browser has gone away
        if path == '/api/net/keep' and method == 'POST':
            # the browser reached the Pico at the address on trial: keep it. (No PIN: the one-time key from the
            # signed-in request that started the trial is the proof, and a new address is a new site to the browser.)
            t = net_trial[0]
            cors = 'application/json\r\nAccess-Control-Allow-Origin: *'  # the page asking is still on the old address
            if (t and q.get('k') == t['k'] and not on_ap(peer) and wlan.isconnected()
                    and tuple(wlan.ifconfig()) == netcfg.tup(t)):  # (really running on those settings)
                cfg['net'] = {k: t[k] for k in ('ip', 'mask', 'gw', 'dns')}
                save_cfg(cfg)
                net_trial[0] = None
                net_kept[0] = t['k']
                return await send(w, 200, '"ok"', cors)
            if net_kept[0] and q.get('k') == net_kept[0]:
                return await send(w, 200, '"ok"', cors)  # asked twice: already kept
            return await send(w, 400, '"no address on trial"', cors)
        if path == '/api/hostname' and method == 'POST':
            try:
                cfg['hostname'] = ok_hostname(json.loads(body or '{}').get('hostname'))
            except Exception as ex:
                return await send(w, 400, json.dumps(str(ex)))
            save_cfg(cfg)
            await send(w, 200, '"ok"')
            await asyncio.sleep(1)
            restart()
        if path in ('/api/notify', '/api/notify/test') and method == 'POST':
            try:
                b = json.loads(body or '{}')
                if path == '/api/notify':
                    set_notify(b)
                    return await send(w, 200, json.dumps(notify_view()))
                if not notify.channels(cfg.get('notify')):
                    raise ValueError('set up Pushover or ntfy first')
                res = await send_alert('Oil Monitor test', 'Notifications from %s are working.' % HOSTNAME, force=True)
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
        if path == '/api/mqtt' and method == 'POST':
            try:
                set_mqtt(json.loads(body or '{}'))
                return await send(w, 200, json.dumps(mqtt_view()))
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
            mac = str(jb(body).get('mac', '')).lower()
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
            return await send(w, 200, json.dumps(update_check(authed(auth))))
        if path == '/api/update/install' and method == 'POST':
            if installing[0]:
                return await send(w, 409, json.dumps('An update is already being installed'))
            if net_restart[0] or net_trial[0]:  # (its restarts would count against the new version)
                return await send(w, 409, json.dumps('A new address is being tried: update in a few minutes'))
            installing[0] = True
            try:
                import updater
                m = manifest[0] if manifest_fresh() else with_room(updater.check, VERSION)['manifest']
                want = (json.loads(body) if body else {}).get('version')
                if want and m['version'] != want:  # (a newer release since the page showed it: never install unseen)
                    installing[0] = False
                    return await send(w, 409, json.dumps('Version %s is out now: check for updates again' % m['version']))
                if updater.vtuple(m['version']) <= updater.vtuple(VERSION):
                    installing[0] = False
                    return await send(w, 400, json.dumps('Already up to date'))
                make_room()
                wd_hold[0] += 1
                try:
                    v = updater.install(m, VERSION)
                finally:
                    wd_hold[0] -= 1
            except Exception as ex:
                gc.collect()
                installing[0] = False  # updater.install() undoes its own half-done swap
                return await send(w, 400, json.dumps('Update failed, nothing was changed: %s' % (str(ex) or repr(ex))))
            try:
                await send(w, 200, json.dumps(v))
            except Exception:
                pass  # the browser went away: restart onto the new version anyway
            await asyncio.sleep(1)
            restart()
        if path == '/api/deliveries':
            try:
                return await send_file(w, 'deliv.json', 'application/json')
            except OSError:
                return await send(w, 200, '{}')
        if path == '/api/forecast' and method == 'POST':  # (no PIN: the dashboard sends it for whoever is viewing;
            try:                                            # checked, and it only ever changes the date shown in HA)
                set_forecast(json.loads(body))
            except Exception as ex:
                return await send(w, 400, json.dumps('bad forecast: %s' % ex))
            return await send(w, 200, '"ok"')
        if path in ('/api/delivery', '/api/restore') and method == 'POST':
            try:
                b = json.loads(body)
                res = set_delivery(b) if path == '/api/delivery' else restore(b)
            except Exception as ex:
                return await send(w, 400, json.dumps('Could not save: %s' % ex))
            return await send(w, 200, json.dumps(res if res is not None else 'ok'))
        if path == '/api/tank/delete' and method == 'POST':
            dm = str(jb(body).get('mac', '')).lower()
            gone = cfg['tanks'].pop(dm, None) or {}
            if gone.get('group'):  # a link down to one tank is no link (as set_tank does)
                left = [t for t in cfg['tanks'].values() if t.get('group') == gone['group']]
                if len(left) == 1:
                    left[0].pop('group', None)
            (cfg.get('alerted') or {}).pop(dm, None)
            unset.clear(dm)  # (readings kept aside while the clock was unset: not for a tank that's gone)
            last_saved.pop(dm, None)
            save_cfg(cfg)
            return await send(w, 200, '"ok"')
        if path == '/api/wifi/scan':
            if not may_setup(auth, peer):  # (it blocks for seconds: not for anyone on the Wi-Fi to repeat)
                return await send(w, 401, json.dumps({'auth': 'login'}))
            nets = {}
            for n in wlan.scan():
                s = n[0].decode('utf-8', 'replace')
                if s and (s not in nets or n[3] > nets[s]):
                    nets[s] = n[3]
            return await send(w, 200, json.dumps([{'ssid': s, 'rssi': v} for s, v in
                                                  sorted(nets.items(), key=lambda x: -x[1])]))
        if path == '/api/wifi' and method == 'POST':
            b = jb(body)
            if not b.get('ssid'):
                return await send(w, 400, '"Pick a network"')
            cfg['ssid'], cfg['pw'] = b['ssid'], b.get('pw', '')
            save_cfg(cfg)
            await send(w, 200, '"ok"')
            await asyncio.sleep(1)
            restart()
        if path == '/api/discover':  # the Sensors nearby list is open: listen actively for a while
            discover(120)
            return await send(w, 200, '"ok"')
        if path == '/hawki':
            return await send(w, 200, hawki_json())
        if path == '/history':
            return await send_page(w, 'hist.html', 'text/html; charset=utf-8', inm)
        if path == '/common.js':
            return await send_page(w, 'common.js.html', 'text/javascript; charset=utf-8', inm)
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
            if q.get('since'):  # only the readings from then on (the Tanks page's "today's readings")
                try:
                    since = int(q['since'])
                    n = os.stat(hist_name(mac))[6] // 6
                    out = []
                    with open(hist_name(mac), 'rb') as f:  # newest at the end: read backwards a block at a time
                        k = n
                        while k > 0:
                            a = max(0, k - 64)
                            f.seek(a * 6)
                            blk = f.read((k - a) * 6)
                            recs = [blk[i:i + 6] for i in range(0, len(blk), 6)]
                            keep = [r for r in recs if struct.unpack('<I', r[:4])[0] >= since]
                            out = keep + out
                            if len(keep) < len(recs) or len(out) > 200:
                                break
                            k = a
                    return await send(w, 200, b''.join(out[-200:]), 'application/octet-stream')
                except (OSError, ValueError):
                    return await send(w, 200, b'', 'application/octet-stream')
            try:
                return await send_file(w, hist_name(mac), 'application/octet-stream')
            except OSError:
                return await send(w, 200, b'', 'application/octet-stream')
        if path == '/devices':  # (every Bluetooth device nearby, with raw adverts: signed in or maintenance only)
            if not (authed(auth) or cfg.get('maint') and q.get('t') == TOKEN):
                return await send(w, 401, json.dumps({'auth': 'login'}))
            f, a = q.get('name', '').lower(), q.get('addr', '').lower()
            out = {k: v for k, v in seen.items()
                   if (not f or f in v['name'].lower()) and (not a or k.startswith(a))}
            return await send(w, 200, json.dumps({'uptime': mono_s(), 'now': time.time(),
                                                  'count': len(seen), 'mem': gc.mem_free(), 'devices': out}))
        if maint:
            if path == '/reset':
                seen.clear()
                return await send(w, 200, '"ok"')
            if path == '/reboot':
                await send(w, 200, '"rebooting"')
                await asyncio.sleep(0.5)
                restart()
            if path == '/run':
                g = {'ble': ble, 'seen': seen, 'start_scan': start_scan, 'scan_on': scan_on,
                     'hook': hook, 'asyncio': asyncio}
                try:
                    exec(open(q['name']).read(), g)
                    wd_hold[0] += 1
                    try:
                        res = json.dumps(await g['run'](q))
                    finally:
                        wd_hold[0] -= 1
                except Exception as ex:
                    res = json.dumps({'error': repr(ex)})
                finally:
                    hook[0] = None
                    if not scan_on[0]:
                        scan_on[0] = True
                        start_scan()
                return await send(w, 200, res)
        await send(w, 404, '"not found"')
    except BadRequest as ex:
        try:
            await send(w, 400, json.dumps('Could not save: %s' % ex))
        except Exception:
            pass
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


wx_back = {}  # part -> [mono_s() of the next try, wait]: a part that fails waits 20 min, doubling to 6 h


def wx_err(part, ex):
    if ex is None:
        wx_state['errs'].pop(part, None)
        wx_back.pop(part, None)
    else:
        wx_state['errs'][part] = str(ex) or repr(ex)
        print('weather', part, ex)
        b = wx_back.get(part) or [0, 600]
        b[1] = min(6 * 3600, b[1] * 2)
        b[0] = mono_s() + b[1]
        wx_back[part] = b


def wx_due(part):
    b = wx_back.get(part)
    return b is None or mono_s() >= b[0]


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
    wx_back.clear()  # (a new place starts without the old one's waiting after failures)
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
        if ready and wx_state['done'] != today and wx_due('archive'):
            have = None
            try:
                have = weather.load()
                first = first_reading()
                d0 = weather.day_of(first) if first else today - 30
                todo = weather.plan(have, max(d0, today - 3650), today)
                for a, b in todo[:6]:  # at most 6 requests a go; the rest 10 minutes later
                    await web_quiet()
                    if cfg.get('wx') is not w:
                        break  # the location changed (or weather was switched off) while waiting
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
        if ready and cfg.get('wx') is w and time.time() - wx_state['fat'] > 6 * 3600 and wx_due('forecast'):
            try:
                await web_quiet()
                got = with_room(weather.forecast, w['lat'], w['lon']) if cfg.get('wx') is w else None
                if cfg.get('wx') is w and got:
                    weather.save(got, weather.FFILE)
                    wx_state['fat'] = time.time()
                wx_err('forecast', None)
            except Exception as ex:
                wx_err('forecast', ex)
            got = None
            gc.collect()
        if ready and cfg.get('wx') is w and (wx_state['norm_y'] != yr or wx_state['norm'] is None) and wx_due('normals'):
            nm = None
            try:
                nm = weather.norm_load(w['lat'], w['lon'])
                wx_state['norm'] = weather.norm_view(nm, yr)  # what's saved counts now, even if a fetch fails
                for _ in range(2):
                    y = weather.norm_next(nm, yr)
                    if y is None:
                        break
                    await web_quiet()
                    if cfg.get('wx') is not w:
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


# ---------- Home Assistant over MQTT (mqtt.py) ----------
# The Pico logs in to the MQTT broker (in HA: the Mosquitto add-on) and HA finds the tanks by itself.
# cfg['mqtt'] = {host, port, user, pw}; cfg['mqtt_macs'] = the tanks HA was told about, kept even while MQTT is off,
# so a tank removed meanwhile has its sensors taken out of HA when it's back on
mqtt_state = {'connected': False, 'err': None, 'sent_at': None, 'gen': 0}


def mqtt_view():
    c = cfg.get('mqtt')
    return {'on': c is not None, 'host': c and c.get('host'), 'port': c and c.get('port'), 'user': c and c.get('user'),
            'pw_set': bool(c and c.get('pw')), 'connected': mqtt_state['connected'], 'err': mqtt_state['err'],
            'sent_at': mqtt_state['sent_at']}  # (never the password)


def set_mqtt(b):
    old = cfg.get('mqtt')
    if b.get('off'):
        cfg.pop('mqtt', None)
    else:
        cfg['mqtt'] = mqtt.clean(b, old)
    mqtt_state['err'] = None
    mqtt_state['gen'] += 1  # the task reconnects with the new settings
    save_cfg(cfg)


def mqtt_err(ex):
    n = ex.args[0] if getattr(ex, 'args', None) else None
    if isinstance(ex, asyncio.TimeoutError):
        return 'no answer from the broker: check its address'
    if n == 111:
        return 'the broker refused the connection: is the Mosquitto add-on running, and the port right?'
    if n in (113, 118, 119, 103, 104, 110):
        return 'could not reach the broker (%s)' % n
    return str(ex) or repr(ex)


async def mqtt_task():
    await asyncio.sleep(15)
    pico = binascii.hexlify(wlan.config('mac')).decode()
    base = 'hawki/' + pico
    while True:
        c = cfg.get('mqtt')
        if not c or not wlan.isconnected():
            mqtt_state['connected'] = False
            await asyncio.sleep(5)
            continue
        gen, w, wait = mqtt_state['gen'], None, 1
        try:
            r, w = await asyncio.wait_for(asyncio.open_connection(c['host'], c['port']), 10)

            async def put(b):  # (a stalled broker must not hold the task up forever: timeout -> reconnect)
                w.write(b)
                await asyncio.wait_for(w.drain(), 15)

            async def pub(topic, payload):
                await put(mqtt.publish_pkt(topic, payload))
            await put(mqtt.connect_pkt('hawki-' + pico, c.get('user'), c.get('pw'), base + '/status', b'offline'))
            e = mqtt.connack(await asyncio.wait_for(r.readexactly(4), 10))
            if e:
                raise ValueError(e)
            await pub(base + '/status', 'online')
            mqtt_state.update(connected=True, err=None)
            told, last, ping, wifi_at = None, {}, time.ticks_ms(), 0
            while cfg.get('mqtt') is c and mqtt_state['gen'] == gen and wlan.isconnected():
                now = time.time()
                tanks = cfg['tanks']
                key = repr(sorted((m, t.get('name')) for m, t in tanks.items()))
                if key != told:  # tell HA what's there (again after a rename, a new or a removed tank)
                    for m, t in tanks.items():
                        for tp, pl in mqtt.discovery(pico, m, t.get('name', m), VERSION):
                            await pub(tp, pl)
                    for m in cfg.get('mqtt_macs', []):
                        if m not in tanks:
                            for tp, pl in mqtt.removal(m, pico):
                                await pub(tp, pl)
                    if sorted(cfg.get('mqtt_macs', [])) != sorted(tanks):
                        cfg['mqtt_macs'] = list(tanks)
                        save_cfg(cfg)
                    told, last = key, {}
                for m, t in tanks.items():
                    v = tank_view(m, t, now)
                    s = (json.dumps(mqtt.state(v, now)), mqtt.avail(v))
                    if last.get(m) != s:
                        await pub('%s/%s/state' % (base, mqtt.nomac(m)), s[0])
                        await pub('%s/%s/avail' % (base, mqtt.nomac(m)), s[1])
                        last[m] = s
                        mqtt_state['sent_at'] = now
                if now - wifi_at > 600:
                    await pub(base + '/pico', json.dumps({'wifi': wlan.status('rssi')}))
                    wifi_at = now
                if time.ticks_diff(time.ticks_ms(), ping) > 60000:
                    await put(mqtt.PING)
                    if await asyncio.wait_for(r.readexactly(2), 10) != b'\xd0\x00':
                        raise ValueError('the broker stopped answering')
                    ping = time.ticks_ms()
                await asyncio.sleep(10)
            if cfg.get('mqtt') is not c or mqtt_state['gen'] != gen:  # settings changed or turned off: say goodbye
                try:
                    await pub(base + '/status', 'offline')
                    await put(mqtt.DISCONNECT)
                except Exception:
                    pass
        except Exception as ex:
            if mqtt_state['gen'] == gen:
                mqtt_state['err'] = mqtt_err(ex)
                print('mqtt', ex)
            wait = 30
        finally:
            mqtt_state['connected'] = False
            if w:
                try:
                    w.close()
                    await w.wait_closed()
                except Exception:
                    pass
        for _ in range(wait):  # (a settings change cuts the wait short)
            if mqtt_state['gen'] != gen:
                break
            await asyncio.sleep(1)


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
                d = None
            if not price_state.get('checked') and now > 1.7e9:  # (with the clock set: 'today' before then is 2021,
                price_state['checked'] = True                    # and a day already fetched would be fetched again)
                if price_state['now'] and price_state['now'][0] == today:
                    price_state['day'] = today  # already fetched today (before a restart)
                    price_state['pc'] = (cfg.get('price') or {}).get('pc')
            p = cfg.get('price')
            gap = price_state.get('gap') or 1800  # (after a failure: 30 min, doubling to 8 h; reset by a success)
            if (p is not None and now > 1.7e9 and wlan.isconnected() and price_state['day'] != today
                    and now - price_state['tried'] > gap and time.gmtime(now)[3] >= 9):
                await web_quiet()
                now = time.time()  # (after the wait: it may be another day, or prices switched off)
                today = weather.day_of(now)
                p = cfg.get('price')
            if (p is not None and now > 1.7e9 and wlan.isconnected() and price_state['day'] != today
                    and now - price_state['tried'] > gap and time.gmtime(now)[3] >= 9):
                price_state['tried'] = now
                try:
                    got = with_room(price.fetch, p['pc'])
                    if cfg.get('price') is p:
                        price.add(today, got)
                        price_state['day'] = today
                        price_state['now'] = [today, got[0], got[1]]
                        price_state['pc'] = p['pc']
                        price_state['err'] = None
                        price_state['gap'] = 1800
                except Exception as ex:
                    price_state['err'] = str(ex) or repr(ex)
                    price_state['gap'] = min(8 * 3600, (price_state.get('gap') or 1800) * 2)
                    print('price err', ex)
                gc.collect()
        except Exception as ex:
            print('price task', ex)
        await asyncio.sleep(600)


async def keep(fn, name):
    # A task that stops on an error is started again (otherwise it is gone until a restart: a dead Wi-Fi keeper
    # means no reconnect and no setup network). Waits 10 s, doubling to 10 min while it keeps failing quickly.
    wait = 10
    while True:
        t0 = mono_s()
        try:
            await fn()
            return  # finished on its own (the one-off tasks)
        except Exception as ex:
            print('task', name, 'stopped:', repr(ex))
        wait = 10 if mono_s() - t0 > 600 else min(wait * 2, 600)
        await asyncio.sleep(wait)


# Soft watchdog: the main loop beats every 30 s; if it hasn't for WD_MINUTES (the event loop stuck, or blocked
# far longer than any fetch or update takes), restart. (The hardware watchdog can't wait more than 8 s, and one
# HTTPS fetch blocks longer than that.) The timer callback only compares two small ints.
WD_MINUTES = 10
beat = [0]
wd = [0, 0]  # beat last seen, minutes it hasn't changed
wd_hold = [0]  # long jobs on purpose (an update over weak Wi-Fi, a maintenance script, a big history upload)


def wd_check(_t=None):
    if beat[0] != wd[0] or wd_hold[0]:
        wd[0], wd[1] = beat[0], 0
        return
    wd[1] += 1
    if wd[1] >= WD_MINUTES:
        machine.reset()


async def main():
    load_forecasts()
    for fn, name in ((wifi_keeper, 'wifi'), (recorder, 'recorder'), (scan_scheduler, 'scan'), (alerts, 'alerts'),
                     (weather_task, 'weather'), (price_task, 'price'), (mqtt_task, 'mqtt'),
                     (net_trial_guard, 'net trial'), (update_guard, 'update guard'), (bootsel_reset, 'bootsel')):
        asyncio.create_task(keep(fn, name))
    await asyncio.start_server(handle, '0.0.0.0', 80)
    wd_timer = machine.Timer(mode=machine.Timer.PERIODIC, period=60000, callback=wd_check)  # noqa: F841 (kept)
    while True:
        for _ in range(2):
            await asyncio.sleep(30)
            beat[0] = (beat[0] + 1) & 0xffff
        gc.collect()


asyncio.run(main())
