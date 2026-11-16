#!/usr/bin/env python3
"""Make a release that every Pico can install from its web page.

    python3 tools/release.py 1.0.1 "What's new, in a sentence or two"

Runs the tests, writes firmware/version.py and manifest.json (SHA-256 + size of each file
the Pico downloads). Then commit, tag and push it, exactly as printed. Picos read
manifest.json from main and fetch the files from the tag, so a release is the tagged commit.
"""
import hashlib, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FW = os.path.join(ROOT, 'firmware')
KEEP = ('main.py', 'rescue.py', 'rollback.py')  # boot path: installed by USB only, never over the air


def vt(v):
    return tuple(int(x) for x in v.split('.'))


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    ver, notes = sys.argv[1].lstrip('v'), sys.argv[2]
    old = json.load(open(os.path.join(ROOT, 'manifest.json')))['version'] if os.path.exists(os.path.join(ROOT, 'manifest.json')) else '0.0.0'
    if vt(ver) <= vt(old):
        sys.exit('version %s must be newer than %s' % (ver, old))
    for t in sorted(os.listdir(os.path.join(ROOT, 'tests'))):
        if t.startswith('test_') and t.endswith('.py'):
            subprocess.run([sys.executable, os.path.join(ROOT, 'tests', t)], check=True)
    with open(os.path.join(FW, 'version.py'), 'w') as f:
        f.write("VERSION = '%s'\n" % ver)
    files = {}
    for n in sorted(os.listdir(FW)):
        p = os.path.join(FW, n)
        if n in KEEP or not os.path.isfile(p) or not n.endswith(('.py', '.html', '.pem')):
            continue
        b = open(p, 'rb').read()
        files[n] = [hashlib.sha256(b).hexdigest(), len(b)]
    m = {'version': ver, 'ref': 'v' + ver, 'notes': notes, 'files': files}
    with open(os.path.join(ROOT, 'manifest.json'), 'w') as f:
        json.dump(m, f, indent=1)
        f.write('\n')
    print('manifest.json: %d files, %d bytes' % (len(files), sum(v[1] for v in files.values())))
    print('\nNow:\n  git add -A && git commit -m "Release v%s" && git tag v%s && git push origin main v%s' % (ver, ver, ver))


if __name__ == '__main__':
    main()
