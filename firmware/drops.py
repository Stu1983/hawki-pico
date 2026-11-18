"""Sudden-drop (leak or theft) check (runs on CPython and MicroPython).

A burner can only burn so much an hour (domestic oil boilers ~1.5-3.5 L/h; 6 L/h covers almost any).
Readings come hourly in ~5 L steps and move a little with temperature, so one hour is compared with
several: oil lost since each reading in the last WINDOW hours, against what the burner could have used
in that time plus SLACK. To rule out one bad reading, the reading after must show the same.
"""

WINDOW = 23400        # look back this far (s): 6.5 h (an int: epoch arithmetic must never go through a float)
SLACK = 15.0          # litres: two 5 mm steps plus temperature (at least; more on a tank where 5 mm is more)


def excess(recent, cap, i=None, slack=SLACK):
    """recent: [(epoch, litres)] sorted by time. Litres lost beyond what the burner could explain by
    reading i (default the newest), and over how many hours; (0, 0) if none."""
    i = len(recent) - 1 if i is None else i
    if i < 1:
        return 0.0, 0.0
    tn, ln = recent[i]
    worst, hrs = 0.0, 0.0
    # baselines need two readings in a row agreeing (the lower of the pair), so one bad HIGH reading
    # can't make every later reading look like a big drop
    for j in range(1, i):
        t, l = recent[j][0], min(recent[j][1], recent[j - 1][1])
        h = (tn - t) / 3600
        if h * 3600 > WINDOW or h <= 0:
            continue
        x = (l - ln) - (cap * max(h, 1.0) + slack)
        if x > worst:
            worst, hrs = x, h
    return worst, hrs


def check(recent, cap, slack=SLACK):
    """Alert-worthy? Returns (litres lost, hours) for the message, or None. Needs the newest reading
    AND the one before it to both show the excess (a single bad reading doesn't count)."""
    if len(recent) < 3:
        return None
    a, _ = excess(recent, cap, len(recent) - 2, slack)
    b, _ = excess(recent, cap, None, slack)
    if a > 0 and b > 0:
        tn, ln = recent[-1]
        lost, hrs = 0.0, 0.0
        for t, l in recent[:-1]:  # the whole drop, for the message
            if tn - t <= WINDOW and l - ln > lost:
                lost, hrs = l - ln, (tn - t) / 3600
        return lost, hrs
    return None
