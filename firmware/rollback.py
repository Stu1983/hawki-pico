"""Undo an update that won't run, or that was cut off part-way (never replaced over the air).

updater.install() writes upd.pending (the journal) BEFORE replacing anything, then moves each
old file to <name>.bak and the new one into place. undo() works from any point of that:
  <name>.bak exists        -> it's the original: put it back
  <name> wasn't there before -> the update added it: remove it
  otherwise                -> not replaced yet: leave it
main.py calls undo() when upd.pending says the install was interrupted ("swapping"), when the
new version has restarted 3 times without confirming itself, or when it crashes on start. If a file
can't be put back, upd.pending stays so the next boot tries again; an unreadable upd.pending puts back
every backup there is.
upd.last tells the web page what happened.
"""
import json, os


def _exists(n):
    try:
        os.stat(n)
        return True
    except OSError:
        return False


BAD = object()  # upd.pending is there but can't be read (damaged flash): see undo()


def _journal():
    """upd.pending as a dict, None if there is none, or BAD."""
    try:
        f = open('upd.pending')
    except OSError:
        return None
    try:
        with f:
            p = json.load(f)
    except Exception:
        return BAD
    return p if isinstance(p, dict) else BAD


def _ours(n):
    # names the updater makes backups / downloads of (never a history file's .new)
    return n.endswith('.py') or n.endswith('.html') or n.endswith('.pem')


def undo(reason=''):
    """Put the old version back. True once it all is; False (journal kept, so the next boot tries again) if a
    file couldn't be put back, or there's nothing to undo."""
    p = _journal()
    if p is None:
        return False
    if p is BAD:  # which files it lists is lost: put back every backup there is (only an install makes them)
        names = [n[:-4] for n in os.listdir() if n.endswith('.bak') and _ours(n[:-4])]
        p = {'files': names, 'had': names}
    names, had = p.get('files', []), p.get('had', [])
    if p.get('stage') != 'undoing':  # say so first: a rollback cut off part-way is finished at the next boot,
        p['stage'] = 'undoing'       # and the half-restored files can never be confirmed as the new version
        try:
            with open('upd.tmp', 'w') as f:
                json.dump(p, f)
            os.rename('upd.tmp', 'upd.pending')
        except OSError:
            pass
    failed = []
    for n in names:
        try:
            if _exists(n + '.bak'):
                os.rename(n + '.bak', n)
            elif n not in had and _exists(n):
                os.remove(n)
        except OSError:
            failed.append(n)
        try:
            os.remove(n + '.new')
        except OSError:
            pass
    if failed:
        reason = '%s; could not put back %s yet' % (reason, ', '.join(failed))
    else:
        try:
            os.remove('upd.pending')
        except OSError:  # still there: not done (saying done would make main.py restart into the same undo)
            failed.append('upd.pending')
    try:
        with open('upd.last', 'w') as f:
            json.dump({'ok': False, 'from': p.get('from'), 'to': p.get('to'), 'reason': str(reason)[:200]}, f)
    except OSError:
        pass
    return not failed


def boot_check(max_boots=3):
    """Called by main.py before the app starts. Returns a reason to roll back, or None."""
    p = _journal()
    if p is None:
        return None
    if p is BAD:
        return 'the update journal is unreadable (damaged flash?)'
    if p.get('stage') == 'swapping':
        return 'the update was interrupted (power cut?) part-way through'
    if p.get('stage') == 'undoing':
        return 'putting the old version back was interrupted: finishing it'
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
