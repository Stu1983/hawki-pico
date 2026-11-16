"""3D-printable case for a HAWKi Pico (Raspberry Pi Pico 2 W, with or without headers).

python3 case/make_case.py  ->  case/out/*.stl and hawki_case.3mf (needs trimesh, manifold3d, shapely, matplotlib)

Base: the board sits on 4 pegs 10 mm up (room for soldered headers underneath), USB opening at one end,
two screw ears to fix it to a wall or beam. Lid: friction-fit lip, posts that hold the board down on the
pegs, a hole over the BOOTSEL button (hold it 5 s with a pen to clear a forgotten PIN), raised text.
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
PLUG_W, PLUG_H, PLUG_R = 11.0, 7.5, 2.0       # opening for the cable's plug (9.5 x 6.5 overmould + clearance)
LIP, LIP_CLR = 3.0, 0.2                        # lid lip depth, clearance per side (PETG friction fit)
EAR, SCREW_D, HEAD_D = 11.0, 4.5, 8.5          # screw ears for ~4 mm wood screws, countersunk
TEXT, SUB = 'Oil Monitor', 'HAWKi'
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
    # rounded opening for the plug: drawn as (height, width), extruded, then turned to run through the end wall (x)
    prof = Polygon([(-PLUG_H / 2, -PLUG_W / 2), (PLUG_H / 2, -PLUG_W / 2), (PLUG_H / 2, PLUG_W / 2), (-PLUG_H / 2, PLUG_W / 2)]).buffer(-PLUG_R).buffer(PLUG_R, resolution=12)
    plug = trimesh.creation.extrude_polygon(prof, WALL + 2)
    plug.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0)))
    plug.apply_translation((WALL + 1 - plug.bounds[1][0], Y0 + PCB_W / 2, usb_z))
    cuts = [cav, plug]
    for y in (-EAR / 2, OUT_W + EAR / 2):
        cuts += [cyl(OUT_L / 2, y, -1, 5, SCREW_D), cone(OUT_L / 2, y, 4 - (HEAD_D - SCREW_D) / 2, 4.01, SCREW_D, HEAD_D)]
    body = D(body, *cuts)
    posts = []
    for x, y in holes:
        posts += [cyl(x, y, FLOOR - 0.5, FLOOR + UNDER, 3.6), cyl(x, y, FLOOR + UNDER - 0.1, FLOOR + UNDER + PCB_T + 1.2, 1.8)]
    return U(body, *posts)


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
    # posts reach the board's top face (board top is OVER below the lid's underside)
    posts = [D(cyl(x, y, -OVER, 0.01, 4.0), cyl(x, y, -OVER - 1, -OVER + 1.6, 2.2)) for x, y in holes]
    body = U(plate, lip, *posts)
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
    # oil drop on the button (press here); text across the rest of the lid
    logo = drop(tip + TAB_W / 2 + 0.6, by, 5.6)
    tx0, tx1 = hinge + SLOT + 2, OUT_L - 3
    w = text_polys(TEXT, 4.6, 0, 0).bounds
    main = text_polys(TEXT, min(4.6, 4.6 * (tx1 - tx0) / (w[2] - w[0])), (tx0 + tx1) / 2, OUT_W / 2 + 3.0)
    sub = text_polys(SUB, 3.8, (tx0 + tx1) / 2, OUT_W / 2 - 3.6).buffer(0.1)
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
