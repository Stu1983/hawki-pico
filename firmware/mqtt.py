"""Home Assistant over MQTT: the packets (MQTT 3.1.1, publish only) and HA's discovery messages.
Runs on CPython and MicroPython; the sending is done by app.py's mqtt_task.

HA finds one device per tank by itself (MQTT discovery), with its sensors. Entity ids are kept as
sensor.hawki_<last 4 of the MAC>_<what>, the names the old NAS bridge used, so dashboards keep working.

Topics (P = 'hawki/' + the Pico's own MAC, no colons):
  P/status            online / offline (retained; offline is the broker's 'last will' if the Pico vanishes)
  P/<tank mac>/state  JSON of that tank's readings (retained)
  P/<tank mac>/avail  online, or offline when the sensor hasn't been heard for 90 minutes
  homeassistant/sensor/<id>/config   the discovery messages (retained; empty = remove)
"""
import json, time

KEEPALIVE = 120
STALE_S = 5400  # a sensor not heard for 90 minutes: its values show as unavailable in HA


def _s(b):
    b = b.encode() if isinstance(b, str) else b
    return bytes((len(b) >> 8, len(b) & 255)) + b


def _len(n):
    out = bytearray()
    while True:
        d = n % 128
        n //= 128
        out.append(d | (128 if n else 0))
        if not n:
            return bytes(out)


def connect_pkt(client_id, user=None, pw=None, will_topic=None, will_msg=b'', keepalive=KEEPALIVE):
    flags = 0x02  # clean session
    pay = _s(client_id)
    if will_topic:
        flags |= 0x04 | 0x20  # will, retained, QoS 0
        pay += _s(will_topic) + _s(will_msg)
    if user:
        flags |= 0x80
        pay += _s(user)
        if pw:
            flags |= 0x40
            pay += _s(pw)
    var = _s('MQTT') + bytes((4, flags, keepalive >> 8, keepalive & 255))
    return b'\x10' + _len(len(var) + len(pay)) + var + pay


def publish_pkt(topic, payload, retain=True):
    t = _s(topic)
    p = payload.encode() if isinstance(payload, str) else payload
    return bytes((0x31 if retain else 0x30,)) + _len(len(t) + len(p)) + t + p


PING = b'\xc0\x00'
DISCONNECT = b'\xe0\x00'

CONNACK_ERR = {1: 'the broker does not speak MQTT 3.1.1', 2: 'client id refused', 3: 'broker unavailable',
               4: 'wrong username or password', 5: 'not allowed: check the username and password'}


def connack(b):
    """None if the CONNACK says connected, else the reason."""
    if len(b) != 4 or b[0] != 0x20 or b[1] != 2:
        return 'not an MQTT broker'
    return None if b[3] == 0 else CONNACK_ERR.get(b[3], 'refused (%d)' % b[3])


def clean(b, old=None):
    """{'host','port','user','pw'} from the form, or ValueError. A blank password keeps the saved one, but only
    for the same broker and username (it's never sent anywhere new without being typed in again)."""
    host = str(b.get('host') or '').strip()
    if not host or len(host) > 64 or any(c in host for c in ' /:@'):
        raise ValueError('broker: the address of Home Assistant (or your MQTT broker), e.g. 192.168.1.50')
    try:
        port = int(b.get('port') or 1883)
    except (TypeError, ValueError):
        port = 0
    if not 1 <= port <= 65535:
        raise ValueError('port: a number, usually 1883')
    user = str(b.get('user') or '').strip()[:64]
    pw = str(b.get('pw') or '')
    if not pw and old and old.get('user') == user and old.get('host') == host and old.get('port') == port:
        pw = old.get('pw', '')
    return {'host': host, 'port': port, 'user': user, 'pw': pw[:128]}


def nomac(mac):
    return mac.replace(':', '').lower()


