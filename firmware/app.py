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


B = 'b'  # the ready-built modules, searched before the sources (sys.path)


def _rm(n):
    # True once n is gone (False: still there, e.g. a directory or a flash error)
    try:
        os.remove(n)
    except OSError:
        pass
    try:
        os.stat(n)
        return False
    except OSError as ex:
        return bool(ex.args) and ex.args[0] == 2  # (only "no such file" says it's gone: a flash error says nothing)


def _sha(n):
    import hashlib, binascii
    h, buf = hashlib.sha256(), bytearray(1024)
    try:
        with open(n, 'rb') as f:
            while True:
                k = f.readinto(buf)
                if not k:
                    break
                h.update(buf if k == len(buf) else buf[:k])
    except OSError:
        return None
    return binascii.hexlify(h.digest()).decode()


def _runs_here(n, m):
    # a built file this MicroPython loads: bytecode only (no machine code), its .mpy version, small ints that fit
    try:
        with open(n, 'rb') as f:
            h = f.read(4)
    except OSError:
        return False
    return len(h) == 4 and h[0] == 77 and h[1] == m & 0xff and h[2] == 0 and h[3] <= 31


def built(path):
    """Put b/X.mpy in place for each module whose source here (X.py) is the one its X.mpy.html was built from
    (built.py: the sha-256 of both): one put back by hand, a rollback, an older release's files all run as source. Returns how many
    are used; path (sys.path) gets b first if any are."""
    import sys
    try:
        from built import SRC
    except Exception:  # (no index: a release from before the built copies, or a hand-made set of files)
        SRC = {}
    m = getattr(sys.implementation, '_mpy', 0)
    try:
        os.mkdir(B)
    except OSError:
        pass
    stuck = False  # a file that should be gone and isn't: b/ never searched (it could hold an old module)
    for n in os.listdir(B):  # (a module that's gone, or a copy cut off part-way)
        if not n.endswith('.mpy') or n[:-4] + '.py' not in SRC:
            stuck = not _rm(B + '/' + n) or stuck
    used = 0
    for n, (sha, bsha) in SRC.items():
        x, b = n[:-3] + '.mpy.html', '%s/%s.mpy' % (B, n[:-3])
        ok = m and _sha(n) == sha and _runs_here(x, m)
        have = ok and _sha(b) == bsha
        if ok and not have and _sha(x) == bsha:
            with open(x, 'rb') as f, open(b + '.tmp', 'wb') as g:
                buf = bytearray(1024)
                while True:
                    k = f.readinto(buf)
                    if not k:
                        break
                    g.write(buf if k == len(buf) else buf[:k])
            os.rename(b + '.tmp', b)
            have = _sha(b) == bsha  # (flash full part-way: never a damaged copy)
        if not have:
            stuck = not _rm(b) or stuck
            continue
        used += 1
    if stuck:
        if '/' + B in path:
            path.remove('/' + B)
        return 0
    if used and '/' + B not in path:
        path.insert(0, '/' + B)
    return used


_w = _take('upd.want')
if _w:
    install(_w)
_w = None
try:
    import sys
    print('built modules:', built(sys.path))
except Exception as ex:  # (whatever it is: the sources)
    print('built err', repr(ex))
    try:
        sys.path.remove('/' + B)
    except ValueError:
        pass
gc.collect()
import core  # noqa: E402,F401  (runs for ever)
