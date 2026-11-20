#!/usr/bin/env python3
"""python3 -I tools/pricehist.py  - rebuild data/priceh.bin: Northern Ireland heating oil prices, one record a day,
from cheapestoil.co.uk's public price chart (the cheapest and the average price for 900 L).

A Pico with oil prices switched on downloads this file once (firmware/price.py hist_fetch), so its chart goes back
years and not just to the day it was set up; after that it adds a day of its own each morning. Run this now and
then (before a release, say) so a newly set-up Pico has no gap. Same 6-byte records as price.bin: <uint16 day since
2000-01-01, int16 cheapest, int16 average> in tenths of a penny a litre.
"""
import datetime as dt, json, os, re, struct, sys, time, urllib.request

FROM = dt.date(2021, 1, 1)  # (the chart's daily figures before 2021 don't line up with its dates)
UA = 'hawki-pico/pricehist'  # (their site turns away some user agents: this one is let through)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'priceh.bin')
E = dt.date(2000, 1, 1)


def year(ty, a, b):
    u = ('https://www.cheapestoil.co.uk/articles/trend?from=%s&to=%s&type=%s&litres=ppl&tax=1&zero=0&annotations=0'
         % (a, b, ty))
    s = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA}), timeout=60).read().decode()
    lab = json.loads(re.search(r'var chartLabels = (\[.*?\]);', s).group(1))
    val = json.loads(re.search(r'var chartValues = (\[.*?\]);', s).group(1))
    if len(val) != (b - a).days + 1:  # one figure a day, from a to b
        raise SystemExit('%s %s..%s: %d figures for %d days' % (ty, a, b, len(val), (b - a).days + 1))
    out = {}
    for i, (l, v) in enumerate(zip(lab, val)):
        d = a + dt.timedelta(days=i)
        try:  # labels with a full date must agree with the count (others read like 'Jan 2021')
            ld = dt.datetime.strptime(l, '%d %B %Y').date()
        except (TypeError, ValueError):
            ld = d
        if ld != d:
            raise SystemExit('%s %s: labelled %s' % (ty, d, l))
        if isinstance(v, (int, float)) and 5 <= v <= 500:
            out[d] = v
    return out


def main():
    end = dt.date.today() - dt.timedelta(days=1)
    got = {'cheap': {}, 'avg': {}}
    for y in range(FROM.year, end.year + 1):
        a, b = max(FROM, dt.date(y, 1, 1)), min(end, dt.date(y, 12, 31))
        for ty in got:
            got[ty].update(year(ty, a, b))
            time.sleep(2)  # (gently: a dozen pages, once in a while)
    days = sorted(set(got['cheap']) | set(got['avg']))
    rec = b''.join(struct.pack('<Hhh', (d - E).days, *(int(round(got[ty][d] * 10)) if d in got[ty] else -32768
                                                        for ty in ('cheap', 'avg'))) for d in days)
    if os.path.exists(OUT) and len(rec) < os.path.getsize(OUT):  # (their chart cut short one day: keep what we have)
        raise SystemExit('only %d days this time, fewer than the %d already saved: left as it was'
                         % (len(days), os.path.getsize(OUT) // 6))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'wb').write(rec)
    print('%d days, %s to %s -> %s (%d bytes)' % (len(days), days[0], days[-1], os.path.normpath(OUT), len(rec)))


if __name__ == '__main__':
    sys.exit(main())
