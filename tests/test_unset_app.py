"""python3 tests/test_unset_app.py - the recorder's side of readings heard with the clock unset (firmware/app.py unset_step)."""
import ast, os, struct, sys, tempfile, types

FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.insert(0, FW)
import unset

src = open(os.path.join(FW, 'core.py')).read()
tree = ast.parse(src)
names = ('hist_name', 'hist_tail', 'merge_hist', 'note_clock', 'unset_step')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


H = 3600
M = 'c0:04:56:c4:0c:71'
clk = {'mono': 0, 'ticks': 0, 'epoch': 1610000000}  # epoch: 2021 until the internet sets it
T = types.SimpleNamespace(time=lambda: clk['epoch'], ticks_ms=lambda: clk['ticks'], ticks_diff=lambda a, b: a - b)
os.chdir(tempfile.mkdtemp())
g = {'os': os, 'struct': struct, 'time': T, 'unset': unset, 'mono_s': lambda: clk['mono'], 'BOOT': 7,
     'cfg': {'tanks': {M: {}}}, 'hawki': {}, 'pending_unset': [], 'clock_set_at': [None], 'gap_from': {}, 'clock_mono': [None], 'anchor': {}, 'hist_busy': [False],
     'last_saved': {}, 'print': lambda *a: None,
     'rm': lambda n: os.path.exists(n) and os.remove(n)}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], []), 'app.py', 'exec'), g)
SYNC = 1795400000
LAST = SYNC - 20 * H
with open(g['hist_name'](M), 'wb') as f:  # history up to when the clock was lost
    for i in range(5):
        f.write(struct.pack('<IH', LAST - (4 - i) * H, 690))


def hist():
    b = open(g['hist_name'](M), 'rb').read()
    return [struct.unpack_from('<IH', b, i) for i in range(0, len(b), 6)]


# 10 hours up with no clock: a reading every hour, queued by the BLE callback with its ticks
for i in range(10):
    clk['mono'], clk['ticks'] = 600 + i * H, (600 + i * H) * 1000
    g['pending_unset'].append((M, clk['ticks'], 0, 700 + i))
    g['unset_step'](clk['epoch'])
ok(len(unset.records(M)) == 10 and len(hist()) == 5, 'clock unset: 10 readings kept aside, history untouched')
# the internet comes back 11 hours after start
clk['mono'], clk['ticks'], clk['epoch'] = 11 * H, 11 * H * 1000, SYNC
g['note_clock'](SYNC)
with open(g['hist_name'](M), 'ab') as f:  # a new reading heard just after the sync, saved before the readings are placed
    f.write(struct.pack('<IH', SYNC + 4, 711))
g['unset_step'](SYNC + 600)  # (and the clock nudged since: the mapping stays the one made at the sync)
h = hist()
ok(len(h) == 16 and [x[1] for x in h[5:15]] == list(range(700, 710)), 'clock set: the 10 readings are in the history, though one was saved since the sync (%d records)' % len(h))
ok(h[5][0] == SYNC - (11 * H - 600) and all(h[i][0] < h[i + 1][0] for i in range(len(h) - 1)), '...at the right times, in order')
ok(unset.records(M) == [], '...and the spool is gone')

# an earlier start's readings wait for a reading after the clock came back (the sensor's clock places them)
unset.add(M, 300, SYNC + 1200 - 6 * H + 1700, 680, boot=6)  # measured 6 hourly steps before the anchor below
clk['epoch'] = SYNC + 600
g['unset_step'](SYNC + 600)
ok(len(unset.records(M)) == 1, 'an earlier start\'s reading waits for one heard after the clock came back')
g['anchor'][M] = (SYNC + 1200, SYNC + 1200 + 1700)  # its first NEW measurement after the sync; its clock is 1700 s ahead
clk['epoch'] = SYNC + 1300
g['unset_step'](SYNC + 1300)
ok(unset.records(M) == [] and (SYNC + 1200 - 6 * H, 680) in hist(), 'then placed by the sensor\'s clock, at its real time (%s)' % ([x for x in hist() if x[1] == 680]))
ok(all(hist()[i][0] < hist()[i + 1][0] for i in range(len(hist()) - 1)), 'history still in order')
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
