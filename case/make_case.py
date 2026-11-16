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
USB_W, USB_H, USB_OVER = 8.0, 3.0, 1.3       # micro-USB: width, height above the board, overhang past the board end
BOOTSEL_X, BOOTSEL_Y = 12.5, 7.0              # button centre from the USB end and from the edge with pin 1 (approx)
# --- case ---
WALL, FLOOR, TOP = 2.0, 2.0, 2.0
GAP = 0.6                                      # air around the board
UNDER = 10.0                                   # under the board: headers stick out ~8.5 mm
OVER = 5.5                                     # over the board: USB socket, RF can, header stubs
PLUG_W, PLUG_H = 12.0, 8.0                    # opening for the cable's plug
LIP, LIP_CLR = 3.0, 0.2                        # lid lip depth, clearance per side (PETG friction fit)
EAR, SCREW_D, HEAD_D = 11.0, 4.5, 8.5          # screw ears for ~4 mm wood screws, countersunk
TEXT, SUB = 'OIL TANKS', 'HAWKi'
TEXT_H = 0.8                                   # raised text height (2nd colour)

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
    usb_z = FLOOR + UNDER + PCB_T + USB_H / 2
    plug = rbox(-1, Y0 + PCB_W / 2 - PLUG_W / 2, usb_z - PLUG_H / 2, WALL + 1, Y0 + PCB_W / 2 + PLUG_W / 2, usb_z + PLUG_H / 2, 1.5)
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
    """Printed top face up: lip and posts underneath (z < 0), plate z 0..TOP, text on top."""
    plate = rbox(0, 0, 0, OUT_L, OUT_W, TOP, 3)
    c = LIP_CLR
    lip = D(box(WALL + c, WALL + c, -LIP, OUT_L - WALL - c, OUT_W - WALL - c, 0.01),
            box(WALL + c + 1.6, WALL + c + 1.6, -LIP - 1, OUT_L - WALL - c - 1.6, OUT_W - WALL - c - 1.6, 0.02))
    # posts reach the board's top face (board top is OVER below the lid's underside)
    posts = [D(cyl(x, y, -OVER, 0.01, 4.0), cyl(x, y, -OVER - 1, -OVER + 1.6, 2.2)) for x, y in holes]
    body = U(plate, lip, *posts)
    bx, by = X0 + BOOTSEL_X, Y0 + BOOTSEL_Y
    body = D(body, cyl(bx, by, -LIP - 1, TOP + 1, 6.5), box(-1, Y0 + PCB_W / 2 - PLUG_W / 2 - 0.5, -LIP - 1, WALL + c + 0.01, Y0 + PCB_W / 2 + PLUG_W / 2 + 0.5, 0.01))
    # text + logo, kept clear of the BOOTSEL hole (USB end); logo at the far end
    tx0, tx1 = bx + 5, OUT_L - 12          # text column; the drop sits in the last 12 mm
    logo = drop(OUT_L - 6.5, OUT_W / 2, 11)
    main = text_polys(TEXT, 4.6, (tx0 + tx1) / 2, OUT_W / 2 + 2.6)
    sub = text_polys(SUB, 3.8, (tx0 + tx1) / 2, OUT_W / 2 - 4.0).buffer(0.1)  # thickened so every stroke is 0.7 mm+ (2 lines of a 0.4 nozzle)
    deco = extrude(unary_union([main, sub, logo]), TOP, TEXT_H)
    return body, deco


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    b = base()
    l, t = lid()
    for name, m in (('base', b), ('lid', l), ('lid_text', t)):
        assert m.is_watertight, name
        m.export(os.path.join(OUT, 'hawki_%s.stl' % name))
    # lid + text as one file: two objects, so a multi-colour printer can give the text its own filament
    sc = trimesh.Scene()
    sc.add_geometry(l, node_name='lid', geom_name='lid')
    sc.add_geometry(t, node_name='text', geom_name='text')
    sc.export(os.path.join(OUT, 'hawki_lid_2colour.3mf'))
    print('outside %.1f x %.1f x %.1f mm (+ ears to %.1f wide), lid %.1f mm; text from z %.1f to %.1f on the lid'
          % (OUT_L, OUT_W, BASE_H, OUT_W + 2 * EAR, TOP, TOP, TOP + TEXT_H))
    print('text bounds', np.round(t.bounds, 1).tolist(), 'bootsel hole at', round(X0 + BOOTSEL_X, 1), round(Y0 + BOOTSEL_Y, 1))
