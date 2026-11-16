# Minimal recovery server: joins Wi-Fi (or opens the setup AP) and accepts
#   PUT /file?name=x&t=TOKEN, GET /reboot?t=TOKEN, GET /crash
import json, network, socket, time, machine
try:
    cfg = json.load(open('config.json'))
except Exception:
    cfg = {}
tok = cfg.get('token', '')
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
while True:
    c, _ = s.accept()
    try:
        f = c.makefile('rwb', 0)
        req = f.readline().decode()
        method, path = req.split(' ')[:2]
        n = 0
        while True:
            h = f.readline()
            if h in (b'\r\n', b''):
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
        elif q.get('t') == tok and path == '/file' and method == 'PUT':
            data = b''
            while len(data) < n:
                data += c.recv(n - len(data))
            with open(q['name'], 'wb') as fh:
                fh.write(data)
            out = 'wrote %d' % len(data)
        elif q.get('t') == tok and path == '/reboot':
            c.send(b'HTTP/1.0 200 OK\r\n\r\nrebooting')
            c.close()
            time.sleep(0.5)
            machine.reset()
        c.send(b'HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n' + out.encode())
    except Exception as ex:
        print('rescue err', ex)
    finally:
        c.close()
