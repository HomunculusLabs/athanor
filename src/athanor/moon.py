"""Where the Moon is, for the biodynamic (Maria Thun) calendar.

The Moon's position comes from the main periodic terms of Meeus, Astronomical
Algorithms, ch. 47: good to a few hundredths of a degree, so a constellation
change lands within a few minutes. The calendar reads the Moon against the
constellations as they stand in the sky (sidereal and of unequal width), not
the twelve equal signs of the tropical zodiac. Their edges are where the IAU
constellation boundaries cross the ecliptic (J2000); the part of Ophiuchus on
the ecliptic counts as Scorpio, as Thun's calendar has it.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# (D, M, M', F, longitude 1e-6 deg, distance 1e-3 km)
_LR = (
    (0, 0, 1, 0, 6288774, -20905355),
    (2, 0, -1, 0, 1274027, -3699111),
    (2, 0, 0, 0, 658314, -2955968),
    (0, 0, 2, 0, 213618, -569925),
    (0, 1, 0, 0, -185116, 48888),
    (0, 0, 0, 2, -114332, -3149),
    (2, 0, -2, 0, 58793, 246158),
    (2, -1, -1, 0, 57066, -152138),
    (2, 0, 1, 0, 53322, -170733),
    (2, -1, 0, 0, 45758, -204586),
    (0, 1, -1, 0, -40923, -129620),
    (1, 0, 0, 0, -34720, 108743),
    (0, 1, 1, 0, -30383, 104755),
    (2, 0, 0, -2, 15327, 10321),
    (0, 0, 1, 2, -12528, 0),
    (0, 0, 1, -2, 10980, 79661),
    (4, 0, -1, 0, 10675, -34782),
    (0, 0, 3, 0, 10034, -23210),
    (4, 0, -2, 0, 8548, -21636),
    (2, 1, -1, 0, -7888, 24208),
    (2, 1, 0, 0, -6766, 30824),
    (1, 0, -1, 0, -5163, -8379),
    (1, 1, 0, 0, 4987, -16675),
    (2, -1, 1, 0, 4036, -12831),
    (2, 0, 2, 0, 3994, -10445),
    (4, 0, 0, 0, 3861, -11650),
    (2, 0, -3, 0, 3665, 14403),
    (0, 1, -2, 0, -2689, -7003),
    (2, 0, -1, 2, -2602, 0),
    (2, -1, -2, 0, 2390, 10056),
    (1, 0, 1, 0, -2348, 6322),
    (2, -2, 0, 0, 2236, -9884),
    (0, 1, 2, 0, -2120, 5751),
    (0, 2, 0, 0, -2069, 0),
)

# (D, M, M', F, latitude 1e-6 deg)
_B = (
    (0, 0, 0, 1, 5128122),
    (0, 0, 1, 1, 280602),
    (0, 0, 1, -1, 277693),
    (2, 0, 0, -1, 173237),
    (2, 0, -1, 1, 55413),
    (2, 0, -1, -1, 46271),
    (2, 0, 0, 1, 32573),
    (0, 0, 2, 1, 17198),
    (2, 0, 1, -1, 9266),
    (0, 0, 2, -1, 8822),
    (2, -1, 0, -1, 8216),
    (2, 0, -2, -1, 4324),
    (2, 0, 1, 1, 4200),
    (2, 1, 0, -1, -3359),
    (2, -1, -1, 1, 2463),
    (2, -1, 0, 1, 2211),
    (2, -1, -1, -1, 2065),
    (0, 1, -1, -1, -1870),
    (4, 0, -1, -1, 1828),
    (0, 1, 0, 1, -1794),
)

J2000 = datetime(2000, 1, 1, 12, tzinfo=UTC)
# TT runs about 69 s ahead of UTC in the 2020s; a minute is all the Moon cares about.
TT_MINUS_UTC = timedelta(seconds=69)


@dataclass(frozen=True)
class Position:
    longitude: float  # ecliptic, of date, degrees
    latitude: float  # degrees
    distance: float  # km
    declination: float  # degrees


def _centuries(when: datetime) -> float:
    return ((when + TT_MINUS_UTC) - J2000).total_seconds() / (86400 * 36525)


def position(when: datetime) -> Position:
    t = _centuries(when)
    rad = math.radians
    lp = 218.3164477 + 481267.88123421 * t
    d = 297.8501921 + 445267.1114034 * t
    m = 357.5291092 + 35999.0502909 * t
    mp = 134.9633964 + 477198.8675055 * t
    f = 93.2720950 + 483202.0175233 * t
    a1 = 119.75 + 131.849 * t
    a2 = 53.09 + 479264.290 * t
    a3 = 313.45 + 481266.484 * t
    e = 1 - 0.002516 * t - 0.0000074 * t * t

    sl = sr = sb = 0.0
    for cd, cm, cmp, cf, lon, dist in _LR:
        arg = rad(cd * d + cm * m + cmp * mp + cf * f)
        k = e ** abs(cm)
        sl += lon * k * math.sin(arg)
        sr += dist * k * math.cos(arg)
    for cd, cm, cmp, cf, lat in _B:
        sb += lat * e ** abs(cm) * math.sin(rad(cd * d + cm * m + cmp * mp + cf * f))
    sl += 3958 * math.sin(rad(a1)) + 1962 * math.sin(rad(lp - f)) + 318 * math.sin(rad(a2))
    sb += (
        -2235 * math.sin(rad(lp))
        + 382 * math.sin(rad(a3))
        + 175 * math.sin(rad(a1 - f))
        + 175 * math.sin(rad(a1 + f))
        + 127 * math.sin(rad(lp - mp))
        - 115 * math.sin(rad(lp + mp))
    )

    lon = (lp + sl / 1e6) % 360
    lat = sb / 1e6
    eps = rad(23.4392911 - 0.0130042 * t)
    dec = math.asin(
        math.sin(rad(lat)) * math.cos(eps) + math.cos(rad(lat)) * math.sin(eps) * math.sin(rad(lon))
    )
    return Position(lon, lat, 385000.56 + sr / 1000, math.degrees(dec))


# Where each constellation starts along the ecliptic (J2000 longitude), with
# its element and the plant part it favours in Thun's calendar.
CONSTELLATIONS = (
    (28.7, "Aries", "♈", "fire"),
    (53.4, "Taurus", "♉", "earth"),
    (90.1, "Gemini", "♊", "air"),
    (117.9, "Cancer", "♋", "water"),
    (138.0, "Leo", "♌", "fire"),
    (173.9, "Virgo", "♍", "earth"),
    (217.8, "Libra", "♎", "air"),
    (241.0, "Scorpio", "♏", "water"),
    (266.2, "Sagittarius", "♐", "fire"),
    (299.6, "Capricorn", "♑", "earth"),
    (327.4, "Aquarius", "♒", "air"),
    (351.5, "Pisces", "♓", "water"),
)

# Element -> (day, Athanor's private-use sign for it)
DAYS = {
    "earth": ("Root", ""),
    "water": ("Leaf", ""),
    "air": ("Flower", ""),
    "fire": ("Fruit", ""),
}

PRECESSION = 1.3969713  # degrees of longitude per century


@dataclass(frozen=True)
class Constellation:
    name: str
    sign: str
    element: str

    @property
    def day(self) -> str:
        return DAYS[self.element][0]

    @property
    def day_sign(self) -> str:
        return DAYS[self.element][1]


def constellation(when: datetime) -> Constellation:
    lon = (position(when).longitude - PRECESSION * _centuries(when)) % 360
    current = CONSTELLATIONS[-1]
    for entry in CONSTELLATIONS:
        if lon >= entry[0]:
            current = entry
    return Constellation(current[1], current[2], current[3])


def ascending(when: datetime) -> bool:
    """Biodynamic 'ascending': each day the Moon climbs higher in the sky."""
    hour = timedelta(hours=1)
    return position(when + hour).declination > position(when - hour).declination


def next_change(when: datetime, limit_days: int = 4) -> tuple[datetime, Constellation] | None:
    """When the Moon next crosses into another constellation, to the minute."""
    start = constellation(when)
    step = timedelta(hours=1)
    t = when
    for _ in range(limit_days * 24):
        nxt = t + step
        if constellation(nxt) != start:
            lo, hi = t, nxt
            while hi - lo > timedelta(minutes=1):
                mid = lo + (hi - lo) / 2
                if constellation(mid) == start:
                    lo = mid
                else:
                    hi = mid
            return hi, constellation(hi)
        t = nxt
    return None


def at_node(when: datetime) -> bool:
    # The Moon crosses the ecliptic at about 1.2 degrees of latitude a day;
    # Thun marks about six hours either side as unfavourable.
    return abs(position(when).latitude) < 0.3


def near_perigee(when: datetime, hours: int = 12) -> bool:
    """Closest approach to Earth within half a day either side."""
    step = timedelta(hours=1)
    dists = [position(when + step * i).distance for i in range(-hours, hours + 1)]
    low = dists.index(min(dists))
    return 0 < low < len(dists) - 1


def sun_longitude(when: datetime) -> float:
    """The Sun's apparent longitude, Meeus ch. 25 (low precision, about 0.01 degree)."""
    t = _centuries(when)
    rad = math.radians
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = rad(357.52911 + 35999.05029 * t - 0.0001537 * t * t)
    c = (
        (1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m)
        + (0.019993 - 0.000101 * t) * math.sin(2 * m)
        + 0.000289 * math.sin(3 * m)
    )
    omega = rad(125.04 - 1934.136 * t)
    return (l0 + c - 0.00569 - 0.00478 * math.sin(omega)) % 360


def elongation(when: datetime) -> float:
    """How far the Moon has run ahead of the Sun: 0 new, 90 first quarter, 180 full."""
    return (position(when).longitude - sun_longitude(when)) % 360


PHASE_NAMES = ("New Moon", "First Quarter", "Full Moon", "Last Quarter")
