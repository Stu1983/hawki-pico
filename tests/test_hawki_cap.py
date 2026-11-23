"""python3 tests/test_hawki_cap.py - adverts with the HAWKi service id can't fill the Pico's memory (firmware/app.py irq).

The device list is capped (SEEN_MAX) and old devices pruned, but anything carrying the HAWKi id skipped the cap so a
new sensor is never shut out - and was then kept for good. A transmitter in radio range sending that id from
ever-changing addresses grew both lists until the heap ran out. Now: at most HAWKI_MAX HAWKis that aren't set up as
tanks, and those not heard for 15 minutes are dropped; set-up tanks are never dropped or shut out.
"""
import ast, binascii, os, sys, time, types

FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.insert(0, FW)
import hawki_decode

src = open(os.path.join(FW, 'app.py')).read()
tree = ast.parse(src)
names = ('HAWKI_UUID', 'SEEN_MAX', 'SEEN_AGE', 'HAWKI_MAX', 'HAWKI_AGE', 'MIN_MM', 'EMPTY_NEAR_MM', 'EMPTY_WAIT', 'odd_empty', 'hx', 'name_of', 'hawki_room', 'irq', 'prune_seen')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


clock = [1790000000.0]
T = types.SimpleNamespace(time=lambda: clock[0])
TANK = 'c0:04:56:c4:0c:71'
g = {'binascii': binascii, 'time': T, 'decode': hawki_decode.decode, 'mfr_from_adv': hawki_decode.mfr_from_adv,
     'cfg': {'tanks': {TANK: {}}}, 'hawki': {}, 'seen': {}, 'pending': [], 'pending_unset': [], 'unset_raw': {}, 'anchor': {}, 'anchor_base': {},
     'listener': types.SimpleNamespace(heard=lambda *a: None, seed=lambda *a: None), 'clk_seeded': set(), 'pending_clk': [], 'ntp_ok': [True],
     'clocklog': types.SimpleNamespace(offsets=lambda *a: [])}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []),
             'app.py', 'exec'), g)
ADV = bytes.fromhex('110733e1dcda6f883335ddff2213231900000bff438fa4afd62b00f00113')
mac = lambda i: bytes([0xd0, 0, 0, (i >> 16) & 255, (i >> 8) & 255, i & 255])
for i in range(1000):  # a spoofer: the HAWKi id from 1000 addresses
    g['irq'](5, (0, mac(i), 0, -60, ADV))
    if i % 100 == 0:
        clock[0] += 60
        g['prune_seen']()
spare = [k for k in g['hawki'] if k not in g['cfg']['tanks']]
print('    hawki %d, seen %d' % (len(g['hawki']), len(g['seen'])))
ok(len(spare) <= g.get('HAWKI_MAX', 8) and len(g['seen']) <= g['SEEN_MAX'] + g.get('HAWKI_MAX', 8),
   'a spoofer from 1000 addresses: lists stay small (hawki %d, seen %d)' % (len(g['hawki']), len(g['seen'])))
g['irq'](5, (0, bytes.fromhex(TANK.replace(':', '')), 0, -60, ADV))
ok(TANK in g['hawki'], 'a set-up tank is still heard while the lists are full')
clock[0] += 16 * 60
g['prune_seen']()
ok(not [k for k in g['hawki'] if k not in g['cfg']['tanks']], 'HAWKis that aren\'t tanks: dropped after 15 minutes unheard')
ok(TANK in g['hawki'], 'the set-up tank is never dropped')
g['irq'](5, (0, mac(5000), 0, -60, ADV))
ok(binascii.hexlify(mac(5000), ':').decode() in g['hawki'], 'and a new sensor nearby is heard again once there is room')
# Codex: a spoofer refreshing 8 addresses every minute must not keep Stu's real second sensor out
g['hawki'].clear(); g['seen'].clear()
REAL = bytes.fromhex('c6761bdc391c')
for minute in range(30):
    for i in range(8):
        g['irq'](5, (0, mac(9000 + i), 0, -60, ADV))
    for s4 in range(15):  # the real sensor: every 4 s
        clock[0] += 4
        g['irq'](5, (0, REAL, 0, -70, ADV))
    g['prune_seen']()
ok('c6:76:1b:dc:39:1c' in g['hawki'], 'a spoofer refreshing 8 addresses every minute: the real second sensor is still listed')
# Codex: the HAWKi id without manufacturer data never becomes a HAWKi, so it must not get past the device cap
g['hawki'].clear(); g['seen'].clear()
bare = bytes.fromhex('110733e1dcda6f883335ddff22132319000000')
for i in range(1000):
    g['irq'](5, (0, mac(20000 + i), 0, -60, bare))
ok(len(g['seen']) <= g['SEEN_MAX'], 'the HAWKi id with no data from 1000 addresses: device list stays capped (%d)' % len(g['seen']))
# readings heard while the clock was unset are placed by an anchor: the first NEW measurement after the sync
g['hawki'].clear(); g['seen'].clear(); g['anchor'].clear()
raw = ADV[-10:].hex()
g['unset_raw'][TANK] = raw  # the payload last heard while the clock was unset
g['irq'](5, (0, bytes.fromhex(TANK.replace(':', '')), 0, -60, ADV))
ok(TANK not in g['anchor'], 'the same measurement heard again after the sync is not an anchor (it was measured before)')
g['unset_raw'][TANK] = 'something else'
g['irq'](5, (0, bytes.fromhex(TANK.replace(':', '')), 0, -60, ADV))
ok(g['anchor'].get(TANK, (0, 0))[1] == 1794787572, 'a new measurement after the sync is, with the sensor\'s own time')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
