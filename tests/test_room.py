"""python3 tests/test_room.py - device-list pruning and the TLS out-of-memory retry (firmware/app.py)."""
import ast, os, sys, time, gc
src = open(os.path.join(os.path.dirname(__file__), '..', 'firmware', 'core.py')).read()
tree = ast.parse(src)
want = {'prune_seen', 'make_room', 'with_room', 'is_oom', 'note_oom'}
code = ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want
                   or isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in ('oom_run', 'OOM_UP_S', 'SEEN_MAX', 'SEEN_AGE', 'HAWKI_MAX', 'HAWKI_AGE') for t in n.targets)], [])
now = time.time()
g = {**__import__('_phstub').STUB, 'time': time, 'gc': gc, 'mono_s': lambda: 0, 'installing': [False], 'cfg': {'tanks': {'t1': {}}}, 'hawki': {'nb': {'rx': now}},  # (a HAWKi nearby, heard just now)
     'seen': {'t1': {'last': 0}, 'nb': {'last': 0}, 'old': {'last': now - 3600}, 'new': {'last': now}}}
exec(compile(code, 'app.py', 'exec'), g)
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


g['prune_seen']()
ok(sorted(g['seen']) == ['nb', 'new', 't1'], 'prune drops only devices not heard for 10 min (keeps tanks + HAWKis)')
g['prune_seen'](True)
ok(sorted(g['seen']) == ['nb', 't1'], 'make room drops every other device')
calls = []


def flaky(x):
    calls.append(x)
    if len(calls) == 1:
        raise OSError(12, 'ENOMEM')
    return x * 2


ok(g['with_room'](flaky, 21) == 42 and len(calls) == 2, 'ENOMEM: retried once after making room')
calls.clear()


def broken(x):
    calls.append(x)
    raise OSError(113, 'EHOSTUNREACH')


try:
    g['with_room'](broken, 1)
    ok(False, 'other errors are raised')
except OSError:
    ok(len(calls) == 1, 'other errors are raised straight away, no retry')
calls.clear()


def mem(x):
    calls.append(x)
    raise MemoryError()


try:
    g['with_room'](mem, 1)
except MemoryError:
    ok(len(calls) == 2, 'MemoryError twice: retried once, then given up')
calls.clear()


def notmem(x):
    calls.append(x)
    raise ValueError('not an ENOMEM failure')


try:
    g['with_room'](notmem, 1)
except ValueError:
    ok(len(calls) == 1, 'an error that only mentions ENOMEM is not retried')
g['seen'] = None  # make_room must never stop the action, even if pruning fails
ok(g['with_room'](lambda x: x, 5) == 5, 'make_room failing does not block the action')
sys.exit(1 if fails else 0)
