# Minimal recovery server: joins Wi-Fi (or opens the setup AP) and accepts
#   PUT /file?name=x&t=TOKEN, GET /reboot?t=TOKEN, GET /crash
# After 15 minutes with no request it restarts, so the app gets another go (a passing fault, such as a
# Wi-Fi or memory hiccup at start, doesn't leave the monitor dead until someone pulls the plug).
import json, network, socket, time, machine
IDLE_MS = 15 * 60000


def _load(n):
    try:
        with open(n) as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


cfg = _load('config.json')
tok = cfg.get('token', '') or _load('config.bad').get('token', '')  # (the copy kept of a damaged one)
w = network.WLAN(network.STA_IF)
w.active(True)
if cfg.get('ssid'):
    w.connect(cfg['ssid'], cfg.get('pw', ''))
    for _ in range(30):
        if w.isconnected():
            break
        time.sleep(1)
if not w.isconnected():
    ap = network.WLAN(network.AP_IF)
    ap.config(essid='HAWKi-Rescue', password='oiltanks')
    ap.active(True)
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('0.0.0.0', 80))
s.listen(2)


class Lines:
    """readline() with a 15 s deadline for the whole request and 1 KB per line."""
    def __init__(self, c, t0):
        self.c, self.t0, self.buf = c, t0, b''

    def readline(self):
        while b'\n' not in self.buf:
            if len(self.buf) > 1024 or time.ticks_diff(time.ticks_ms(), self.t0) > 15000:
                raise OSError('bad or slow request')
            d = self.c.recv(256)
            if not d:
                break
            self.buf += d
        i = self.buf.find(b'\n') + 1 or len(self.buf)
        ln, self.buf = self.buf[:i], self.buf[i:]
        return ln


s.settimeout(30)
idle = time.ticks_ms()
while True:
    try:
        c, _ = s.accept()
    except OSError:  # (timed out: nobody asked)
        if time.ticks_diff(time.ticks_ms(), idle) > IDLE_MS:
            machine.reset()
        continue
    idle = time.ticks_ms()
    c.settimeout(10)  # one silent client must not block recovery for everyone
    try:
        t0 = time.ticks_ms()
        f = Lines(c, t0)
        req = f.readline().decode()
        method, path = req.split(' ')[:2]
        n = 0
        t0 = time.ticks_ms()
        for _ in range(30):  # bounded: a client dripping headers can't hold the only slot
            if time.ticks_diff(time.ticks_ms(), t0) > 15000:
                raise OSError('slow request')
            h = f.readline()
            if h in (b'\r\n', b'\n', b''):
                break
            if h.lower().startswith(b'content-length:'):
                n = int(h.split(b':')[1])
        q = {}
        if '?' in path:
            path, qs = path.split('?', 1)
            q = dict(kv.split('=', 1) for kv in qs.split('&') if '=' in kv)
        out = 'rescue mode'
        if path == '/crash':
            try:
                out = open('crash.log').read()
            except Exception:
                out = 'no crash.log'
        elif tok and q.get('t') == tok and path == '/file' and method == 'PUT':
            data = f.buf[:n]  # bytes the line reader already took
            while len(data) < n:
                d = c.recv(min(2048, n - len(data)))
                if not d:
                    raise OSError('short upload')
                data += d
            with open(q['name'], 'wb') as fh:
                fh.write(data)
            out = 'wrote %d' % len(data)
        elif tok and q.get('t') == tok and path == '/reboot':
            c.send(b'HTTP/1.0 200 OK\r\n\r\nrebooting')
            c.close()
            time.sleep(0.5)
            machine.reset()
        c.send(b'HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n' + out.encode())
    except Exception as ex:
        print('rescue err', ex)
    finally:
        c.close()
