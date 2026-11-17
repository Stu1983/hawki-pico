"""3D-printable case for a HAWKi Pico (Raspberry Pi Pico 2 W, with or without headers).

python3 case/make_case.py  ->  case/out/*.stl and hawki_case.3mf (needs trimesh, manifold3d, shapely, matplotlib)

Base: the board sits on 4 pegs 10 mm up (room for soldered headers underneath): short pins on one diagonal line it up,
two M2 self-tapping screws on the other hold it down. USB opening at one end, two screw ears to fix it to a wall or
beam. Lid: a lip that clicks into grooves in the base (no posts: nothing to line up with the pins), a hole over the BOOTSEL button (hold it 5 s with a pen to clear a forgotten PIN), raised text.
All sizes in mm; change them below.
"""
import os
import numpy as np
import trimesh
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from matplotlib.textpath import TextPath
from matplotlib.font_manager import FontProperties

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')

# --- Pico 2 W (datasheet): board 51 x 21 x 1, holes 2.1 mm on a 47 x 11.4 grid ---
PCB_L, PCB_W, PCB_T = 51.0, 21.0, 1.0
HOLE_DX, HOLE_DY, HOLE_D = 47.0, 11.4, 2.1
# Measured positions below came from the Pico 2 STEP, confirmed on a real Pico 2 W by a printed MiSTer mount
USB_OVER, USB_Z = 1.3, 1.07                   # micro-USB overhang past the board end; socket centre above the component face
BOOTSEL_X, BOOTSEL_Y = 12.0, 7.0              # BOOTSEL centre: from the USB-end edge, from the long edge nearer the button
BOOTSEL_TOP = 2.5                             # actuator top above the component face
LED_X, LED_Y, LED_D = 4.8, 4.8, 2.5           # LED window (same frame)
# --- case ---
WALL, FLOOR, TOP = 2.0, 2.0, 2.0
GAP = 0.6                                      # air around the board
UNDER = 10.0                                   # under the board: headers stick out ~8.5 mm
OVER = 5.5                                     # over the board: USB socket, RF can, header stubs
PLUG_W, PLUG_H, PLUG_R = 12.0, 8.5, 2.0       # opening for the cable's plug (9.5 x 6.5 overmould + clearance; +1 mm after a
                                               # test print only just fitted). The U's bottom is PLUG_H/2 under the socket centre
LIP, LIP_CLR = 3.0, 0.15                       # lid lip depth, clearance per side
# the lid clicks on: a rounded ridge along each long side of the lip snaps into a groove in the base wall
RIDGE_R, RIDGE_LEN, GROOVE_EXTRA = 0.45, 24.0, 0.15   # ridge radius (0.3 mm of snap past the clearance), length; groove a little bigger
# board fixing: locating pins on one diagonal, M2 self-tapping screws (pan head, ~6 mm) on the other (as on the MiSTer mount)
PIN_D, PIN_UP, PIN_CH = 1.9, 0.8, 0.4          # pin (Pico holes are 2.1), how far it stands above the board, tip chamfer
PEG_D, SCREW_PEG_D, PILOT_D, PILOT_DEEP = 3.6, 4.6, 1.7, 7.0   # pegs; the screw pegs are fatter round a 1.7 mm pilot this deep
SCREWS_AT = (1, 2)                             # indexes into holes: the diagonal pair that gets screws; the other two get pins
EAR, SCREW_D, HEAD_D = 11.0, 4.5, 8.5          # screw ears for ~4 mm wood screws, countersunk
TEXT, SUB = 'Oil Monitor', 'HAWKi'
# cable-tie strain relief off the USB end: a tab, then a saddle (past the plug's 20 mm overmould) with a groove for the
# cable and a slot under it for the tie
PLUG_LEN = 20.0                                # straight plug overmould length out of the case
TAB_OUT, TAB_WIDE, TAB_THK = 32.0, 16.0, 4.0   # how far the tab sticks out, its width and thickness
SAD_L, SAD_W = 8.0, 12.0                       # saddle length (along the cable) and width
CABLE_D = 4.0                                  # cable groove fits up to this diameter
TIE_W, TIE_H = 2.6, 5.2                        # tie slot, on its side (ties up to ~4.8 x 1.5 go through on edge), pointed
                                               # 45-degree roof so it prints without support
