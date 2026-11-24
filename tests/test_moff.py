"""python3 tests/test_moff.py - the offset typed into the Magnus app, read from the monitor and added back
(firmware/poke.py read_offset, firmware/app.py moff_*). The Magnus app writes it into the monitor's RANGE_START (1964),
on top of its built-in INTERNAL_OFFSET (1978); the distance the monitor sends is short by the difference."""
import ast, asyncio, os, sys
FW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware')
sys.path.append(FW)
import time
time.ticks_ms = lambda: int(time.monotonic() * 1000)  # (MicroPython's, for poke._session)
time.ticks_diff = lambda a, b: a - b
import poke

fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


def raises(f, *a):
    try:
        f(*a)
    except ValueError:
        return True
    return False


# ---- the values (as the app writes them: a byte, low byte first if two)
ok(poke.le_num(b'\x02') == 2 and poke.le_num(b'\x07') == 7 and poke.le_num(b'\x2c\x01') == 300, 'one byte, or two low first')
ok(raises(poke.le_num, b'') and raises(poke.le_num, b'0138\x00') and raises(poke.le_num, None), 'nothing, or a string (RANGE_STOP\'s form): refused')
ok(poke.offset_cm(2, 2) == 0 and poke.offset_cm(7, 2) == 5 and poke.offset_cm(82, 2) == 80, 'offset = range start - internal (Stu: 2, 2; Conor: 7, 2)')
ok(raises(poke.offset_cm, 1, 2) and raises(poke.offset_cm, 250, 2), 'below the built-in offset, or past 100 cm: refused (never added to readings)')


# ---- a monitor over Bluetooth (the IRQ events poke._session waits for)
class Ble:
    def __init__(self, vals, drop=0):
        self.vals, self.reads, self.writes, self.drop = vals, [], [], drop

    def gap_connect(self, *a):
        if a and a[0] is None:
            return
        if self.drop:
            self.drop -= 1
            self.h(8, (1,))
            return
        self.h(7, (1, 0, b''))

    def gap_disconnect(self, c):
        pass

    def gattc_discover_services(self, c):
        self.h(9, (c, 10, 40, "UUID('00001923-1322-ffdd-3533-886fdadce133')"))
        self.h(10, (c, 0))

    def gattc_discover_characteristics(self, c, a, b):
        for i, k in enumerate(sorted(self.vals)):
            self.h(11, (c, 11 + 2 * i, 12 + 2 * i, 10, "UUID('0000%s-1322-ffdd-3533-886fdadce133')" % k))
        self.h(12, (c, 0))
        self.hs = {12 + 2 * i: k for i, k in enumerate(sorted(self.vals))}

    def gattc_read(self, c, vh):
        self.reads.append(self.hs[vh])
        self.h(15, (c, vh, self.vals[self.hs[vh]]))
        self.h(17, (c, vh, 0))

    def gattc_write(self, *a):
        self.writes.append(a)


def run(ble):
    def hook(f):
        ble.h = f
    async def go():
        return await poke.read_offset(ble, 0, 'd1:0c:fa:a9:e6:1a', hook, asyncio)
    asyncio.sleep_ms = lambda ms: asyncio.sleep(ms / 100000)
    return asyncio.run(go())


b = Ble({'1964': b'\x07', '1978': b'\x02', '1965': b'0138\x00', '1962': b'00796 002 310 0'})
ok(run(b) == (5, 7, 2) and b.reads == ['1964', '1978'] and not b.writes, "Conor's 5 cm: read, nothing written, nothing else read")
b = Ble({'1964': b'\x02', '1978': b'\x02'})
ok(run(b) == (0, 2, 2), "Stu's monitors (2026-11-24): no offset")
b = Ble({'1964': b'\x02'})
try:
    run(b)
    ok(False, 'no INTERNAL_OFFSET characteristic: an error')
except OSError as ex:
    ok('1978' in str(ex), 'no INTERNAL_OFFSET characteristic: an error, nothing guessed (%s)' % ex)

# ---- app.py: when it's read, and what's kept
src = open(os.path.join(FW, 'app.py')).read()
keep = [n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name in ('moff_due', 'moff_set', 'moff_view')
        or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in ('MOFF_EVERY_S', 'MOFF_AGAIN_S') for t in n.targets)]
saves = []
g = {'MIN_MM': 30, 'hawki': {'m1': {'level': 800}}, 'cfg': {'tanks': {'m1': {}}}, 'moff_info': {}, 'moff_want': set(), 'moff_try': {}, 'moff_seen': {},
     'save_cfg': lambda c: saves.append(dict(c.get('moff') or {}))}
exec(compile(ast.Module(keep, []), 'app.py', 'exec'), g)
due = g['moff_due']
ok(due('m1', 100), 'never read on this start: due')
g['moff_try']['m1'] = 100
ok(not due('m1', 100 + 3600) and due('m1', 100 + 86400), 'read: again a day later')
g['moff_info']['m1'] = {'err': 'no conn'}
ok(not due('m1', 100 + 3599) and due('m1', 100 + 3600), 'a failed read: again an hour later')
g['moff_info']['m1'] = {'got': (5, 7, 2)}
g['moff_want'].add('m1')
ok(due('m1', 101), 'asked for (Read it again): due at once')
g['moff_set']('m1', 5, 1000)
g['moff_set']('m1', 5, 2000)
ok(len(saves) == 1 and g['cfg']['moff']['m1'] == {'cm': 5, 'at': 1000}, 'the settings written only when it changes')
ok(g['hawki']['m1']['level'] == 850, 'the last distance heard moves with it (odd_empty compares the next one with it)')
ok(g['moff_view']('m1') == {'cm': 5, 'read': 2000} and g['moff_view']('m2') is None, 'shown: the offset and when it was last read')
g['moff_set']('m1', 0, 3000)
ok(len(saves) == 2 and g['cfg']['moff']['m1']['cm'] == 0, 'taken off in the Magnus app: 0 kept (and shown as none)')
ok(g['hawki']['m1']['level'] == 800, '... and the last distance heard moves back')

# the advert: added back only to a real distance, before the misread checks
i = src.index("mo = (cfg.get('moff') or {}).get(k)")
ok(i < src.index("if lv is None or lv == 16383 or lv < MIN_MM") and "lv is not None and MIN_MM <= lv < 16382" in src[i:i + 200]
   and "lv = d['level'] = lv + 10 * mo['cm']" in src[i:i + 300], "added back to the advert's distance (not to 'unknown', 'empty' or a blind-zone misread such as 0 mm), before it is judged or saved")
j = src.index("path == '/api/tank/delete'")
ok(all(x in src[j:j + 1200] for x in ('moff_info.pop(dm', 'moff_want.discard(dm', 'moff_try.pop(dm', 'moff_seen.pop(dm', "cfg.get('moff') or {}).pop(dm")),
   'a deleted tank forgets its offset and when it was read (added again: read at once)')
ok("'/api/tank/offset'" in src.split('MUTATING = ')[1].split(')')[0], 'Read it again needs the PIN like any other change')
sys.exit(1 if fails else 0)
