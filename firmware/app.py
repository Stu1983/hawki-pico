# The front door: main.py imports app (main.py itself never comes over the air), and this loads the app (core.py).
# An update asked for (the note upd.want: the Install button, or an install that ran out of memory and restarted to
# try again) is installed HERE first, before the app is loaded. Loading the app's ~180 KB of source leaves the heap
# in pieces too small for the TLS an install needs: on 2026-11-27, 256 KB free but no block over 12 KB, and v1.3.46
# would not install even straight after a restart. Here only Wi-Fi, the clock and updater.py are in memory.
import gc, json, os, time, machine

OOM_WHY = 'not enough memory even before the app started'


def _take(name):
    try:
        with open(name) as f:
            d = json.load(f)
    except Exception:
        d = None
    try:
        os.remove(name)  # (read once: a note that crashes the start must not be acted on at every start)
    except OSError:
        return None  # (one that can't be removed would be acted on at every start: never)
    return d if isinstance(d, dict) else None


def _leave(name, d):
    try:
        with open(name, 'w') as f:
            json.dump(d, f)
    except Exception as ex:
        print('note err', name, ex)


def _oom(ex):
    # out of memory: MemoryError, or mbedtls' OSError ENOMEM (the same test as core.is_oom)
    return isinstance(ex, MemoryError) or isinstance(ex, OSError) and (
        getattr(ex, 'errno', None) == 12 or bool(ex.args and ex.args[0] == 12))


def _planned():
    # the restart that follows is planned, not a freeze (core.py's watchdog record: SCRATCH0, last step 0xFE)
    try:
        import sys
        a = (0x400d8000 if 'RP2350' in getattr(sys.implementation, '_machine', '') else 0x40058000) + 0x0c
        machine.mem32[a] = 0x4BFE0000
    except Exception:
        pass


def _online(cfg, wlan, wait_s=90):
    import network, binascii
    wlan.active(True)
    try:
        wlan.config(pm=0xa11140)  # (power-save off, as the app has it)
    except Exception:
        pass
    n = cfg.get('net')
    if n:  # a fixed address
        import netcfg
        wlan.ifconfig(netcfg.tup(n))
        network.ipconfig(dns=n['dns'])
    b = cfg.get('ap_b')  # the access point it was on last (a mesh: never the first one that answers, if it can help it)
    t0 = time.ticks_ms()
    ok_b = isinstance(b, str) and len(b) == 12 and all(c in '0123456789abcdefABCDEF' for c in b)
    for bssid in ([binascii.unhexlify(b)] if ok_b else []) + [None]:
        try:
            wlan.disconnect()
        except Exception:
            pass
        try:
            if bssid:
                wlan.connect(cfg['ssid'], cfg.get('pw', ''), bssid=bssid)
            else:
                wlan.connect(cfg['ssid'], cfg.get('pw', ''))
        except Exception as ex:  # (that access point refused outright: the next way)
            print('join', ex)
            continue
        while time.ticks_diff(time.ticks_ms(), t0) < wait_s * 1000 * (1 if bssid is None else 0.4):
            if wlan.isconnected():
                break
            time.sleep_ms(250)
        if wlan.isconnected():
            break
    if not wlan.isconnected():
        raise OSError('could not join the Wi-Fi')
    if time.time() < 1700000000:  # (certificates are checked against the date)
        import ntptime
        for host in ('pool.ntp.org', 'time.google.com', 'pool.ntp.org'):
            try:
                ntptime.host = host
                ntptime.settime()
                break
            except Exception as ex:
                print('ntp', host, ex)
        if time.time() < 1700000000:
            raise OSError('could not set the clock')


def install(w):
    """The update asked for in w ({'v', 'id'}). Restarts into it; returns only if it failed (upd.last says why)."""
    import network
    from version import VERSION
    v = w.get('v')
    wlan = network.WLAN(network.STA_IF)
    try:
        with open('config.json') as f:
            cfg = json.load(f)
        if not cfg.get('ssid'):
            raise OSError('no Wi-Fi set up')
        _online(cfg, wlan)
        cfg = None
        gc.collect()
        import updater
        m = updater.check(VERSION)['manifest']
        if m['version'] != v:  # (never install a release nobody saw)
            raise OSError('version %s is out now: check for updates again' % m['version'])
        if updater.vtuple(v) <= updater.vtuple(VERSION):
            raise OSError('already up to date')
        updater.tidy()  # (what a failed try left)
        gc.collect()
        updater.install(m, VERSION)
    except Exception as ex:
        print('install', repr(ex))
        why = OOM_WHY if _oom(ex) else (str(ex) or repr(ex))
        _leave('upd.last', {'ok': False, 'from': VERSION, 'to': v, 'id': w.get('id'), 'reason': why[:200], 'stage': 'install'})
        try:
            wlan.disconnect()  # (the app joins in its own way: the nearest access point)
        except Exception:
            pass
        return
    _planned()
    machine.reset()


_w = _take('upd.want')
if _w:
    install(_w)
_w = None
gc.collect()
import core  # noqa: E402,F401  (runs for ever)
