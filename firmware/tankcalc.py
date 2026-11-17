"""Tank volume from a HAWKi distance reading (runs on CPython and MicroPython).

Mirrors what the Magnus app/server does with the Tank Details:
  height_cm  = the user-measured maximum fill height (sensor down to the outlet)
  length_cm, width_cm, shape, windows (0/1/2)
  capacity_l = the oil between the top of the outlet and the monitor (NOT the brochure figure,
               which counts from the tank floor: a Titan R1225 is ~1180 L here, checked against
               a metered 500 L delivery with height 121.5 = 130 less an 8.5 cm outlet)

Cuboid with windows: Magnus computes window geometry server-side from the window count.
Reverse-fitted from the app on a Titan R1225 (H130 L178 W75, 1323 L, 2 windows):
the windows form a band of reduced cross-section from 17.38 % to 82.23 % of the height,
and the band's area makes the total equal the brimful capacity. This reproduces the app's
621.41 / 617.18 / 613 L at 696 / 701 / 706 mm. For other window counts or tanks it's the
same assumption (the window volume is whatever the capacity says is missing).
That's window_model 'standard' (the default; matches the app).

window_model 'measured' (cuboid only): the user's own rough measurements, all cm ABOVE THE
GROUND (easier than inside the tank):
  outlet_cm                     top of the outlet = the zero of the fill height
  win_bottom_cm, win_top_cm     outer opening of the windows (all windows assumed level)
  win_outer_w_cm                outer opening width, along the tank's length
  win_inner_w_cm, win_inner_h_cm  the narrowest point, mid-way through the tank
  ribs_cm                       list of rib centre heights; rib_h_cm (band height), rib_depth_cm
Each window is a tunnel through the tank's width that tapers linearly from the outer opening
to the inner size at the middle. Ribs are hollow bands that add depth x perimeter.
The body cross-section is then scaled so the full height holds exactly capacity_l, so rough
measurements only move litres between heights; they can't change the total.
"""
import math
from array import array

WIN_Z1 = 225.82 / 1300
WIN_Z2 = 1069.38 / 1300
SHAPES = ('cuboid', 'horizontal', 'vertical', 'other')
STEP = 5.0  # mm, resolution of the measured-model table
_tables = {}
PER_MONITOR = ('name', 'reserve_l', 'unusable_l', 'isolated', 'mode', 'group')  # not shared by linked tanks


def _f(t, k, d=0.0):
    v = t.get(k)
    return d if v in (None, '') else float(v)


def _win_rate(t, z):
    """L per mm removed by the windows at height z (mm above the outlet)."""
    n = int(_f(t, 'windows'))
    if n <= 0:
        return 0.0
    base = _f(t, 'outlet_cm') * 10
    zb, zt = _f(t, 'win_bottom_cm') * 10 - base, _f(t, 'win_top_cm') * 10 - base
    if zt <= zb:
        return 0.0
    zc, ho = (zb + zt) / 2, zt - zb
    wo = _f(t, 'win_outer_w_cm') * 10
    wi = _f(t, 'win_inner_w_cm', wo / 10) * 10
    hi = _f(t, 'win_inner_h_cm', ho / 10) * 10
    W = _f(t, 'width_cm') * 10
    steps, area = 24, 0.0
    for i in range(steps):  # walk through the width; symmetric, so face -> middle twice
        f = (i + 0.5) / steps  # 0 at the face, 1 at the middle
        h = ho + (hi - ho) * f
        if abs(z - zc) <= h / 2:
            area += (wo + (wi - wo) * f) * (W / 2 / steps)
    return n * 2 * area / 1e6


def _rib_rate(t, z):
    ribs = t.get('ribs_cm') or []
    if not ribs:
        return 0.0
    base = _f(t, 'outlet_cm') * 10
    rh, rd = _f(t, 'rib_h_cm', 12) * 10, _f(t, 'rib_depth_cm', 1.5) * 10
    per = 2 * (_f(t, 'length_cm') + _f(t, 'width_cm')) * 10
    k = sum(1 for c in ribs if abs(z - (float(c) * 10 - base)) <= rh / 2)
    return k * per * rd / 1e6


def _measured_table(t, H, cap):
    # Litres at every STEP mm, kept as 4-byte floats: a list of boxed floats cost ~13 KB a table, and a
    # few of those chopped the heap up so much that HTTPS (one ~40 KB block) failed with ENOMEM.
    key = (H, cap) + tuple((k, str(t.get(k))) for k in sorted(t) if k not in PER_MONITOR)  # (linked tanks: one table)
    tbl = _tables.get(key)
    if tbl:
        return tbl
    n = int(H / STEP) + 1
    zs = [min(H, i * STEP) for i in range(n)]
    if zs[-1] < H:
        zs.append(H)
    vs = array('f', bytes(4 * len(zs)))
    prev_r, c = _rib_rate(t, 0) - _win_rate(t, 0), 0.0
    for i in range(1, len(zs)):  # cumulative ribs - windows, then add the body
        r = _rib_rate(t, zs[i]) - _win_rate(t, zs[i])
        c += (r + prev_r) / 2 * (zs[i] - zs[i - 1])
        vs[i] = c
        prev_r = r
    a0 = (cap - c) / H  # body L/mm, scaled so the full height = capacity
    for i in range(len(zs)):
        vs[i] += a0 * zs[i]
    tbl = (H, vs)
    if len(_tables) >= 3:
        _tables.clear()
    _tables[key] = tbl
    return tbl


