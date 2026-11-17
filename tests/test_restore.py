"""python3 tests/test_restore.py - importing a backup (firmware/app.py restore, merge_hist).

All or nothing: a backup with one bad delivery changes nothing. Deliveries come in batches (a tank's 200
receipts don't fit one request on the Pico). An uploaded history must be in time order with sane times, or the
history file is left as it was.
"""
import ast, json, os, struct, sys, tempfile, time

FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.insert(0, FW)
import tankcalc

src = open(os.path.join(FW, 'app.py')).read()
tree = ast.parse(src)
names = ('MODES', 'MEASURED_KEYS', 'isolated_since', 'num', 'opt', 'check_shape', 'set_tank', 'clean_delivery', 'restore_deliveries', 'STAGE', 'restore', 'merge_hist')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


A1, A2 = 'c0:04:56:c4:0c:71', 'c6:76:1b:dc:39:1c'
saves = []
store = {'deliv': {}}


def save_deliv(d):
    store['deliv'] = json.loads(json.dumps(d))


g = {'time': time, 'json': json, 'os': os, 'struct': struct, 'cfg': {'tanks': {}}, 'hawki': {}, 'save_cfg': lambda c: saves.append(1),
     'SHAPES': tankcalc.SHAPES, 'link': tankcalc.link, 'litres_many': tankcalc.litres_many, 'whole': tankcalc.whole, 'above': tankcalc.above, 'restore_groups': tankcalc.restore_groups,
     'load_deliv': lambda: json.loads(json.dumps(store['deliv'])), 'save_deliv': save_deliv}
os.chdir(tempfile.mkdtemp())
g['load_json'] = lambda n, bad: json.load(open(n)) if os.path.exists(n) else {}
g['rm'] = lambda n: os.path.exists(n) and os.remove(n)
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []),
             'app.py', 'exec'), g)
T = {'shape': 'cuboid', 'height_cm': 123, 'length_cm': 173, 'width_cm': 69, 'tank_l': 1306, 'outlet_cm': 9.5}
g['cfg']['tanks'] = {A1: dict(T, name='Tank 1', capacity_l=1180)}
store['deliv'] = {A1: [{'t': 1780000000, 'litres': 500, 'total': None, 'ppl': None, 'supplier': '', 'note': ''}]}
before = json.dumps(g['cfg']['tanks'], sort_keys=True), json.dumps(store['deliv'], sort_keys=True)

# 1. one bad delivery: nothing changes
bad = {'tanks': {A1: dict(T, name='Renamed')}, 'deliveries': {A1: [{'t': 1785000000, 'litres': 900}, {'t': 0, 'litres': 1}]}}
saves.clear()
try:
    g['restore'](bad)
    raised = False
except Exception:
    raised = True
after = json.dumps(g['cfg']['tanks'], sort_keys=True), json.dumps(store['deliv'], sort_keys=True)
ok(raised and after == before and not saves, 'a backup with one bad delivery changes nothing (tanks, deliveries, nothing saved)')
for junk in ({A1: 'oops'}, {A1: [None]}, {A1: [{'litres': 5}]}):
    try:
        g['restore']({'tanks': {A1: dict(T, name='Renamed')}, 'deliveries': junk})
        raised = False
    except Exception:
        raised = True
    ok(raised and json.dumps(g['cfg']['tanks'], sort_keys=True) == before[0], 'deliveries %r: refused, settings unchanged' % (junk,))

# 2. good backup, upper-case keys too
n = g['restore']({'tanks': {A2.upper(): dict(T, name='Tank 2')}, 'deliveries': {A2.upper(): [{'t': 1786000000, 'litres': 300}]}})
ok(A2 in g['cfg']['tanks'] and store['deliv'].get(A2, [{}])[0].get('litres') == 300, 'upper-case MAC keys in a backup are imported')

# 3. deliveries in batches: held aside until the settings request, then everything at once
store['deliv'] = {A1: [{'t': 1600000000, 'litres': 999, 'total': None, 'ppl': None, 'supplier': '', 'note': ''}]}
live = json.dumps(store['deliv'], sort_keys=True)
recs = [{'t': 1700000000 + i * 86400, 'litres': 500, 'ppl': 80, 'total': 400, 'supplier': 'Supplier', 'note': 'x' * 80} for i in range(230)]
ok(len(json.dumps({'deliveries': {A1: recs[:200]}})) > 16000, 'a tank\'s 200 receipts are more than one request (%d bytes)' % len(json.dumps({'deliveries': {A1: recs[:200]}})))
for i in range(0, 230, 50):
    g['restore']({'deliveries': {A1: recs[i:i + 50]}, 'part': 'first' if i == 0 else 'more'})
