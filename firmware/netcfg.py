"""Fixed (static) address settings: checking them, and the one-boot trial (runs on CPython and MicroPython).

A new fixed address is never saved straight to config.json. It is written to net.try and the Pico restarts;
at boot the file is read and DELETED at once, so the settings apply to that one boot only. They become
permanent only when a browser reaches the Pico at the new address and says so (POST /api/net/keep with
the one-time key); otherwise the app restarts after a few minutes, or the user pulls the plug, and either
way the Pico comes back with the settings it had before.
"""
import json, os

TRY = 'net.try'
TRIAL_SECS = 180


def _quad(s, what):
    p = str(s or '').strip().split('.')
    if len(p) != 4 or not all(x.isdigit() and len(x) <= 3 and int(x) <= 255 for x in p):
        raise ValueError(what + ': four numbers like 192.168.1.50')
    return tuple(int(x) for x in p)


def _n(q):
    return (q[0] << 24) | (q[1] << 16) | (q[2] << 8) | q[3]


def _s(q):
    return '%d.%d.%d.%d' % q


def clean(b):
    """{'ip','mask','gw','dns'} as tidy strings, or ValueError saying what's wrong."""
    ip = _quad(b.get('ip'), 'address')
    mask = _quad(b.get('mask') or '255.255.255.0', 'subnet mask')
    gw = _quad(b.get('gw'), 'router (gateway)')
    dns = _quad(b.get('dns') or _s(gw), 'DNS server')
    m = _n(mask)
    inv = ~m & 0xffffffff
    if m == 0 or inv & (inv + 1) or inv < 3:
        raise ValueError('subnet mask: not a usable mask (most homes use 255.255.255.0)')
    if ip[0] in (0, 127) or ip[0] >= 224:
        raise ValueError('address: not one a device can use')
    host = _n(ip) & inv
    if host == 0 or host == inv:
        raise ValueError("address: that is the network's own or its broadcast address")
    if (_n(gw) & m) != (_n(ip) & m):
        raise ValueError('router (gateway): must be on the same network as the address')
    gh = _n(gw) & inv
    if gw == ip or gh == 0 or gh == inv:
        raise ValueError("router (gateway): must be the router's own address, not the Pico's")
    if dns[0] in (0, 127) or dns[0] >= 224:
        raise ValueError('DNS server: not a usable address')
    return {'ip': _s(ip), 'mask': _s(mask), 'gw': _s(gw), 'dns': _s(dns)}


def tup(n):
    return (n['ip'], n['mask'], n['gw'], n['dns'])


def write_try(n, key, name=TRY):
    with open(name + '.tmp', 'w') as f:
        json.dump(dict(n, k=key), f)
    os.rename(name + '.tmp', name)


def take_try(name=TRY):
    """The settings to try on this boot (with their key 'k'), or None. The file is removed before anything
    is done with it: a restart for any reason goes back to the saved settings."""
    try:
        with open(name) as f:
            raw = f.read()
    except OSError:
        return None
    try:
        os.remove(name)
    except OSError:
        return None  # can't remove it: don't risk trying these settings on every boot
    try:
        j = json.loads(raw)
        n = clean(j)
        k = str(j.get('k') or '')
        if len(k) < 8:
            return None
        n['k'] = k
        return n
    except Exception:
        return None
