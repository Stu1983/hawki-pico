"""python3 tests/test_silent.py - the 'monitor gone quiet' alert (firmware/app.py silent_check)."""
import ast, asyncio, os, sys
src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
keep = [n for n in ast.parse(src).body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'silent_check'
        or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in ('SILENT_H', 'quiet_clock') for t in n.targets)
        or isinstance(n, ast.FunctionDef) and n.name == 'quiet_since_start']
sent = []


async def send_alert(title, msg, urgent=False):
    sent.append((title, msg))
    return {'pushover': g['result']}

g = {'cfg': {}, 'save_cfg': lambda c: None, 'send_alert': send_alert, 'result': 'ok'}
exec(compile(ast.Module(keep, []), 'app.py', 'exec'), g)
H, T0 = 3600, 1.8e9
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


def chk(e, now, up=100 * H, a=None, n=None):
    # up: how long the clock-based count has been running (since the first check, or a clock jump)
    a = {} if a is None else a
    asyncio.run(g['silent_check'](n or {'po_user': 'u'}, 'm', {'name': 'Tank 1'}, e, now, now - up, a))
    return a


a = chk({'chg': T0, 'first': T0 - H}, T0 + 5 * H)
ok(sent == [], '5 hours quiet: nothing')
a = chk({'chg': T0, 'first': T0 - H, 'raw': 'old'}, T0 + 6 * H + 60, a=a)
ok(len(sent) == 1 and 'no readings' in sent[0][0] and '6 hours' in sent[0][1] and a.get('silent'), 'over 6 hours: one alert')
chk({'chg': T0, 'raw': 'old'}, T0 + 9 * H, a=a)
ok(len(sent) == 1, 'still quiet: no repeat')
chk({'chg': T0 + 10 * H, 'raw': 'new'}, T0 + 10 * H + 60, a=a)
ok('silent' not in a, 'a new reading: armed again')
chk({'chg': T0 + 10 * H}, T0 + 17 * H, a=a)
ok(len(sent) == 2, 'quiet again for 7 hours: alerts again')
sent.clear()
chk(None, T0, up=2 * H)
ok(sent == [], 'just restarted, not heard yet: waits (counts from the restart)')
chk(None, T0, up=7 * H)
ok(len(sent) == 1, 'restarted 7 hours ago and never heard it: alerts')
sent.clear()
chk({'chg': None, 'first': T0}, T0 + 3 * H, up=3 * H)
ok(sent == [], 'heard once after a restart (reading of unknown age): fine')
chk(None, 1e6, up=20 * H)
ok(sent == [], 'clock not set: nothing')
chk(None, T0, up=20 * H, n={'po_user': 'u', 'silent': False})
ok(sent == [], 'switched off: nothing')
g['result'] = 'failed'
a = chk(None, T0, up=20 * H)
ok(len(sent) == 1 and 'silent' not in a, 'send failed: not marked, tries again next check')
sent.clear(); g['result'] = 'ok'
# restart after an alert, then the SAME payload heard again: not a new reading, stays latched
a = {'silent': int(T0), 'silent_raw': 'old'}
chk({'chg': None, 'first': T0 + H, 'raw': 'old'}, T0 + H + 60, up=60, a=a)
ok(a.get('silent'), 'after a restart, hearing the same old reading again does not re-arm')
# the clock-based start: steady 5-minute checks keep it; a jump (NTP correction) or a long gap restarts it
qs = g['quiet_since_start']
s0 = qs(T0)
ok(qs(T0 + 300) == s0 and qs(T0 + 600) == s0, 'steady checks: the count keeps running')
ok(qs(T0 + 600 + 7 * H) == T0 + 600 + 7 * H, 'clock jumps 7 hours: the count starts again (no false alert)')
ok(qs(T0 + 600 + 8 * H) == T0 + 600 + 8 * H, 'a 1-hour jump also restarts it')
ok(qs(T0) == T0, 'clock goes back: the count starts again')
# clock went back a day after an alert: a changed reading still re-arms (compared by payload, not time)
a = {'silent': int(T0), 'silent_raw': 'old'}
chk({'chg': T0 - 24 * H, 'raw': 'newer'}, T0 - 24 * H + 60, up=60, a=a)
ok('silent' not in a, 'clock went back: a changed reading still re-arms')
sys.exit(1 if fails else 0)
