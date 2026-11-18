"""python3 tests/test_battery.py - the low-battery alert (firmware/app.py battery_check)."""
import ast, asyncio, os, sys, time
src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
tree = ast.parse(src)
keep = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'battery_check'
        or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in ('BATT_LOW', 'BATT_REARM', 'batt_seen') for t in n.targets)]
sent, saves = [], []


async def send_alert(title, msg, urgent=False, mark=None):
    sent.append(title)
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


a = feed([62, 50, 25])
ok(sent == [], 'above 20%: nothing')
a = feed([20, 19], a=a)
ok(sent == [], 'two low checks in a row: not yet (a cold reading)')
feed([18], a=a)
ok(sent == ['Tank 1: monitor battery low'] and a.get('battery'), 'third low check: one alert')
feed([18, 17, 15, 30], a=a)
ok(len(sent) == 1, 'stays quiet while low, and at 30% (not a new battery yet)')
feed([90, 90], a=a)
ok('battery' in a, 'two good readings: not re-armed yet')
feed([90], a=a)
ok('battery' not in a, 'new battery (three readings >= 40%): armed again')
feed([19, 50, 19, 19], a=a)
ok(len(sent) == 1, 'a dip that recovers resets the count')
feed([19], a=a)
ok(len(sent) == 2, 'three in a row again: alerts again')
sent.clear(); g['result'] = 'failed'; g['batt_seen'].clear()
a = feed([10, 10, 10])
ok(len(sent) == 1 and 'battery' not in a, 'send failed: not marked, so it tries again')
feed([10], a=a)
ok(len(sent) == 2, '... on the next check')
sent.clear(); g['result'] = 'ok'
feed([5, 5, 5, 5], n={'ntfy_topic': 'x', 'battery': False})
ok(sent == [], 'switched off: never')
ok(asyncio.run(g['battery_check']({}, 'm', {}, {}, {})) is None, 'no battery figure: nothing')
g['batt_seen'].clear(); sent.clear()
feed([10], repeat=12)
ok(sent == [], 'one low measurement repeated for an hour: no alert (counts measurements, not checks)')
sys.exit(1 if fails else 0)