# what each tank shows in HA: key in the state JSON, name, unit, device_class, state_class, category, icon
SENSORS = (
    ('litres', 'Usable oil', 'L', 'volume_storage', 'measurement', None, 'mdi:barrel'),
    ('total', 'All oil', 'L', 'volume_storage', 'measurement', None, 'mdi:barrel-outline'),
    ('percent', 'Level', '%', None, 'measurement', None, 'mdi:oil-level'),
    ('distance', 'Distance to oil', 'mm', 'distance', 'measurement', 'diagnostic', 'mdi:hydraulic-oil-level'),
    ('battery', 'Sensor battery', '%', 'battery', 'measurement', 'diagnostic', None),
    ('rssi', 'Sensor signal', 'dBm', 'signal_strength', 'measurement', 'diagnostic', None),
    ('read_at', 'Last reading', None, 'timestamp', None, 'diagnostic', None),
    ('order_by', 'Order by', None, 'timestamp', None, None, 'mdi:calendar-clock'),  # (the dashboard's order date)
)


def discovery(pico, tank_mac, name, version, prefix='homeassistant'):
    """[(topic, payload)] of the discovery messages for one tank."""
    base = 'hawki/' + pico
    tm = nomac(tank_mac)
    out = [('%s/sensor/hawki_pico_%s/config' % (prefix, pico), json.dumps({  # the Pico itself
        'name': 'Wi-Fi signal', 'unique_id': 'hawki_pico_%s_wifi' % pico, 'state_topic': base + '/pico',
        'value_template': '{{ value_json.wifi }}', 'unit_of_measurement': 'dBm', 'device_class': 'signal_strength',
        'state_class': 'measurement', 'entity_category': 'diagnostic', 'availability_topic': base + '/status',
        'device': {'identifiers': ['hawki_pico_' + pico], 'name': 'Oil Monitor', 'manufacturer': 'DIY',
                   'model': 'Pico 2 W HAWKi monitor', 'sw_version': version}}))]
    dev = {'identifiers': ['hawki_' + tm], 'name': name, 'manufacturer': 'Magnus', 'model': 'HAWKi oil sensor',
           'via_device': 'hawki_pico_' + pico}
    for key, label, unit, dc, sc, cat, icon in SENSORS:
        uid = 'hawki_%s_%s' % (tm, key)
        c = {'name': label, 'unique_id': uid, 'default_entity_id': 'sensor.hawki_%s_%s' % (tm[-4:], key),
             'state_topic': '%s/%s/state' % (base, tm), 'value_template': '{{ value_json.%s }}' % key,
             'availability': [{'topic': base + '/status'}, {'topic': '%s/%s/avail' % (base, tm)}],
             'availability_mode': 'all', 'device': dev}
        for k, v in (('unit_of_measurement', unit), ('device_class', dc), ('state_class', sc),
                     ('entity_category', cat), ('icon', icon)):
            if v:
                c[k] = v
        if key == 'distance':
            c['json_attributes_topic'] = c['state_topic']
            c['json_attributes_template'] = '{{ {"misread": value_json.misread} | tojson }}'
        out.append(('%s/sensor/%s/config' % (prefix, uid), json.dumps(c)))
        dev = {'identifiers': ['hawki_' + tm]}  # the full device once is enough
    return out


def removal(tank_mac, pico, prefix='homeassistant'):
    """Empty retained messages: HA removes that tank's sensors, and the broker forgets its last readings."""
    tm = nomac(tank_mac)
    base = 'hawki/%s/%s' % (pico, tm)
    return [('%s/sensor/hawki_%s_%s/config' % (prefix, tm, s[0]), '') for s in SENSORS] + [
        (base + '/state', ''), (base + '/avail', '')]


def state(v, now):
    """The state JSON for one tank from app.tank_view(); None values show as 'unknown' in HA."""
    read_at = None
    if now > 1700000000 and v.get('good_at'):  # when it measured, not when last heard (none if heard before the
        t = int(v['good_at'])                    # clock was set: that time can't be trusted)
        y, mo, d, h, mi, s = time.gmtime(t)[:6]
        read_at = '%04d-%02d-%02dT%02d:%02d:%02d+00:00' % (y, mo, d, h, mi, s)
    r = lambda x, n=0: None if x is None else (round(x) if n == 0 else round(x, n))
    return {'litres': r(v.get('litres')), 'total': r(v.get('total')), 'percent': r(v.get('percent'), 1),
            'distance': None if v.get('level') in (16382, 16383) else v.get('level'),  # (codes, not distances)
            'battery': v.get('battery'), 'rssi': v.get('rssi'), 'read_at': read_at,
            'order_by': v.get('order_by'),
            'misread': v.get('misread') is not None}


def avail(v):
    return 'online' if v.get('age') is not None and v['age'] < STALE_S else 'offline'