def _interp(tbl, d):
    H, vs = tbl
    i = min(len(vs) - 2, int(d / STEP))
    z0, z1 = i * STEP, min(H, (i + 1) * STEP)
    return vs[i] + (vs[i + 1] - vs[i]) * (d - z0) / (z1 - z0)


def whole(tank):
    """The whole tank, floor to monitor, holding tank_l (what a spec sheet gives)."""
    o = float(tank.get('outlet_cm') or 0)
    return dict(tank, height_cm=float(tank['height_cm']) + o, capacity_l=float(tank['tank_l']), outlet_cm=0)


def below(tank):
    """Litres under the top of the outlet (there, but the boiler can't draw it); 0 if not known."""
    if tank.get('tank_l') in (None, ''):
        return 0.0
    w = whole(tank)
    return _litres(w, float(tank['height_cm']) * 10.0) or 0.0


def above(tank):
    """Usable capacity: from the top of the outlet up to the monitor."""
    if tank.get('tank_l') in (None, ''):
        return float(tank['capacity_l'])
    return float(tank['tank_l']) - below(tank)


def tank_equiv(tank):
    """Older settings (usable capacity_l, no tank_l): the whole-tank capacity that gives the same usable
    capacity. Usable capacity rises steadily with the whole (piecewise straight), so a few secant steps
    find it."""
    if tank.get('tank_l') not in (None, ''):
        return float(tank['tank_l'])
    cap = float(tank['capacity_l'])
    if not float(tank.get('outlet_cm') or 0):
        return cap
    f = lambda x: above(dict(tank, tank_l=x)) - cap
    x0, x1 = cap, cap * 1.2
    y0, y1 = f(x0), f(x1)
    for _ in range(8):
        if abs(y1) < 0.05 or y1 == y0:
            break
        x0, x1, y0 = x1, x1 - y1 * (x1 - x0) / (y1 - y0), y1
        y1 = f(x1)
    return x1 if abs(y1) < 1 else None  # odd settings (e.g. nothing usable): no suggestion


def litres(tank, level_mm):
    """Usable litres (above the top of the outlet) for a sensor-to-surface distance, or None if unknown.
    With tank_l the whole tank is modelled from the floor and the oil under the outlet taken off;
    without it (older settings) capacity_l is the usable capacity, outlet to monitor."""
    if tank.get('tank_l') in (None, ''):
        return _litres(tank, level_mm)
    if level_mm is None or level_mm == 16383:
        return None
    if level_mm == 16382:
        return 0.0
    v = _litres(whole(tank), level_mm)
    return None if v is None else max(0.0, v - below(tank))


def total(tank, level_mm):
    """All the oil in the tank, floor to surface (usable + what's below the outlet), or None if unknown.
    Needs tank_l (the whole-tank model); older settings only know the usable part."""
    if tank.get('tank_l') in (None, '') or level_mm is None or level_mm == 16383:
        return None
    if level_mm == 16382:
        return 0.0
    v = _litres(whole(tank), level_mm)
    return None if v is None else max(0.0, v)


def _litres(tank, level_mm):
    """Return litres of liquid for a sensor-to-surface distance, or None if unknown."""
    if level_mm is None or level_mm == 16383:
        return None
    if level_mm == 16382:  # sensor's own 'nearly empty' code
        return 0.0
    H = float(tank['height_cm']) * 10.0
    cap = float(tank['capacity_l'])
    d = H - level_mm
    if d <= 0:
        return 0.0
    if d >= H:
        return cap
    shape = tank.get('shape', 'cuboid')
    if shape == 'cuboid' and tank.get('window_model') == 'measured':
        return min(cap, max(0.0, _interp(_measured_table(tank, H, cap), d)))
    if shape == 'cuboid':
        A = float(tank['length_cm']) * float(tank['width_cm']) / 10000.0  # L per mm
        if int(tank.get('windows', 0)) > 0 and A * H > cap:
            z1, z2 = WIN_Z1 * H, WIN_Z2 * H
            a = A - (A * H - cap) / (z2 - z1)  # window band L per mm
            if d <= z1:
                v = A * d
            elif d <= z2:
                v = A * z1 + a * (d - z1)
            else:
                v = A * z1 + a * (z2 - z1) + A * (d - z2)
            return min(cap, max(0.0, v))
        return cap * d / H  # straight-sided: scale to the stated capacity
    if shape == 'horizontal':  # lying cylinder, diameter = height
        r = H / 2.0
        h = d
        seg = r * r * math.acos((r - h) / r) - (r - h) * math.sqrt(max(0.0, 2 * r * h - h * h))
        return cap * seg / (math.pi * r * r)
    return cap * d / H  # vertical cylinder / other: linear


