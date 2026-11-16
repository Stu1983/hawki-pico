"""Undo an update that won't run, or that was cut off part-way (never replaced over the air).

updater.install() writes upd.pending (the journal) BEFORE replacing anything, then moves each
old file to <name>.bak and the new one into place. undo() works from any point of that:
  <name>.bak exists        -> it's the original: put it back
  <name> wasn't there before -> the update added it: remove it
  otherwise                -> not replaced yet: leave it
main.py calls undo() when upd.pending says the install was interrupted ("swapping"), when the
new version has restarted 3 times without confirming itself, or when it crashes on start.
upd.last tells the web page what happened.
"""
import json, os


def _exists(n):
    try:
        os.stat(n)
        return True
    except OSError:
        return False


def undo(reason=''):
    try:
        p = json.load(open('upd.pending'))
    except (OSError, ValueError):
        return False
    had = p.get('had', [])
    for n in p.get('files', []):
        try:
            if _exists(n + '.bak'):
                os.rename(n + '.bak', n)
            elif n not in had and _exists(n):
                os.remove(n)
        except OSError:
            pass
        try:
            os.remove(n + '.new')
        except OSError:
            pass
    try:
        os.remove('upd.pending')
    except OSError:
        pass
    try:
        with open('upd.last', 'w') as f:
            json.dump({'ok': False, 'from': p.get('from'), 'to': p.get('to'), 'reason': str(reason)[:200]}, f)
    except OSError:
        pass
    return True


def boot_check(max_boots=3):
    """Called by main.py before the app starts. Returns a reason to roll back, or None."""
    try:
        p = json.load(open('upd.pending'))
    except (OSError, ValueError):
        return None
    if p.get('stage') == 'swapping':
        return 'the update was interrupted (power cut?) part-way through'
    p['boots'] = p.get('boots', 0) + 1
    if p['boots'] > max_boots:
        return 'the new version restarted %d times without starting properly' % (p['boots'] - 1)
    try:
        with open('upd.tmp', 'w') as f:
            json.dump(p, f)
        os.rename('upd.tmp', 'upd.pending')
    except OSError:
        pass
    return None
