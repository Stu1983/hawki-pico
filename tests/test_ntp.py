"""python3 tests/test_ntp.py - setting the clock while the internet is down doesn't freeze the web page (firmware/app.py).

Each NTP try looks up a host name, which blocks everything (seconds when DNS is down). With the clock unset the
Wi-Fi keeper used to try every 10 s. Now: 10 s, 1 min, 5 min, then every 15 min, never while a page is loading,
and back to quick tries after a success or a fresh Wi-Fi join.
"""
import ast, asyncio, os, sys, types

src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'app.py')).read()
tree = ast.parse(src)
names = ('ntp_sync', 'ntp_due', 'NTP_BACKOFF', 'ntp_wait', 'web_busy')
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


clock = [0]
tries = []
up = [False]
ntptime = types.ModuleType('ntptime')


def settime():
    tries.append((clock[0], ntptime.host))
    if not up[0]:
        raise OSError(-2, 'no DNS')
ntptime.settime = settime
sys.modules['ntptime'] = ntptime
g = {'asyncio': asyncio, 'mono_s': lambda: clock[0], 'net_proof': lambda: None, 'print': lambda *a: None,
     'page_s': [None]}
exec(compile(ast.Module([n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names
                         or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)], []),
             'app.py', 'exec'), g)
due = g.get('ntp_due', lambda: True)


def keeper(secs):  # the Wi-Fi keeper's clock-unset branch, every 10 s
    end = clock[0] + secs
    while clock[0] < end:
        if due():
            asyncio.run(g['ntp_sync']())
        clock[0] += 10


keeper(3600)
ok(len(tries) <= 2 * 8, 'internet down for an hour: %d tries (was 2 every 10 s = 720)' % len(tries))
gaps = sorted({b[0] - a[0] for a, b in zip(tries, tries[1:]) if b[0] != a[0]})
ok(gaps and max(gaps) == 900, 'tries back off to every 15 minutes: gaps %r' % gaps)

tries.clear()
g['page_s'][0] = clock[0]  # someone just opened the page
g['ntp_wait'][0] = clock[0]  # (a try is due now)
keeper(50)
ok(not tries, 'no try while a page is loading')

up[0] = True
keeper(70)
ok(tries and tries[-1][0] >= 60 and g['ntp_wait'][1] == 0, 'once the page is quiet it tries, and succeeds')
ok(g['ntp_wait'][1] == 0, 'a success starts the backoff again from 10 s')
up[0] = False

# a page open for good (the history page fetches every 10 s): still tried within 5 minutes of being due
tries.clear()
g['ntp_wait'][0] = clock[0]
t0 = clock[0]
end = clock[0] + 1200
while clock[0] < end:
    g['page_s'][0] = clock[0]
    if due():
        asyncio.run(g['ntp_sync']())
    clock[0] += 10
ok(tries and tries[0][0] - t0 <= 300, 'a page loading non-stop puts a try off by at most 5 min (%s s)' % (tries and tries[0][0] - t0))
print('all ok' if not fails else '%d FAILED' % fails)
raise SystemExit(1 if fails else 0)