# flexible BOOTSEL button: a tongue cut from the lid, hinged on the side away from USB, flexing along the print layers
TAB_W, TAB_LEN, TAB_TIP, SLOT = 7.0, 12.0, 2.5, 0.8   # width, hinge to tip, tip past the button centre, slot round it
TAB_T = 1.44                                   # tongue thickness (the lid is thinned under it)
NUB_R, NUB_GAP, NUB_CH = 1.2, 0.2, 0.48        # plunger radius, gap above the actuator, tip chamfer
INLAY = 0.6                                    # text/logo inlaid flush into the lid face, this deep (3 layers at 0.2)

IN_L = PCB_L + 2 * GAP + USB_OVER
IN_W = PCB_W + 2 * GAP
IN_H = UNDER + PCB_T + OVER
OUT_L, OUT_W, BASE_H = IN_L + 2 * WALL, IN_W + 2 * WALL, FLOOR + IN_H
X0 = WALL + GAP + USB_OVER     # board's USB end (x) inside the base; USB end of the case is x = 0
Y0 = WALL + GAP                # board's pin-1 edge (y)
holes = [(X0 + (PCB_L - HOLE_DX) / 2 + i * HOLE_DX, Y0 + (PCB_W - HOLE_DY) / 2 + j * HOLE_DY) for i in (0, 1) for j in (0, 1)]


def box(x0, y0, z0, x1, y1, z1):
    b = trimesh.creation.box(extents=(x1 - x0, y1 - y0, z1 - z0))
    b.apply_translation(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    return b


def cyl(x, y, z0, z1, d, n=48):
    c = trimesh.creation.cylinder(radius=d / 2, height=z1 - z0, sections=n)
    c.apply_translation((x, y, (z0 + z1) / 2))
    return c


def cone(x, y, z0, z1, d0, d1, n=48):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = lambda d, z: np.c_[x + d / 2 * np.cos(a), y + d / 2 * np.sin(a), np.full(n, z)]
    v = np.vstack([ring(d0, z0), ring(d1, z1), [[x, y, z0], [x, y, z1]]])
    f = []
    for i in range(n):
        j = (i + 1) % n
        f += [[i, j, n + j], [i, n + j, n + i], [2 * n, j, i], [2 * n + 1, n + i, n + j]]
    return trimesh.Trimesh(v, f, process=True)


def rbox(x0, y0, z0, x1, y1, z1, r):
    """Box with rounded vertical edges."""
    p = Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]).buffer(-r).buffer(r, resolution=12)
    m = trimesh.creation.extrude_polygon(p, z1 - z0)
    m.apply_translation((0, 0, z0))
    return m


U = lambda *m: trimesh.boolean.union(list(m), engine='manifold')
D = lambda a, *b: trimesh.boolean.difference([a] + list(b), engine='manifold')


