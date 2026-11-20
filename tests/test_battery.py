"""python3 tests/test_battery.py - the low-battery alert (firmware/app.py battery_check)."""
import ast, asyncio, os, sys, time
src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
tree = ast.parse(src)
keep = [n for n in tree.body if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name in ('battery_check', 'batt_of', 'starting')
        or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in ('BATT_LOW', 'BATT_REARM', 'batt_seen') for t in n.targets)]
sent, saves, msgs = [], [], []


async def send_alert(title, msg, urgent=False, mark=None):
    sent.append(title)
    msgs.append(msg)
    return {'ntfy': g['result']}

g = {'time': time, 'cfg': {}, 'save_cfg': lambda c: saves.append(1), 'send_alert': send_alert, 'result': 'ok'}
exec(compile(ast.Module(keep, []), 'app.py', 'exec'), g)
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


seq = [0]


def feed(levels, n=None, a=None, repeat=1):
    a = {} if a is None else a
    for b in levels:
        seq[0] += 1  # a new hourly measurement (its payload changes) ...
        for _ in range(repeat):  # ... checked every 5 minutes, repeated in between
            asyncio.run(g['battery_check'](n or {'ntfy_topic': 'x'}, 'm', {'name': 'Tank 1'}, {'battery': b, 'raw': 'p%d' % seq[0]}, a))
    return a


a = feed([82, 74, 66])
ok(sent == [], 'above 65%: nothing (82, 74, 66)')
a = feed([65, 64], a=a)
ok(sent == [], 'two low checks in a row: not yet (a cold reading)')
feed([62], a=a)
ok(sent == ['Tank 1: monitor battery low'] and a.get('battery') and '2.74 V' in msgs[-1] and '%' not in msgs[-1], 'third low check: one alert, with the voltage: ' + msgs[-1])
feed([62, 61, 60, 70], a=a)
ok(len(sent) == 1, 'stays quiet while low, and at 70% (not a new battery yet)')
feed([82, 82], a=a)
ok('battery' in a, 'two good readings: not re-armed yet')
feed([82], a=a)
ok('battery' not in a, 'new battery (three readings at 75% or more): armed again')
feed([64, 80, 64, 64], a=a)
ok(len(sent) == 1, 'a dip that recovers resets the count')
feed([64], a=a)
ok(len(sent) == 2, 'three in a row again: alerts again')
sent.clear(); g['result'] = 'failed'; g['batt_seen'].clear()
a = feed([55, 55, 55])
ok(len(sent) == 1 and 'battery' not in a, 'send failed: not marked, so it tries again')
feed([55], a=a)
ok(len(sent) == 2, '... on the next check')
sent.clear(); g['result'] = 'ok'
feed([50, 50, 50, 50], n={'ntfy_topic': 'x', 'battery': False})
ok(sent == [], 'switched off: never')
ok(asyncio.run(g['battery_check']({}, 'm', {}, {}, {})) is None, 'no battery figure: nothing')
g['batt_seen'].clear(); sent.clear()
feed([55], repeat=12)
ok(sent == [], 'one low measurement repeated for an hour: no alert (counts measurements, not checks)')
g['batt_seen'].clear(); sent.clear()
for k in range(4):  # just after a battery change: clock at 0, a placeholder 1 ('3.01 V') until it measures
    asyncio.run(g['battery_check']({'ntfy_topic': 'x'}, 'm2', {'name': 'Tank 1'}, {'battery': 1, 'timestamp': 0, 'raw': 'start%d' % k}, {}))
ok(sent == [] and g['batt_of']({'battery': 1, 'timestamp': 0}) is None and g['batt_of']({'battery': 82, 'timestamp': 1795177120}) == 82,
   'a monitor starting up (clock at 0): its placeholder battery (1%) never counts, never alerts')
ok(g['batt_of']({'battery': 97, 'timestamp': 0}) == 97, 'clock still at 0 but a real battery figure: kept (seen measuring again with its clock at 0)')
sys.exit(1 if fails else 0)
