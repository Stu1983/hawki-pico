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
# Maintenance (token): PUT /file?name=x&t=TOK, GET /reboot?t=TOK, GET /run?name=x.py&t=TOK
# Debug: GET /devices[?name=&addr=], GET /reset
#
# No Wi-Fi configured, or it can't connect for 60 s: the Pico also opens a setup network
# "HAWKi-Setup-XXXX" (password: oiltanks); browse to http://192.168.4.1/
import bluetooth, binascii, json, time, network, machine, asyncio, gc, os, struct
from hawki_decode import decode, mfr_from_adv
from tankcalc import reading, litres, SHAPES
import histstore
from version import VERSION

# HAWKi service UUID 00001923-1322-ffdd-3533-886fdadce133, as it appears in the advert (LE)
HAWKI_UUID = bytes(reversed(binascii.unhexlify('000019231322ffdd3533886fdadce133')))
AP_PASSWORD = 'oiltanks'
MEASURED_KEYS = ('outlet_cm', 'win_bottom_cm', 'win_top_cm', 'win_outer_w_cm', 'win_inner_w_cm',
                 'win_inner_h_cm', 'rib_h_cm', 'rib_depth_cm')
CFG_KEYS = ('shape', 'height_cm', 'length_cm', 'width_cm', 'capacity_l', 'windows', 'window_model',
            'ribs_cm', 'reserve_l') + MEASURED_KEYS


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
seen = {}    # mac -> every BLE device heard (debug)
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
            if len(seen) > 200:  # memory guard
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
                hawki[k] = d
        h = hx(adv)
        lst = e['adv'].setdefault(str(adv_type), [])
        if h not in lst:
            lst.append(h)
            if len(lst) > 4:
                lst.pop(0)
    elif ev == 6:  # _IRQ_SCAN_DONE -> restart unless paused for GATT work
        if scan_on[0]:
            start_scan()
    elif hook[0]:
        hook[0](ev, data)


scan_on = [True]
hook = [None]  # experiments (/run) receive every non-scan BLE event here

ble = bluetooth.BLE()
ble.active(True)
ble.irq(irq)


def start_scan():
    ble.gap_scan(0, 60000, 30000, True)  # forever, active (gets names)


start_scan()

try:
    network.hostname('hawki-pico')  # reachable as http://hawki-pico.local/ where mDNS works
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
# Every minute, note each configured tank's latest distance; on the hour, append the hour's
# median to h_<last 6 hex of mac>.bin as <uint32 epoch (mid-hour), uint16 mm>: 52 KB a year
# per tank. Distances, not litres, so changing a tank's shape re-maps the whole history.
# Daily at 03:00 UTC, readings older than KEEP_HOURLY_DAYS shrink to one per day (that day's
# median; histstore.py), so history stays ~110 KB per tank for good.
samples = {}
KEEP_HOURLY_DAYS = 730


def hist_name(mac):
    return 'h_' + mac.replace(':', '')[-6:] + '.bin'


