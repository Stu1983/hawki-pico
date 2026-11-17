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


def test_total():
    """all the oil (floor up): usable + below the outlet, and below the outlet only what's there"""
    from tankcalc import total
    t = {'shape': 'cuboid', 'height_cm': 90, 'outlet_cm': 10, 'length_cm': 100, 'width_cm': 100, 'tank_l': 1000, 'windows': 0}
    assert abs(total(t, 0) - 1000) < 0.5 and abs(total(t, 500) - 500) < 0.5, (total(t, 0), total(t, 500))
    assert abs(total(t, 950) - 50) < 0.5 and total(t, 1000) == 0 and litres(t, 950) == 0, total(t, 950)
    assert total({'shape': 'cuboid', 'height_cm': 90, 'capacity_l': 900, 'length_cm': 100, 'width_cm': 100}, 500) is None


def test_litres_many_same_as_litres():
    # the curve's quick path gives exactly what litres() gives, for every kind of tank settings
    from tankcalc import litres_many
    live = {"outlet_cm": 9.5, "window_model": "measured", "length_cm": 173.0, "ribs_cm": [31.5, 62.5, 93.5],
            "win_top_cm": 79.0, "win_bottom_cm": 45.0, "tank_l": 1306.0, "height_cm": 123.0, "rib_h_cm": 12.5,
            "capacity_l": 1207.3, "windows": 2, "rib_depth_cm": 1.5, "win_outer_w_cm": 39.0,
            "win_inner_w_cm": 17.0, "win_inner_h_cm": 14.0, "shape": "cuboid", "width_cm": 69.0}
    tanks = [R1225, dict(R1225, windows=0), dict(R1225, tank_l=1400, outlet_cm=8.5), live,
             dict(live, tank_l=None), dict(live, tank_l=''), dict(live, outlet_cm=0),
             {'shape': 'horizontal', 'height_cm': 100, 'capacity_l': 1000},
             {'shape': 'horizontal', 'height_cm': 100, 'capacity_l': 1000, 'tank_l': 1100, 'outlet_cm': 5},
             {'shape': 'vertical', 'height_cm': 150, 'capacity_l': 900}]
    B = dict(height_cm=100, capacity_l=1000, length_cm=100, width_cm=100)
    odd = [{}, dict(B, height_cm='bad'), dict(height_cm=100, capacity_l=1000), dict(B, width_cm='bad'),
           dict(B, windows='bad'), dict(B, window_model='measured', windows='bad'),
           dict(B, height_cm=0, window_model='measured'), dict(B, height_cm=0, capacity_l=-1, windows=2),
           dict(B, height_cm=-1, window_model='measured'), dict(B, tank_l='bad'), {'height_cm': -1}]
    levels = [None, 16383, 16382, -5, 0] + list(range(1, 1600, 7)) + [1230, 1300]

    for t in tanks + odd:
        for lv in [levels] + [[x] for x in (None, 16383, 16382, 0, 500, 1000)] + [[]]:
            try:
                want = [litres(t, x) for x in lv]
            except Exception as ex:
                want = type(ex)  # the old way's first error
            try:
                got = litres_many(t, iter(lv))
            except Exception as ex:
                got = type(ex)
            assert got == want, (t, lv, got, want)


if __name__ == '__main__':
    test_matches_magnus_app(); test_bounds_and_codes(); test_other_shapes(); test_measured_model(); test_whole_tank_capacity(); test_total(); test_litres_many_same_as_litres()
    print('all ok')