def base():
    shell = rbox(0, 0, 0, OUT_L, OUT_W, BASE_H, 3)
    ears = []
    for y0, y1 in ((-EAR, 3), (OUT_W - 3, OUT_W + EAR)):   # one ear each side, centred lengthwise, 4 mm thick
        ears.append(rbox(OUT_L / 2 - 8, y0, 0, OUT_L / 2 + 8, y1, 4, 4))
    body = U(shell, *ears)
    cav = box(WALL, WALL, FLOOR, OUT_L - WALL, OUT_W - WALL, BASE_H + 1)
    usb_z = FLOOR + UNDER + PCB_T + USB_Z
    # opening for the plug: a U-slot open at the top (the lid closes it), so there's no roof to bridge and the cable
    # drops in from above. Drawn as (height, width) about the socket centre, extruded, turned to run through the end wall
    hb, ht = -PLUG_H / 2, BASE_H + 1 + PLUG_R - usb_z
    hb, ht = -ht, -hb                              # the turn below maps the drawing's height to -z
    prof = Polygon([(hb, -PLUG_W / 2), (ht, -PLUG_W / 2), (ht, PLUG_W / 2), (hb, PLUG_W / 2)]).buffer(-PLUG_R).buffer(PLUG_R, resolution=12)
    plug = trimesh.creation.extrude_polygon(prof, WALL + 2)
    plug.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0)))
    plug.apply_translation((WALL + 1 - plug.bounds[1][0], Y0 + PCB_W / 2, usb_z))
    cuts = [cav, plug]
    for y in (-EAR / 2, OUT_W + EAR / 2):
        cuts += [cyl(OUT_L / 2, y, -1, 5, SCREW_D), cone(OUT_L / 2, y, 4 - (HEAD_D - SCREW_D) / 2, 4.01, SCREW_D, HEAD_D)]
    # strain relief: tab + saddle, cable groove on top at the cable's height, tie slot through under it
    cy = Y0 + PCB_W / 2
    sx1 = -(PLUG_LEN - WALL) - 3.0                 # saddle starts 3 mm past the end of the plug overmould
    sx0 = max(sx1 - SAD_L, -TAB_OUT + 2)
    groove_bot = usb_z - CABLE_D / 2
    tab = rbox(-TAB_OUT, cy - TAB_WIDE / 2, 0, 3.0, cy + TAB_WIDE / 2, TAB_THK, 3)
    saddle = rbox(sx0, cy - SAD_W / 2, 0, sx1, cy + SAD_W / 2, groove_bot + 1.2, 1.5)
    body = U(body, tab, saddle)
    groove = cyl(0, 0, sx0 - 1, sx1 + 1, CABLE_D + 0.4)
    groove.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0)))
    groove.apply_translation(((sx0 + sx1) / 2 - groove.centroid[0], cy - groove.centroid[1], usb_z - groove.centroid[2]))
    peak = groove_bot - 1.2                        # roof point, 1.2 mm under the cable groove
    z1 = peak - TIE_W / 2                          # top of the straight sides
    mx = (sx0 + sx1) / 2
    tp = Polygon([(-TIE_W / 2, z1 - TIE_H), (TIE_W / 2, z1 - TIE_H), (TIE_W / 2, z1), (0, peak), (-TIE_W / 2, z1)])  # (x, z)
    tie = trimesh.creation.extrude_polygon(tp, SAD_W + 2)            # extruded along +z ...
    tie.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))    # ... turned to run across (y), z kept
    tie.apply_translation((mx, cy - SAD_W / 2 - 1 - tie.bounds[0][1], 0))
    cuts += [groove, tie]
    body = D(body, *cuts)
    # snap grooves: inside each long wall, where the lid's ridges land
    gz = BASE_H - LIP / 2
    for y in (WALL, OUT_W - WALL):
        g = cyl(0, 0, -RIDGE_LEN / 2 - 1, RIDGE_LEN / 2 + 1, 2 * (RIDGE_R + GROOVE_EXTRA))
        g.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0)))
        g.apply_translation((OUT_L / 2 - g.centroid[0], y - g.centroid[1], gz - g.centroid[2]))
        body = D(body, g)
    top = FLOOR + UNDER                       # the board's underside
    posts, pilots = [], []
    for i, (x, y) in enumerate(holes):
        if i in SCREWS_AT:                     # screw peg: fatter, with a pilot for an M2 self-tapper
            posts.append(cyl(x, y, FLOOR - 0.5, top, SCREW_PEG_D))
            pilots.append(cyl(x, y, top - PILOT_DEEP, top + 1, PILOT_D))
        else:                                  # pin peg: a short pin through the board's hole, chamfered tip
            posts += [cyl(x, y, FLOOR - 0.5, top, PEG_D), cyl(x, y, top - 0.1, top + PCB_T + PIN_UP - PIN_CH, PIN_D),
                      cone(x, y, top + PCB_T + PIN_UP - PIN_CH - 0.01, top + PCB_T + PIN_UP, PIN_D, PIN_D - 2 * PIN_CH)]
    return D(U(body, *posts), *pilots)


