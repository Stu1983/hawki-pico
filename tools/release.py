#!/usr/bin/env python3
"""Make a release that every Pico can install from its web page.

    python3 tools/release.py 1.0.1 "What's new, in a sentence or two"

Runs the tests, writes firmware/version.py and manifest.json: a body listing the SHA-256 + size
of each file the Pico downloads, SIGNED with the release key (RSA-2048, PKCS#1 v1.5, SHA-256).
Picos only install a body whose signature matches the public key built into updater.py.
Key: $HAWKI_RELEASE_KEY, default ~/.config/hawki-release/release_key.pem (keep it secret and
backed up; losing it means Picos can only be updated over USB).
Then commit, tag and push it, exactly as printed; `release.py --check vX.Y.Z` (after tagging, before pushing)
checks the tagged files are the ones the manifest signs.
"""
import hashlib, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FW = os.path.join(ROOT, 'firmware')
KEEP = ('main.py', 'rescue.py', 'rollback.py', 'boot.py')  # boot path: installed by USB only, never over the air
KEY = os.environ.get('HAWKI_RELEASE_KEY', os.path.expanduser('~/.config/hawki-release/release_key.pem'))


def vt(v):
    return tuple(int(x) for x in v.split('.'))


def build(ver, notes, key, fw=FW):
    """The manifest text for the files in fw, signed with key."""
    files = {}
    for n in sorted(os.listdir(fw)):
        p = os.path.join(fw, n)
        if n in KEEP or not os.path.isfile(p) or not n.endswith(('.py', '.html', '.pem')):
            continue
        b = open(p, 'rb').read()
        files[n] = [hashlib.sha256(b).hexdigest(), len(b)]
    m = {'version': ver, 'ref': 'v' + ver, 'notes': notes, 'files': files}
    body = json.dumps(m, sort_keys=True)
    with tempfile.NamedTemporaryFile('wb', delete=False) as t:
        t.write(body.encode())
    try:
        sig = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', key, t.name], check=True,
                             capture_output=True).stdout.hex()
    finally:
        os.remove(t.name)
    # top-level fields only for Picos still on 1.0.x (they predate signing); 1.1+ trust 'signed' only
    return json.dumps(dict(m, signed={'body': body, 'sig': sig}), indent=1) + '\n'


def check_text(text):
    """Everything a Pico checks before installing, done with the Pico's own code: refuse to publish a release
    that every Pico would refuse (a file over 200 KB or empty, a manifest over 20 KB, a name it may not write,
    a signature that doesn't match the key in updater.py)."""
    if FW not in sys.path:
        sys.path.insert(0, FW)
    import updater
    if len(text.encode()) > 20000:  # (updater.check fetches the manifest with limit=20000)
        raise ValueError('manifest.json is %d bytes: Picos only read 20000' % len(text.encode()))
    return updater.parse(text)


def keep_changed(old):
    """Start-up files changed since the last release (they never go over the air: USB or maintenance upload)."""
    out = []
    for n in KEEP:
        r = subprocess.run(['git', 'diff', '--quiet', 'v' + old, '--', 'firmware/' + n], cwd=ROOT)
        if r.returncode == 1:
            out.append(n)
    return out


def check_tag(tag):
    """After tagging, before pushing: the tag's own manifest is signed and valid, and the files at the tag are
    exactly the ones it lists (none different, none missing, none extra)."""
    git = lambda *a: subprocess.run(['git'] + list(a), cwd=ROOT, capture_output=True)
    r = git('show', '%s:manifest.json' % tag)
    if r.returncode:
        sys.exit('no manifest.json at ' + tag)
    m = check_text(r.stdout.decode())
    bad = []
    for n, (sha, size) in m['files'].items():
        b = git('show', '%s:firmware/%s' % (tag, n)).stdout
        if hashlib.sha256(b).hexdigest() != sha or len(b) != size:
            bad.append(n)
    at_tag = {p.rsplit('/', 1)[1] for p in git('ls-tree', '--name-only', tag, 'firmware/').stdout.decode().split()}
    extra = sorted(n for n in at_tag if n not in KEEP and n.endswith(('.py', '.html', '.pem')) and n not in m['files'])
    bad += ['%s (not in the manifest)' % n for n in extra]
    if m['ref'] != tag:
        bad.append('ref %s != %s' % (m['ref'], tag))
    if bad:
        sys.exit('the tag does not match its signed manifest: ' + ', '.join(bad))
    print('%s matches its signed manifest (%d files)' % (tag, len(m['files'])))


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--check':
        return check_tag(sys.argv[2])
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    ver, notes = sys.argv[1].lstrip('v'), sys.argv[2]
    if not os.path.exists(KEY):
        sys.exit('release key not found: ' + KEY)
    old = json.load(open(os.path.join(ROOT, 'manifest.json')))['version'] if os.path.exists(os.path.join(ROOT, 'manifest.json')) else '0.0.0'
    if vt(ver) <= vt(old):
        sys.exit('version %s must be newer than %s' % (ver, old))
    for t in sorted(os.listdir(os.path.join(ROOT, 'tests'))):
        if t.startswith('test_') and t.endswith('.py'):
            subprocess.run([sys.executable, os.path.join(ROOT, 'tests', t)], check=True)
    subprocess.run(['node', os.path.join(ROOT, 'tests', 'tests_forecast.js')], check=True)  # no npm packages needed
    subprocess.run(['node', os.path.join(ROOT, 'tests', 'test_pages_parse.js')], check=True)  # every page script parses
    subprocess.run(['node', os.path.join(ROOT, 'tests', 'tests_widget.js')], check=True)  # the phone widget (no packages needed)
    subprocess.run(['node', os.path.join(ROOT, 'tests', 'tests_false_readings.js')], check=True)  # false readings left out (no packages needed)
    vp, mp = os.path.join(FW, 'version.py'), os.path.join(ROOT, 'manifest.json')
    was = open(vp).read() if os.path.exists(vp) else None
    try:
        with open(vp, 'w') as f:
            f.write("VERSION = '%s'\n" % ver)
        text = build(ver, notes, KEY)
        m = check_text(text)
        with open(mp + '.tmp', 'w') as f:
            f.write(text)
        os.replace(mp + '.tmp', mp)
    except BaseException:  # (anything, Ctrl-C too: nothing published, version.py as it was)
        if was is None:
            os.path.exists(vp) and os.remove(vp)
        else:
            with open(vp, 'w') as f:
                f.write(was)
        os.path.exists(mp + '.tmp') and os.remove(mp + '.tmp')
        raise
    total = sum(v[1] for v in m['files'].values())
    if 2 * total + 40000 > 1500000:  # (an install keeps .new and .bak copies: updater.install's own sum)
        print('!! this release needs %d KB free on the Pico to install (about 2.4 MB is free on a Pico 2 W with history)' % ((2 * total + 40000) // 1024))
    print('manifest.json: %d files, %d bytes (checked with the Pico\'s own updater)' % (
        len(m['files']), sum(v[1] for v in m['files'].values())))
    kc = keep_changed(old)
    if kc:
        print('\n!! changed since v%s and NOT sent over the air: %s\n   upload them by maintenance or USB after installing.' % (old, ', '.join(kc)))
    print('\nNow:\n  git add -A && git commit -m "Release v%s" && git tag v%s\n  python3 tools/release.py --check v%s\n'
          '  git push origin main v%s' % (ver, ver, ver, ver))


if __name__ == '__main__':
    main()