def flush_hour(hr):
    for mac, l in samples.items():
        if l and mac in cfg['tanks']:
            l.sort()
            try:
                with open(hist_name(mac), 'ab') as f:
                    f.write(struct.pack('<IH', hr * 3600 + 1800, l[len(l) // 2]))
            except Exception as ex:
                print('hist err', ex)
    samples.clear()


async def compact_all(now):
    for mac in list(cfg['tanks']):  # ~2 s per 2-year file; let BLE/HTTP run in between
        try:
            print('compact', mac, histstore.compact(hist_name(mac), now - KEEP_HOURLY_DAYS * 86400))
        except Exception as ex:
            print('compact err', mac, ex)
        await asyncio.sleep(0)


async def recorder():
    cur = None
    while True:
        await asyncio.sleep(60)
        now = time.time()
        if now < 1700000000:  # clock not set yet
            continue
        hr = now // 3600
        if cur is not None and hr != cur:
            flush_hour(cur)
            if hr % 24 == 3:
                await compact_all(now)
        cur = hr
        for mac in cfg['tanks']:
            d = hawki.get(mac)
            if d and now - d['rx'] < 180 and d.get('level') not in (None, 16383):
                samples.setdefault(mac, []).append(d['level'])


def curve(t):
    H = float(t['height_cm']) * 10
    n = int(H // 10)
    out = [round(litres(t, min(H, i * 10)), 1) for i in range(n + 1)]
    if n * 10 < H:
        out.append(0.0)
    return {'step': 10, 'h': H, 'l': out}


# ---------- views ----------

def tank_view(mac, t, now):
    d = hawki.get(mac) or {}
    lvl = d.get('level')
    lit, pct = reading(t, lvl) if lvl is not None else (None, None)
    std = None  # what the Magnus-style standard model says, for comparison
    if t.get('window_model') == 'measured' and lvl is not None:
        std = reading(dict(t, window_model='standard'), lvl)[0]
    return {'mac': mac, 'name': t.get('name', mac), 'level': lvl, 'litres': lit, 'percent': pct,
            'litres_standard': std,
            'battery': d.get('battery'), 'rssi': d.get('rssi'),
            'age': (now - d['rx']) if d.get('rx') else None,
            'cfg': {k: t.get(k) for k in CFG_KEYS}}


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
            'ap': AP_NAME if ap.active() else None, 'update': update_info()}


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
         'height_cm': num(b['height_cm'], 10, 500), 'capacity_l': num(b['capacity_l'], 1, 100000),
         'windows': int(num(b.get('windows', 0), 0, 2))}
    if b.get('reserve_l') not in (None, ''):
        t['reserve_l'] = num(b['reserve_l'], 0, 100000)
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
            if r[0] != last:
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
    await w.drain()


async def send_file(w, name, ctype):
    size = os.stat(name)[6]
    w.write(('HTTP/1.0 200 OK\r\nContent-Type: %s\r\nContent-Length: %d\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n' % (ctype, size)).encode())
    with open(name, 'rb') as f:
        while True:
            chunk = f.read(1024)
            if not chunk:
                break
            w.write(chunk)
            await w.drain()


async def handle(r, w):
    try:
        line = (await r.readline()).decode()
        method, path, _ = line.split(' ', 2)
        clen = 0
        while True:
            h = await r.readline()
            if h in (b'\r\n', b'\n', b''):
                break
            if h.lower().startswith(b'content-length:'):
                clen = int(h.split(b':')[1])
        path, q = parse_q(path)
        if method == 'PUT' and path == '/file' and q.get('t') == TOKEN:
            # stream uploads straight to flash: big files don't fit in one read
            got = 0
            with open(q['name'] + '.part', 'wb') as fh:
                while got < clen:
                    chunk = await r.read(min(1024, clen - got))
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
            if got != clen:
                return await send(w, 400, '"short upload %d/%d"' % (got, clen))
            os.rename(q['name'] + '.part', q['name'])
            return await send(w, 200, '"wrote %d"' % got)
        if method == 'POST' and path == '/api/hist':
            mac = q.get('mac', '').replace('%3A', ':').replace('%3a', ':').lower()
            if mac not in cfg['tanks'] or clen % 6:
                return await send(w, 400, '"bad history upload"')
            got = 0
            with open('hist.up', 'wb') as fh:  # stream to flash; merged once complete (no awaits)
                while got < clen:
                    chunk = await r.read(min(1024, clen - got))
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
            if got != clen:
                return await send(w, 400, '"short upload"')
            return await send(w, 200, json.dumps(merge_hist(hist_name(mac), 'hist.up')))
        if clen > (16000 if path in ('/api/restore', '/api/delivery') else 4000):
            return await send(w, 413, '"too large"')
        body = await r.readexactly(clen) if clen and method == 'POST' else b''

        if path in ('/', '/index.html'):
            return await send_file(w, 'ui.html', 'text/html; charset=utf-8')
        if path == '/api/state':
            return await send(w, 200, json.dumps(state()))
        if path == '/api/tank' and method == 'POST':
            try:
                set_tank(json.loads(body))
            except Exception as ex:
                return await send(w, 400, json.dumps('Could not save: %s' % ex))
            return await send(w, 200, '"ok"')
        if path == '/api/update/check':
            try:
                import updater
                r = updater.check(VERSION)
                manifest[0] = r.pop('manifest')
            except Exception as ex:
                r = {'current': VERSION, 'error': str(ex) or repr(ex)}
            gc.collect()
            return await send(w, 200, json.dumps(r))
        if path == '/api/update/install' and method == 'POST':
            try:
                import updater
                m = manifest[0] or updater.check(VERSION)['manifest']
                if updater.vtuple(m['version']) <= updater.vtuple(VERSION):
                    return await send(w, 400, json.dumps('Already up to date'))
                v = updater.install(m, VERSION)
            except Exception as ex:
                gc.collect()
                return await send(w, 400, json.dumps('Update failed, nothing was changed: %s' % (str(ex) or repr(ex))))
            await send(w, 200, json.dumps(v))
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
            cfg['tanks'].pop(str(json.loads(body).get('mac', '')).lower(), None)
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
        if path == '/hawki':
            return await send(w, 200, hawki_json())
        if path == '/history':
            return await send_file(w, 'hist.html', 'text/html; charset=utf-8')
        if path in ('/api/hist', '/api/curve'):
            mac = q.get('mac', '').replace('%3A', ':').replace('%3a', ':').lower()
            if mac not in cfg['tanks']:
                return await send(w, 404, '"unknown tank"')
            if path == '/api/curve':
                return await send(w, 200, json.dumps(curve(cfg['tanks'][mac])))
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
        if path == '/reset':
            seen.clear()
            return await send(w, 200, '"ok"')
        if q.get('t') == TOKEN:
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
        try:
            w.close()
            await w.wait_closed()
        except Exception:
            pass
        gc.collect()


async def main():
    asyncio.create_task(wifi_keeper())
    asyncio.create_task(recorder())
    asyncio.create_task(update_guard())
    await asyncio.start_server(handle, '0.0.0.0', 80)
    while True:
        await asyncio.sleep(60)
        gc.collect()


asyncio.run(main())
