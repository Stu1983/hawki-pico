"""Share for support (opt-in): once a day this Pico's readings, tank settings, deliveries and weather go to the
share server (a Cloudflare Worker) under a random ID, like HK-7QM2-XFD9. The owner gives the ID to someone
helping them, who sees the same Dashboard and Forecast pages; the same ID restores the readings to a new Pico.

Never sent: the Wi-Fi name or password, the PIN, notification keys, MQTT, the network details or the place name.
Tank names and delivery notes go as typed (the owner is told so).
The location goes as the postcode district (if given for oil prices) and the weather location rounded to a
quarter of a degree (about 15 miles by 10). Only this Pico can change or delete its upload: it alone holds the
key (made here, never shown). Runs on CPython and MicroPython.
"""
import binascii, json, os, socket, time

HOST = 'hawki-share.northcoast.workers.dev'  # the share server (cloud/share-worker)
FILE = 'share.up'
ALPH = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'  # Crockford's base 32: no I, L, O or U to misread
STATE_KEYS = ('tanks', 'primary', 'year_l', 'switch', 'price')  # all else in /api/state stays on the Pico


def new_id():
    n = int.from_bytes(os.urandom(5), 'big')  # 40 random bits: a trillion IDs, none guessable
    s = ''.join(ALPH[(n >> (5 * i)) & 31] for i in range(8))
    return 'HK-' + s[:4] + '-' + s[4:]


def new_key():
    return binascii.hexlify(os.urandom(16)).decode()


def ok_id(s):
    """A share ID as typed (any case, spaces, I/L for 1, O for 0) -> 'HK-XXXX-XXXX', or ValueError."""
    s = ''.join(c for c in str(s or '').upper() if c.isalpha() or c.isdigit())
    s = s[2:] if s.startswith('HK') and len(s) == 10 else s
    s = s.replace('O', '0').replace('I', '1').replace('L', '1')
    if len(s) != 8 or any(c not in ALPH for c in s):
        raise ValueError('a share ID looks like HK-7QM2-XFD9')
    return 'HK-' + s[:4] + '-' + s[4:]


def area(cfg):
    """Roughly where: the postcode district given for oil prices, and the weather location to 0.25 degrees."""
    w = cfg.get('wx') or {}
    out = {'pc': (cfg.get('price') or {}).get('pc') or None, 'lat': None, 'lon': None}
    try:
        out['lat'], out['lon'] = round(float(w['lat']) * 4) / 4, round(float(w['lon']) * 4) / 4
    except (KeyError, TypeError, ValueError):
        pass
    return out


def clean_state(st, cfg):
    """/api/state with only what the pages need to draw the charts: nothing about the network, the Pico or the house."""
    out = {k: st[k] for k in STATE_KEYS if k in st}
    out['found'] = []
    out['pin_set'] = True
    out['update'] = {'version': (st.get('update') or {}).get('version')}
    wx = st.get('wx') or {}
    a = area(cfg)
    if wx.get('lat') is not None:
        out['wx'] = {'name': a['pc'] or 'about %.2f, %.2f' % (a['lat'], a['lon']), 'lat': a['lat'], 'lon': a['lon'],
                     'norm': wx.get('norm'), 'err': None}
    return out


def _size(name):
    try:
        return os.stat(name)[6]
    except OSError:
        return 0


def _b64_file(o, name, chunk=768):
    # a file as base 64, straight into the upload a piece at a time (a history can be 100 KB: never all in memory)
    try:
        f = open(name, 'rb')
    except OSError:
        return
    with f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            o.write(binascii.b2a_base64(b).decode().strip())


def build(cfg, st, files, curves, battlog, fw, now, out=FILE):
    """Write the upload to `out`: a backup (the format Config -> Backup exports, so it restores the same way) plus what
    the support view needs. files: {'deliv': path, 'hist': {mac: path}, 'wx': path, 'wxf': path, 'prices': path}.
    Returns its size in bytes."""
    tanks = {t['mac']: dict(t.get('cfg') or {}, name=t.get('name')) for t in st.get('tanks') or []}
    with open(out, 'w') as o:
        o.write('{"format":"hawki-backup","version":1,"share":1,"exported":%s,"at":%d,"fw":%s,"area":%s,"tanks":%s,'
                % (json.dumps('%04d-%02d-%02dT%02d:%02d:%02dZ' % time.gmtime(now)[:6]), int(now), json.dumps(fw),
                   json.dumps(area(cfg)), json.dumps(tanks)))
        o.write('"deliveries":')
        try:
            with open(files['deliv']) as f:
                d = json.load(f)
        except (OSError, ValueError, KeyError):
            d = {}
        o.write(json.dumps({m: d.get(m) or [] for m in tanks}))
        o.write(',"state":%s,"curves":%s,"battlog":%s,"history":{' % (json.dumps(clean_state(st, cfg)), json.dumps(curves), json.dumps(battlog)))
        first = True
        for m in tanks:
            p = (files.get('hist') or {}).get(m)
            if not p or not _size(p):
                continue
            o.write(('' if first else ',') + json.dumps(m) + ':"')
            _b64_file(o, p)
            o.write('"')
            first = False
        o.write('},"files":{')
        first = True
        for k in ('wx', 'wxf', 'prices'):
            if files.get(k) and _size(files[k]):
                o.write(('' if first else ',') + '"%s":"' % k)
                _b64_file(o, files[k])
                o.write('"')
                first = False
        o.write('}}')
    return os.stat(out)[6]


def _send(method, host, path, key, body_file=None, deadline=60):
    """One HTTPS request to the share server, the body streamed from a file. -> (status, first 300 bytes of the reply)."""
    import notify  # (its TLS context and per-read deadline)
    t0 = time.time()
    n = os.stat(body_file)[6] if body_file else 0
    ai = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0]
    s = socket.socket(ai[0], socket.SOCK_STREAM, ai[2])
    s.settimeout(15)
    try:
        s.connect(ai[-1])
        raw, s = s, notify._ctx().wrap_socket(s, server_hostname=host)
        w = s.write if hasattr(s, 'write') else s.sendall
        w(('%s %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: hawki-pico\r\nX-Key: %s\r\nContent-Type: application/json\r\n'
           'Content-Length: %d\r\nConnection: close\r\n\r\n' % (method, path, host, key, n)).encode())
        if body_file:
            with open(body_file, 'rb') as f:
                while True:
                    notify._within(s, raw, t0, deadline, host)
                    b = f.read(1024)
                    if not b:
                        break
                    w(b)
        rd = s.read if hasattr(s, 'read') else s.recv
        got = b''
        while len(got) < 2048:
            notify._within(s, raw, t0, deadline, host)
            c = rd(256)
            if not c:
                break
            got += c
            if b'\r\n\r\n' in got and len(got.split(b'\r\n\r\n', 1)[1]) >= 300:
                break
        try:
            status = int(got.split(b' ', 2)[1])
        except (IndexError, ValueError):
            raise OSError('no reply from the share server')
        return status, got.split(b'\r\n\r\n', 1)[-1][:300].decode('utf-8', 'replace')
    finally:
        s.close()


def _why(status, body):
    try:
        return json.loads(body).get('error') or 'the share server said %d' % status
    except Exception:
        return 'the share server said %d' % status


def upload(host, sid, key, path=FILE):
    status, body = _send('PUT', host, '/u/' + sid, key, path)
    if not 200 <= status < 300:
        raise OSError(_why(status, body))


def delete(host, sid, key):
    status, body = _send('DELETE', host, '/u/' + sid, key)
    if not (200 <= status < 300 or status == 404):
        raise OSError(_why(status, body))
