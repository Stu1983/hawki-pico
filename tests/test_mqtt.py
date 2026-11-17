import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware'))
import mqtt


def test_packets():
    # CONNECT, checked byte for byte against the MQTT 3.1.1 spec layout
    p = mqtt.connect_pkt('c', 'u', 'p', 'w', b'x', keepalive=60)
    assert p == (b'\x10\x19' + b'\x00\x04MQTT\x04' + bytes((0x80 | 0x40 | 0x20 | 0x04 | 0x02,)) + b'\x00\x3c'
                 + b'\x00\x01c' + b'\x00\x01w' + b'\x00\x01x' + b'\x00\x01u' + b'\x00\x01p'), p
    assert mqtt.connect_pkt('c')[9] == 0x02  # no login, no will: clean session only
    assert mqtt.publish_pkt('a/b', 'hi') == b'\x31\x07\x00\x03a/bhi'
    assert mqtt.publish_pkt('a', b'', retain=False) == b'\x30\x03\x00\x01a'
    big = mqtt.publish_pkt('t', 'x' * 300)  # remaining length over 127: two bytes
    assert big[1:3] == bytes((303 % 128 | 128, 303 // 128)) and len(big) == 3 + 303
    assert mqtt.connack(b'\x20\x02\x00\x00') is None
    assert 'username' in mqtt.connack(b'\x20\x02\x00\x05') and 'username' in mqtt.connack(b'\x20\x02\x00\x04')
    assert mqtt.connack(b'HTTP') == 'not an MQTT broker'


def test_clean():
    c = mqtt.clean({'host': ' 192.168.1.235 ', 'user': 'hawki', 'pw': 'secret'})
    assert c == {'host': '192.168.1.235', 'port': 1883, 'user': 'hawki', 'pw': 'secret'}
    assert mqtt.clean({'host': '192.168.1.235', 'user': 'hawki'}, c)['pw'] == 'secret'  # blank keeps it
    assert mqtt.clean({'host': '192.168.1.235', 'user': 'other'}, c)['pw'] == ''  # but not for a different user,
    assert mqtt.clean({'host': '192.168.1.9', 'user': 'hawki'}, c)['pw'] == ''  # or broker: never sent anywhere new
    assert mqtt.clean({'host': '192.168.1.235', 'port': 1884, 'user': 'hawki'}, c)['pw'] == ''
    for bad in ({'host': ''}, {'host': 'http://ha'}, {'host': 'a b'}, {'host': 'h', 'port': '0'},
                {'host': 'h', 'port': 'x'}, {'host': 'h', 'port': 70000}):
        try:
            mqtt.clean(bad)
            assert False, bad
        except ValueError:
            pass


def test_discovery():
    d = mqtt.discovery('28cdc1aabbcc', 'C0:04:56:C4:0C:71', 'Tank "1"', '1.2.53')
    topics = [t for t, _ in d]
    assert topics[0] == 'homeassistant/sensor/hawki_pico_28cdc1aabbcc/config'
    assert len(d) == 1 + len(mqtt.SENSORS)
    by = {json.loads(p)['unique_id']: json.loads(p) for _, p in d}
    lit = by['hawki_c00456c40c71_litres']
    # the old NAS bridge's entity ids, so dashboards and automations keep working
    for k in ('litres', 'percent', 'distance', 'battery'):
        assert by['hawki_c00456c40c71_' + k]['default_entity_id'] == 'sensor.hawki_0c71_' + k
    assert lit['state_topic'] == 'hawki/28cdc1aabbcc/c00456c40c71/state'
    assert lit['device']['name'] == 'Tank "1"' and lit['device']['via_device'] == 'hawki_pico_28cdc1aabbcc'
    assert lit['availability_mode'] == 'all' and len(lit['availability']) == 2
    assert by['hawki_c00456c40c71_battery']['entity_category'] == 'diagnostic'
    assert all(t.endswith('/config') for t in topics)
    rm = mqtt.removal('c0:04:56:c4:0c:71', '28cdc1aabbcc')
    assert [t for t, _ in rm][:-2] == topics[1:] and all(p == '' for _, p in rm)
    assert [t for t, _ in rm][-2:] == ['hawki/28cdc1aabbcc/c00456c40c71/state', 'hawki/28cdc1aabbcc/c00456c40c71/avail']


def test_state():
    v = {'litres': 502.3, 'total': 601.6, 'percent': 41.64, 'level': 716, 'battery': 62, 'rssi': -86, 'age': 60,
         'misread': None}
    s = mqtt.state(dict(v, good_at=1794935000), 1794935060)
    assert mqtt.state(v, 1794935060)['read_at'] is None  # no measurement time (heard before the clock was set)
    assert s == {'litres': 502, 'total': 602, 'percent': 41.6, 'distance': 716, 'battery': 62, 'rssi': -86,
                 'read_at': '2026-11-17T17:03:20+00:00', 'order_by': None, 'misread': False}, s
    ob = mqtt.state(dict(v, order_by='2026-12-16T02:13:20+00:00'), 1794935060)['order_by']
    assert ob == '2026-12-16T02:13:20+00:00', ob  # the dashboard's order date, as a timestamp HA shows in local time
    disc = [json.loads(p) for t, p in mqtt.discovery('pico1', 'c0:04:56:c4:0c:71', 'Tank 1', '1.2.54') if 'order_by' in t]
    assert disc and disc[0]['device_class'] == 'timestamp' and disc[0]['default_entity_id'] == 'sensor.hawki_0c71_order_by', disc
    heard_later = mqtt.state(dict(v, good_at=1794931400), 1794935060)  # measured 16:03, re-heard since
    assert heard_later['read_at'] == '2026-11-17T16:03:20+00:00', heard_later
    none = mqtt.state({'age': None, 'misread': -1}, 1794935060)
    assert none['litres'] is None and none['read_at'] is None and none['misread'] is True
    assert json.dumps(none)  # nulls go out as JSON null: HA shows 'unknown'
    assert mqtt.avail({'age': 60}) == 'online' and mqtt.avail({'age': 6000}) == 'offline'
    assert mqtt.avail({'age': None}) == 'offline'


if __name__ == '__main__':
    test_packets(); test_clean(); test_discovery(); test_state()
    print('all ok')