def _model(tank):
    """The tank's level -> litres function, with the settings read once (a curve calls it ~125 times)."""
    H = float(tank['height_cm']) * 10.0
    cap = float(tank['capacity_l'])
    shape = tank.get('shape', 'cuboid')
    tbl = None
    if shape == 'cuboid' and tank.get('window_model') == 'measured':
        tbl = _measured_table(tank, H, cap)
    elif shape == 'cuboid':
        A = float(tank['length_cm']) * float(tank['width_cm']) / 10000.0  # L per mm
        win = int(tank.get('windows', 0)) > 0 and A * H > cap
        if win:
            z1, z2 = WIN_Z1 * H, WIN_Z2 * H
            a = A - (A * H - cap) / (z2 - z1)  # window band L per mm

    def f(level_mm):
        if level_mm is None or level_mm == 16383:
            return None
        if level_mm == 16382:  # sensor's own 'nearly empty' code
            return 0.0
        d = H - level_mm
        if d <= 0:
            return 0.0
        if d >= H:
            return cap
        if tbl is not None:
            return min(cap, max(0.0, _interp(tbl, d)))
        if shape == 'cuboid':
            if win:
                if d <= z1:
                    v = A * d
                elif d <= z2:
                    v = A * z1 + a * (d - z1)
                else:
                    v = A * z1 + a * (z2 - z1) + A * (d - z2)
                return min(cap, max(0.0, v))
            return cap * d / H  # straight-sided: scale to the stated capacity
        if shape == 'horizontal':  # lying cylinder, diameter = height
            r = H / 2.0
            h = d
            seg = r * r * math.acos((r - h) / r) - (r - h) * math.sqrt(max(0.0, 2 * r * h - h * h))
            return cap * seg / (math.pi * r * r)
        return cap * d / H  # vertical cylinder / other: linear
    return f


def litres_many(tank, levels):
    """litres() for a list of distances, working the model out once (same answers, ~25x quicker).
    Odd settings that stop the model being built go the slow way, so they give exactly what litres() gives."""
    levels = list(levels)  # (an iterator would be half used up by a failed fast try)
    try:
        return _many(tank, levels)
    except Exception:
        return [litres(tank, x) for x in levels]


def _many(tank, levels):
    if tank.get('tank_l') in (None, ''):
        f = _model(tank)
        return [f(x) for x in levels]
    f, b = _model(whole(tank)), below(tank)
    out = []
    for x in levels:
        if x is None or x == 16383:
            out.append(None)
        elif x == 16382:
            out.append(0.0)
        else:
            v = f(x)
            out.append(None if v is None else max(0.0, v - b))
    return out


def link(tanks, mac, t, b, restore=False):
    """Store tank settings t for mac in tanks, handling 'Same tank as'. Linked monitors share one tank's
    settings, so a change to one (the form, or a capacity fit) is a change to all of them; only the
    PER_MONITOR settings are their own. b is the request: 'same_as' = the other tank's mac ('' = not linked);
    without it (a capacity fit, a restore) the link stays as it was."""
    g = None
    if 'same_as' in b:
        o = str(b.get('same_as') or '').lower()
        if o and o != mac and o in tanks:
            g = tanks[o].get('group')
            if not g:  # a new group, with a name of its own (not a tank's: that tank could leave it)
                used = set(x.get('group') for x in tanks.values())
                i = 1
                while 'g%d' % i in used:
                    i += 1
                g = tanks[o]['group'] = 'g%d' % i
    else:
        g = b.get('group') if restore else tanks.get(mac, {}).get('group')
    if g:
        t['group'] = str(g)[:17]
    tanks[mac] = t
    if g and not restore:  # (a restore brings every tank's own copy)
        for m in list(tanks):
            o = tanks[m]
            if m != mac and o.get('group') == t['group']:
                n = {k: v for k, v in t.items() if k not in PER_MONITOR}
                for k in PER_MONITOR:
                    if k in o:
                        n[k] = o[k]
                tanks[m] = n
    if not restore:  # a group down to one tank (the other unlinked or was removed) is no group
        n = {}
        for x in tanks.values():
            if x.get('group'):
                n[x['group']] = n.get(x['group'], 0) + 1
        for x in tanks.values():
            if x.get('group') and n[x['group']] < 2:
                del x['group']


def restore_groups(tanks, incoming):
    """A backup's tanks with their groups renamed so none is the name of a group the tanks NOT in the backup
    already have (an old backup's g1 must not join a newer, unrelated g1). Returns a new dict."""
    used = set(t.get('group') for m, t in tanks.items() if m.lower() not in [x.lower() for x in incoming])
    ren, out, i = {}, {}, 1
    for m, t in incoming.items():
        g = t.get('group') if isinstance(t, dict) else None
        if g:
            if g not in ren:
                while 'g%d' % i in used:
                    i += 1
                ren[g] = 'g%d' % i
                used.add(ren[g])
            t = dict(t, group=ren[g])
        out[m] = t
    return out


def reading(tank, level_mm):
    v = litres(tank, level_mm)
    if v is None:
        return None, None
    return round(v, 1), round(100.0 * v / above(tank), 1)