def text_polys(s, size, cx, cy, bold=True):
    """Bold text as shapely polygons centred on (cx, cy)."""
    fp = FontProperties(family='DejaVu Sans', weight='bold' if bold else 'normal')
    tp = TextPath((0, 0), s, size=size, prop=fp)
    polys = []
    for poly in tp.to_polygons(closed_only=True):
        if len(poly) >= 3:
            polys.append(Polygon(poly).buffer(0))
    # even-odd: letters with holes come as outer + inner rings
    shapes = []
    for p in sorted(polys, key=lambda p: -p.area):
        for i, q in enumerate(shapes):
            if q.contains(p.representative_point()):
                shapes[i] = q.difference(p)
                break
        else:
            shapes.append(p)
    g = unary_union(shapes)
    b = g.bounds
    from shapely import affinity
    return affinity.translate(g, cx - (b[0] + b[2]) / 2, cy - (b[1] + b[3]) / 2)


def drop(cx, cy, h):
    """Oil-drop logo: a circle with a point on top."""
    r = h * 0.32
    c = Point(cx, cy - h / 2 + r).buffer(r, resolution=24)
    tip = Polygon([(cx - r * 0.97, cy - h / 2 + r * 1.25), (cx, cy + h / 2), (cx + r * 0.97, cy - h / 2 + r * 1.25)])
    return unary_union([c, tip])


def extrude(geom, z0, h):
    ms = []
    for g in getattr(geom, 'geoms', [geom]):
        m = trimesh.creation.extrude_polygon(g, h)
        m.apply_translation((0, 0, z0))
        ms.append(m)
    return U(*ms) if len(ms) > 1 else ms[0]