ok(json.dumps(store['deliv'], sort_keys=True) == live, 'batches are held aside: the receipts already saved are untouched')
g['restore']({'tanks': {A1: dict(T, name='Tank 1')}, 'staged': True})
got = store['deliv'][A1]
ok(len(got) == 200 and got[-1]['t'] == recs[-1]['t'] and got[0]['t'] == recs[30]['t'] and not os.path.exists('deliv.stage'),
   'then the settings request replaces them all at once: the newest 200 kept (%d)' % len(got))
# a bad receipt in a later batch, or a batch that never arrives: nothing changes
store['deliv'] = {A1: [{'t': 1600000000, 'litres': 999, 'total': None, 'ppl': None, 'supplier': '', 'note': ''}]}
live = json.dumps(store['deliv'], sort_keys=True)
g['restore']({'deliveries': {A1: recs[:50]}, 'part': 'first'})
try:
    g['restore']({'deliveries': {A1: [{'t': 0, 'litres': 1}]}, 'part': 'more'})
    ok(False, 'a bad receipt in a later batch is refused')
except ValueError:
    ok(json.dumps(store['deliv'], sort_keys=True) == live, 'a bad receipt in a later batch: refused, the saved receipts untouched')
saves.clear()
try:
    g['restore']({'deliveries': {'aa:aa:aa:aa:aa:aa': recs[:1]}, 'part': 'first'})
    g['restore']({'tanks': {A1: dict(T, name='Renamed')}, 'staged': True})
    ok(False, 'deliveries for a tank that isn\'t in the backup or set up are refused')
except ValueError:
    ok(json.dumps(store['deliv'], sort_keys=True) == live and g['cfg']['tanks'][A1]['name'] == 'Tank 1' and not saves,
       'deliveries for an unknown tank: refused at the end, nothing changed')
g['restore']({'deliveries': {A1: []}, 'part': 'first'})
g['restore']({'tanks': {A1: dict(T, name='Tank 1')}, 'staged': True})
ok(store['deliv'][A1] == [], 'a tank with no deliveries in the backup: its list is cleared')
g['restore']({'deliveries': {A1: [dict(recs[0], litres=1)]}, 'part': 'first'})
g['restore']({'deliveries': {A1: [dict(recs[0], litres=777)]}, 'part': 'more'})
g['restore']({'tanks': {A1: dict(T, name='Tank 1')}, 'staged': True})
ok([x['litres'] for x in store['deliv'][A1]] == [777], 'the same time twice: one receipt, the later one')
g['restore']({'deliveries': {A1: recs[:2]}, 'part': 'first', 'import': 'tabA'})
g['restore']({'deliveries': {A1: recs[5:6]}, 'part': 'first', 'import': 'tabB'})  # a second import starts
for bad in ({'deliveries': {A1: recs[2:3]}, 'part': 'more', 'import': 'tabA'}, {'tanks': {A1: dict(T, name='Tank 1')}, 'staged': True, 'import': 'tabA'}):
    try:
        g['restore'](bad)
        ok(False, 'two imports at once: the older one is refused')
    except ValueError:
        ok(True, 'two imports at once: the older one\'s %s is refused' % ('batch' if 'part' in bad else 'commit'))
g['restore']({'tanks': {A1: dict(T, name='Tank 1')}, 'staged': True, 'import': 'tabB'})
ok([x['t'] for x in store['deliv'][A1]] == [recs[5]['t']], '...and the newer one commits only its own receipts')

# 4. history upload: time order and sane times, or the file is left alone
os.chdir(tempfile.mkdtemp())
NOW = int(time.time())


def write(name, recs):
    with open(name, 'wb') as f:
        for t, mm in recs:
            f.write(struct.pack('<IH', t, mm))


def read(name):
    b = open(name, 'rb').read()
    return [struct.unpack_from('<IH', b, i) for i in range(0, len(b), 6)]


have = [(NOW - 7200, 700), (NOW - 3600, 701)]
for label, up in (('out of time order', [(NOW - 9000, 690), (NOW - 20000, 680)]),
                  ('a time of 0', [(0, 7), (NOW - 9000, 690)]),
                  ('a time far in the future', [(NOW - 9000, 690), (4294967295, 100)])):
    write('h.bin', have)
    write('h.up', up)
    try:
        g['merge_hist']('h.bin', 'h.up')
        raised = False
    except ValueError:
        raised = True
    ok(raised and read('h.bin') == have and not os.path.exists('h.bin.new'), 'history upload %s: refused, history unchanged' % label)
write('h.bin', have)
write('h.up', [(NOW - 20000, 680), (NOW - 7200, 999), (NOW - 100, 702)])
n = g['merge_hist']('h.bin', 'h.up')
ok(read('h.bin') == [(NOW - 20000, 680), (NOW - 7200, 700), (NOW - 3600, 701), (NOW - 100, 702)] and n == 4,
   'a good upload merges in order (existing readings win on the same time)')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
