"""Magnus HAWKi BLE advert decoder (runs on CPython and MicroPython).

Port of parseDT8advertisingRawData from the Magnus app (com.magnusmonitors.user 3.0.2,
Hermes bundle). Input = the 10 bytes of the 0xFF (manufacturer) AD structure; the
"company ID" is really part of the payload. Fields are bit-packed, not encrypted.
level = mm from sensor to liquid surface (16383 = unknown, 16382 = nearly empty).
timestamp = sensor's own clock (unix s) at measurement; may be wrong on unsynced sensors.
"""


def volts(b):
    """The battery field is the cell's voltage above 3 V, in hundredths: 62 = 3.62 V (the Magnus app shows it as
    '3.' and two digits). A new lithium cell reads about 3.8 V; the app says BAD by 3.62 V."""
    return None if b is None else round(3 + b / 100, 2)


def decode(d):
    d = bytes(d)
    n = len(d)
    if n < 1:
        return {}
    pt = d[0] & 0x0F
    r = {'packetType': pt}
    if n < 7 or (pt < 4 and n < 9):
        return r
    if pt <= 3:
        r['timestamp'] = ((d[4] & 0xF) << 28) | (d[3] << 20) | (d[2] << 12) | (d[1] << 4) | (d[0] >> 4)
        r['level'] = ((d[6] & 3) << 12) | (d[5] << 4) | (d[4] >> 4)
    if pt == 3:
        r['floatSensorData'] = (d[6] >> 2) & 3
        r['temperature'] = ((d[7] & 7) << 4) | (d[6] >> 4)
        r['battery'] = ((d[8] & 3) << 5) | (d[7] >> 3)
        r['errorStatus'] = d[8] >> 2
        r['firmwareVersion'] = d[9] if n > 9 else None
    elif pt < 3:
        r['temperature'] = ((d[7] & 1) << 6) | (d[6] >> 2)
        r['battery'] = d[7] >> 1
        r['errorStatus'] = d[8]
    elif pt == 4:
        r['packetId'] = ((d[1] & 0xF) << 4) | (d[0] >> 4)
        r['level'] = ((d[3] & 3) << 12) | (d[2] << 4) | (d[1] >> 4)
        r['floatSensorData'] = (d[3] >> 2) & 3
        r['temperature'] = ((d[4] & 7) << 4) | (d[3] >> 4)
        r['battery'] = ((d[5] & 3) << 5) | (d[4] >> 3)
        r['errorStatus'] = d[5] >> 2
        r['firmwareVersion'] = d[6]
    if r.get('battery') is not None:
        r['volts'] = volts(r['battery'])
    if 'level' in r:
        r['isUnknownLevel'] = r['level'] == 16383
        r['isNearlyEmpty'] = r['level'] == 16382
    return r


def mfr_from_adv(adv):
    """Return the 0xFF (manufacturer data) AD payload from a raw advert, or None."""
    adv = bytes(adv)
    i = 0
    while i + 1 < len(adv):
        l = adv[i]
        if l == 0:
            break
        if adv[i + 1] == 0xFF:
            return adv[i + 2:i + 1 + l]
        i += 1 + l
    return None
