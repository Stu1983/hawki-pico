"""Undo an update that won't run (never replaced over the air).

updater.install() keeps each replaced file as <name>.bak and writes upd.pending. If the new
version crashes before app.py has confirmed it (upd.pending deleted), main.py calls undo():
the .bak files go back, files the update added are removed, and the Pico restarts on the old
version. upd.last tells the web page what happened.
"""
import json, os


def undo(reason=''):
    try:
        p = json.load(open('upd.pending'))
    except (OSError, ValueError):
        return False
    had = p.get('had', [])
    for n in p.get('files', []):
        try:
            if n in had:
                os.rename(n + '.bak', n)
            else:
                os.remove(n)
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
