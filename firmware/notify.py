"""Phone notifications through Pushover and/or ntfy (runs on CPython and MicroPython).

Both are a single HTTPS POST, checked against ca.pem (Pushover: DigiCert Global Root G2, ntfy.sh: ISRG).
  Pushover: a user key + an application token (pushover.net, one-off app purchase).
  ntfy:     free, no account: subscribe to a hard-to-guess topic in the ntfy app (ntfy.sh, or your own server).
"""
import socket, ssl

POOL = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-'


def _ctx():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.verify_mode = ssl.CERT_REQUIRED
    with open('ca.pem', 'rb') as f:
        ca = f.read()
    try:
        ctx.load_verify_locations(cadata=ca)  # MicroPython: PEM bytes
    except Exception:
        ctx.load_verify_locations(cadata=ca.decode())  # CPython wants PEM as str
    return ctx


def _q(s):
    out = []
    for b in str(s).encode():
        c = chr(b)
        out.append(c if c.isalpha() and b < 128 or c.isdigit() or c in '-_.~' else '%%%02X' % b)
    return ''.join(out)


def _clean(s, n):
    """One line, no control characters (it goes into an HTTP header)."""
    return ''.join(c if ' ' <= c and c != '\x7f' else ' ' for c in str(s))[:n]


def _post(host, path, body, headers, deadline=20):
    import time
    t0 = time.time()
    body = body.encode() if isinstance(body, str) else body
    ai = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0]
    s = socket.socket(ai[0], socket.SOCK_STREAM, ai[2])
    s.settimeout(15)
    try:
        s.connect(ai[-1])
        s = _ctx().wrap_socket(s, server_hostname=host)
        h = 'POST %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: hawki-pico\r\nContent-Length: %d\r\nConnection: close\r\n' % (path, host, len(body))
        for k, v in headers.items():
            h += '%s: %s\r\n' % (k, _clean(v, 200))
        w = s.write if hasattr(s, 'write') else s.sendall
        w((h + '\r\n').encode() + body)
        rd = s.read if hasattr(s, 'read') else s.recv
        head = b''
        while b'\r\n' not in head and len(head) < 2048:
            if time.time() - t0 > deadline:
                raise OSError('%s took too long' % host)
            c = rd(256)
            if not c:
                break
            head += c
        try:
            status = int(head.split(b' ', 2)[1])
        except (IndexError, ValueError):
            raise OSError('no reply from ' + host)
        if not 200 <= status < 300:
            raise OSError('%s said %d' % (host, status))
    finally:
        s.close()


def ok_topic(t):
    t = str(t or '').strip()
    if t and not (6 <= len(t) <= 64 and all(c in POOL for c in t)):
        raise ValueError('ntfy topic: 6 to 64 letters, digits, - or _')
    return t


def ok_host(h):
    h = str(h or '').strip().lower()
    if h.startswith('https://'):
        h = h[8:]
    h = h.rstrip('/')
    if h and not (len(h) <= 80 and '.' in h and all(c.isdigit() or 'a' <= c <= 'z' or c in '.-' for c in h)):
        raise ValueError('ntfy server: a host name like ntfy.sh')
    return h


def ok_key(k, what):
    k = str(k or '').strip()
    if k and not (20 <= len(k) <= 40 and all(c.isdigit() or c.isalpha() and ord(c) < 128 for c in k)):
        raise ValueError(what + ': 30 letters and digits, from pushover.net')
    return k


def channels(n):
    """Which channels are set up in cfg['notify']."""
    n = n or {}
    out = []
    if n.get('po_user') and n.get('po_token'):
        out.append('pushover')
    if n.get('ntfy_topic'):
        out.append('ntfy')
    return out


def send(n, title, msg, urgent=False):
    """Send to every channel set up. Returns {channel: 'ok' or the error}."""
    n = n or {}
    res = {}
    if n.get('po_user') and n.get('po_token'):
        try:
            form = 'token=%s&user=%s&title=%s&message=%s&priority=%d' % (
                _q(n['po_token']), _q(n['po_user']), _q(title), _q(msg), 1 if urgent else 0)
            _post('api.pushover.net', '/1/messages.json', form, {'Content-Type': 'application/x-www-form-urlencoded'})
            res['pushover'] = 'ok'
        except Exception as ex:
            res['pushover'] = str(ex) or repr(ex)
    if n.get('ntfy_topic'):
        try:
            _post(ok_host(n.get('ntfy_host')) or 'ntfy.sh', '/' + ok_topic(n['ntfy_topic']), msg,
                  {'Title': title, 'Priority': '5' if urgent else '3', 'Tags': 'warning' if urgent else 'droplet'})
            res['ntfy'] = 'ok'
        except Exception as ex:
            res['ntfy'] = str(ex) or repr(ex)
    return res