def lid():
    """As fitted: lip and posts underneath (z < 0), plate z 0..TOP. Text and logo are inlaid flush into the top face
    (z TOP-INLAY..TOP): the lid minus the text, plus the text as its own body for a 2nd filament."""
    plate = rbox(0, 0, 0, OUT_L, OUT_W, TOP, 3)
    c = LIP_CLR
    lip = D(box(WALL + c, WALL + c, -LIP, OUT_L - WALL - c, OUT_W - WALL - c, 0.01),
            box(WALL + c + 1.6, WALL + c + 1.6, -LIP - 1, OUT_L - WALL - c - 1.6, OUT_W - WALL - c - 1.6, 0.02))
    ridges = []
    for y in (WALL + c, OUT_W - WALL - c):      # a rounded ridge along the middle of each long side of the lip
        r = cyl(0, 0, -RIDGE_LEN / 2, RIDGE_LEN / 2, 2 * RIDGE_R)
        r.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0)))
        r.apply_translation((OUT_L / 2 - r.centroid[0], y - r.centroid[1], -LIP / 2 - r.centroid[2]))
        ridges.append(r)
    body = U(plate, lip, *ridges)
    bx, by = X0 + BOOTSEL_X, Y0 + BOOTSEL_Y
    # flexible button: tongue from the hinge (away from USB) to a round tip just past the button
    tip = bx - TAB_TIP                               # USB-side end of the tongue
    hinge = tip + TAB_LEN
    tongue = Polygon([(tip + TAB_W / 2, by - TAB_W / 2), (hinge, by - TAB_W / 2), (hinge, by + TAB_W / 2), (tip + TAB_W / 2, by + TAB_W / 2)]).union(Point(tip + TAB_W / 2, by).buffer(TAB_W / 2, resolution=32))
    slot = tongue.buffer(SLOT, resolution=32).difference(tongue).difference(Polygon([(hinge, by - 10), (hinge + 5, by - 10), (hinge + 5, by + 10), (hinge, by + 10)]))
    thin = extrude(tongue.buffer(SLOT, resolution=32), -LIP - 1, LIP + 1 + TOP - TAB_T)   # thin the lid under the tongue
    body = D(body, extrude(slot, -LIP - 1, LIP + TOP + 2), thin,
             cyl(X0 + LED_X, Y0 + LED_Y, -LIP - 1, TOP + 1, LED_D),
             box(-1, Y0 + PCB_W / 2 - PLUG_W / 2 - 0.5, -LIP - 1, WALL + c + 0.01, Y0 + PCB_W / 2 + PLUG_W / 2 + 0.5, 0.01))
    nub_bot = -OVER + BOOTSEL_TOP + NUB_GAP        # lid underside is z 0; the board's component face is z -OVER
    nub = U(cyl(bx, by, nub_bot + NUB_CH, TOP - TAB_T + 0.01, 2 * NUB_R), cone(bx, by, nub_bot, nub_bot + NUB_CH + 0.01, 2 * (NUB_R - NUB_CH), 2 * NUB_R))
    body = U(body, nub)
    # layout (top view, USB on the left): 'Oil Monitor' along the top, the button below it, the oil drop
    # beside the button, 'HAWKi' reading upwards along the far end
    from shapely import affinity
    band0 = by + TAB_W / 2 + SLOT + 1.2               # text band: above the button...
    band1 = OUT_W - 2.0                               # ...to near the far edge
    tx0, tx1 = 3.5, OUT_L - 10.5
    w = text_polys(TEXT, 10, 0, 0).bounds
    size = min(10 * (tx1 - tx0) / (w[2] - w[0]), 10 * (band1 - band0) / (w[3] - w[1]))
    main = text_polys(TEXT, size, 0, 0)
    mb = main.bounds
    main = affinity.translate(main, tx0 - mb[0], (band0 + band1) / 2 - (mb[1] + mb[3]) / 2)
    logo = drop((hinge + OUT_L - 9) / 2 + 0.5, (2.0 + band0) / 2, min(band0 - 2.5, 11))
    sub = text_polys(SUB, 4.4, 0, 0).buffer(0.08)
    sub = affinity.rotate(sub, 90, origin='centroid')
    sb = sub.bounds
    sub = affinity.translate(sub, OUT_L - 4.6 - (sb[0] + sb[2]) / 2, OUT_W / 2 - (sb[1] + sb[3]) / 2)
    deco = extrude(unary_union([main, sub, logo]), TOP - INLAY, INLAY)
    return D(body, deco), deco


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    b = base()
    l, t = lid()
    for name, m in (('base', b), ('lid', l), ('lid_text', t)):
        assert m.is_watertight, name
        m.export(os.path.join(OUT, 'hawki_%s.stl' % name))
    # lid + text as one file: two objects, so a multi-colour printer can give the text its own filament
    # print the lid face down: the text sits on the build plate (flip about the long axis; reads correctly once fitted)
    flip = trimesh.transformations.rotation_matrix(np.pi, (1, 0, 0))
    lf, tf = l.copy(), t.copy()
    for m in (lf, tf):
        m.apply_transform(flip)
        m.apply_translation((0, 0, -lf.bounds[0][2] if m is lf else 0))
    tf.apply_translation((0, 0, lf.bounds[0][2] - l.copy().apply_transform(flip).bounds[0][2]))
    sc = trimesh.Scene()
    sc.add_geometry(lf, node_name='lid', geom_name='lid')
    sc.add_geometry(tf, node_name='text', geom_name='text')
    sc.export(os.path.join(OUT, 'hawki_lid_2colour.3mf'))
    print('outside %.1f x %.1f x %.1f mm (+ ears to %.1f wide), lid %.1f mm; text inlaid %.1f mm, 3mf face down: lid z %.2f..%.2f text z %.2f..%.2f'
          % (OUT_L, OUT_W, BASE_H, OUT_W + 2 * EAR, TOP, INLAY, *lf.bounds[:, 2], *tf.bounds[:, 2]))
    print('text bounds', np.round(t.bounds, 1).tolist(), 'bootsel hole at', round(X0 + BOOTSEL_X, 1), round(Y0 + BOOTSEL_Y, 1))
