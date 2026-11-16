import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'firmware'))
from tankcalc import litres, reading

R1225 = {'shape': 'cuboid', 'height_cm': 130, 'length_cm': 178, 'width_cm': 75,
         'capacity_l': 1323, 'windows': 2}


def test_matches_magnus_app():
    # (distance mm, litres shown by the Magnus app)
    for mm, app in ((696, 621.41), (701, 617.18), (706, 613)):
        assert abs(litres(R1225, mm) - app) < 0.6, (mm, litres(R1225, mm), app)
    l, p = reading(R1225, 701)
    assert abs(l - 617.18) < 0.1 and abs(p - 46.65) < 0.1, (l, p)


def test_bounds_and_codes():
    assert litres(R1225, 0) == 1323
    assert litres(R1225, 1300) == 0
    assert litres(R1225, 1500) == 0
    assert litres(R1225, 16383) is None
    assert litres(R1225, 16382) == 0
    assert reading(R1225, 16383) == (None, None)
    prev = -1
    for mm in range(1300, -1, -5):  # monotonic as the tank fills
        v = litres(R1225, mm)
        assert v >= prev, mm
        prev = v


def test_other_shapes():
    v = {'shape': 'vertical', 'height_cm': 100, 'capacity_l': 1000}
    assert litres(v, 500) == 500
    h = {'shape': 'horizontal', 'height_cm': 100, 'capacity_l': 1000}
    assert abs(litres(h, 500) - 500) < 0.01
    assert litres(h, 750) < 250  # a lying cylinder holds less in its bottom quarter
    c = {'shape': 'cuboid', 'height_cm': 100, 'length_cm': 100, 'width_cm': 100,
         'capacity_l': 1000, 'windows': 0}
    assert litres(c, 250) == 750


MEASURED = dict(R1225, window_model='measured', outlet_cm=10, win_bottom_cm=57, win_top_cm=80,
                win_outer_w_cm=30, win_inner_w_cm=15, win_inner_h_cm=11,
                ribs_cm=[30, 68, 106], rib_h_cm=12, rib_depth_cm=1.5)


def test_measured_model():
    m = MEASURED
    assert abs(litres(m, 0) - 1323) < 1e-6 and litres(m, 1300) == 0
    prev = -1
    for mm in range(1300, -1, -5):
        v = litres(m, mm)
        assert v >= prev - 1e-9, mm
        prev = v
    # slope inside the window band is lower than just below it
    slope = lambda mm: litres(m, mm - 5) - litres(m, mm)
    win_mid = 1300 - (68.5 * 10 - 100)   # distance reading at the window centre
    assert slope(int(win_mid)) < slope(int(1300 - 150))
    # no windows/ribs -> straight line
    plain = dict(MEASURED, windows=0, ribs_cm=[])
    assert abs(litres(plain, 650) - 1323 / 2) < 0.01


def test_whole_tank_capacity():
    from tankcalc import below, above, reading
    # spec-sheet capacity of the whole tank; the oil under the outlet is worked out and left out
    t = dict(MEASURED, height_cm=121.5, outlet_cm=8.5, tank_l=1268)
    t.pop('capacity_l', None)
    b, a = below(t), above(t)
    assert 80 < b < 115 and abs(a + b - 1268) < 1e-6, (b, a)
    assert abs(litres(t, 0) - a) < 0.5  # full = everything above the outlet
    assert litres(t, 1215) == 0 and litres(t, 1260) == 0  # at / below the top of the outlet: none usable
    assert litres(t, 16383) is None and litres(t, 16382) == 0
    assert abs(reading(t, 0)[1] - 100) < 0.1  # percent of the usable capacity
    # a real R1225 (measured outside): its metered 500 L delivery (1149 -> 601 mm) comes out at 500 with 1268 L
    real = dict(shape='cuboid', height_cm=121.5, outlet_cm=8.5, length_cm=178, width_cm=75, windows=2, tank_l=1268,
                window_model='measured', win_bottom_cm=45, win_top_cm=79, win_outer_w_cm=39, win_inner_w_cm=17,
                win_inner_h_cm=14, ribs_cm=[31.5, 62.5, 93.5], rib_h_cm=12, rib_depth_cm=1.5)
    assert abs(litres(real, 601) - litres(real, 1149) - 500) < 2
    # no outlet: same as the old fill-height capacity
    p = dict(MEASURED, outlet_cm=0, tank_l=1323)
    p.pop('capacity_l', None)
    assert below(p) == 0 and abs(litres(p, 650) - litres(MEASURED_NO_OUTLET(), 650)) < 1e-6


def MEASURED_NO_OUTLET():
    return dict(MEASURED, outlet_cm=0, capacity_l=1323)


if __name__ == '__main__':
    test_matches_magnus_app(); test_bounds_and_codes(); test_other_shapes(); test_measured_model(); test_whole_tank_capacity()
    print('all ok')
