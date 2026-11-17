"""python3 tests/test_netcfg.py - fixed-address settings and the one-boot trial (firmware/netcfg.py)."""
import os, sys, tempfile, json
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'firmware'))
import netcfg

fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


def bad(**b):
    try:
        netcfg.clean(b)
    except ValueError as ex:
        return str(ex)
    return None


G = dict(ip='192.168.1.83', mask='255.255.255.0', gw='192.168.1.254', dns='192.168.1.254')
ok(netcfg.clean(G) == G and netcfg.tup(G) == ('192.168.1.83', '255.255.255.0', '192.168.1.254', '192.168.1.254'), 'a normal home setup passes, in ifconfig order')
ok(netcfg.clean(dict(ip=' 192.168.001.83 ', gw='192.168.1.254')) == G, 'tidied; mask defaults to 255.255.255.0 and DNS to the router')
ok('four numbers' in (bad(**dict(G, ip='192.168.1')) or '') and 'four numbers' in (bad(**dict(G, ip='192.168.1.300')) or '') and bad(**dict(G, ip='a.b.c.d')), 'not an address: refused')
ok('same network' in (bad(**dict(G, gw='192.168.0.1')) or ''), 'router on another network: refused, and says so')
ok(bad(**dict(G, ip='192.168.1.0')) and bad(**dict(G, ip='192.168.1.255')), "the network's own and broadcast addresses: refused")
ok(bad(**dict(G, ip='192.168.1.254')) and bad(**dict(G, gw='192.168.1.255')), "the router's own address, or a broadcast gateway: refused")
ok(bad(**dict(G, mask='255.0.255.0')) and bad(**dict(G, mask='0.0.0.0')) and bad(**dict(G, mask='255.255.255.255')), 'masks with holes, empty or host-only: refused')
ok(bad(**dict(G, ip='127.0.0.5', gw='127.0.0.1')) and bad(**dict(G, ip='224.0.0.5', gw='224.0.0.1')) and bad(**dict(G, dns='0.0.0.0')), 'loopback, multicast, zero DNS: refused')
ok(netcfg.clean(dict(ip='10.0.5.20', mask='255.255.0.0', gw='10.0.0.1', dns='1.1.1.1'))['dns'] == '1.1.1.1', 'a bigger network with an outside DNS passes')
# the trial: written, taken once, gone
d = tempfile.mkdtemp()
f = os.path.join(d, 'net.try')
netcfg.write_try(G, 'abcdef0123456789', f)
t = netcfg.take_try(f)
ok(t == dict(G, k='abcdef0123456789') and not os.path.exists(f), 'trial settings are read once and the file is removed')
ok(netcfg.take_try(f) is None, 'so the next boot has no trial: back to the saved settings')
open(f, 'w').write('{"ip": "192.168.1.83", "gw": "10.0.0.1", "k": "abcdef0123456789"}')
ok(netcfg.take_try(f) is None and not os.path.exists(f), 'a trial file with bad settings is thrown away')
open(f, 'w').write(json.dumps(dict(G, k='x')))
ok(netcfg.take_try(f) is None, 'or with no proper key')
open(f, 'w').write('not json')
ok(netcfg.take_try(f) is None and not os.path.exists(f), 'or that is not readable')
sys.exit(1 if fails else 0)
