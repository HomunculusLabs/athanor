"""The biodynamic almanac: each day's events, the week ahead, and a few words.

Everything is found the same way: sample the Moon each hour, then halve the
hour where something changed until the moment is known to the minute.
"""

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from . import moon, sky

HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class Event:
    when: datetime
    kind: str  # enters, turns, node, perigee, apogee, phase
    text: str
    sign: str = ""  # an Athanor glyph to go with it


def _bisect(lo: datetime, hi: datetime, test) -> datetime:
    """test(lo) is False and test(hi) is True; find where it flips."""
    while hi - lo > MINUTE:
        mid = lo + (hi - lo) / 2
        if test(mid):
            hi = mid
        else:
            lo = mid
    return hi


def events(start: datetime, end: datetime) -> list[Event]:
    """Everything the Moon does between two moments (timezone-aware)."""
    found: list[Event] = []
    t = start
    prev = _sample(t)
    while t < end:
        nxt_t = min(t + HOUR, end)
        cur = _sample(nxt_t)

        if cur["where"] != prev["where"]:
            was = prev["where"]
            when = _bisect(t, nxt_t, lambda m, was=was: moon.constellation(m) != was)
            c = moon.constellation(when)
            found.append(Event(when, "enters", f"enters {c.name}", c.sign))

        if cur["rising"] != prev["rising"]:
            rising = cur["rising"]
            when = _bisect(t, nxt_t, lambda m, r=rising: moon.ascending(m) == r)
            found.append(Event(when, "turns", "turns ascending" if rising else "turns descending"))

        if (cur["lat"] >= 0) != (prev["lat"] >= 0):
            north = cur["lat"] >= 0
            when = _bisect(t, nxt_t, lambda m, n=north: (moon.position(m).latitude >= 0) == n)
            # The dragon's head where the Moon climbs north of the Sun's path,
            # its tail where it falls back south.
            found.append(
                Event(
                    when,
                    "node",
                    "the dragon's head" if north else "the dragon's tail",
                    "☊" if north else "☋",
                )
            )

        if prev["approach"] is not None and cur["approach"] != prev["approach"]:
            closing = prev["approach"]
            when = _bisect(t, nxt_t, lambda m, c=closing: _approach(m) != c)
            kind = "perigee" if closing else "apogee"
            found.append(Event(when, kind, "nearest the Earth" if closing else "farthest out"))

        quarter_prev, quarter_cur = int(prev["elong"] // 90), int(cur["elong"] // 90)
        if quarter_cur != quarter_prev:
            q = quarter_cur
            when = _bisect(t, nxt_t, lambda m, q=q: int(moon.elongation(m) // 90) == q)
            found.append(Event(when, "phase", moon.PHASE_NAMES[q], PHASE_SIGNS[q]))

        prev, t = cur, nxt_t
    return sorted(found, key=lambda e: e.when)


def _approach(when: datetime) -> bool:
    """True while the Moon is drawing closer to the Earth."""
    return moon.position(when + MINUTE * 30).distance < moon.position(when - MINUTE * 30).distance


def _sample(when: datetime) -> dict:
    p = moon.position(when)
    return {
        "where": moon.constellation(when),
        "rising": moon.ascending(when),
        "lat": p.latitude,
        "approach": _approach(when),
        "elong": moon.elongation(when),
    }


PHASE_SIGNS = ("\U0001f311", "\U0001f313", "\U0001f315", "\U0001f317")


def phase_sign(when: datetime) -> str:
    """One of Athanor's eight moon-phase glyphs for this moment."""
    return chr(0x1F311 + int(moon.elongation(when) / 45 + 0.5) % 8)


# How far either side of the moment Thun counts as unfavourable.
SPILL = {"node": timedelta(hours=6), "perigee": timedelta(hours=12)}


@dataclass(frozen=True)
class Day:
    date: object  # datetime.date
    kind: moon.Constellation  # the constellation that holds most of the day
    events: tuple[Event, ...]
    unfavourable: bool  # a node or perigee falls in the day, or spills into it


def day(date, tz) -> Day:
    start = datetime.combine(date, time(), tz)
    end = start + timedelta(days=1)
    held = Counter(moon.constellation(start + HOUR * h + MINUTE * 30) for h in range(24))
    widest = max(SPILL.values())
    nearby = events(start - widest, end + widest)
    unlucky = any(
        e.kind in SPILL and start - SPILL[e.kind] <= e.when < end + SPILL[e.kind] for e in nearby
    )
    inside = tuple(e for e in nearby if start <= e.when < end)
    return Day(date, held.most_common(1)[0][0], inside, unlucky)


def days(first, count: int, tz) -> list[Day]:
    return [day(first + timedelta(days=i), tz) for i in range(count)]


# Flavour, in the voice of the rest of the screen.
VERBS = {"earth": "settles", "water": "drifts", "air": "rises", "fire": "kindles"}
DAY_LINES = {
    "Root": "The roots stir beneath the soil.",
    "Leaf": "Sap gathers in the green leaf.",
    "Flower": "The blossoms turn their faces to the light.",
    "Fruit": "Seed and fruit swell with warmth.",
}
# What each day type is good for depends on the time of year. These follow a
# cold northern climate with a short season, about USDA zone 4; in the
# southern hemisphere the months shift by half a year.
SEASONS = (
    # (months, name)
    ((12, 1, 2), "Deep winter"),
    ((3, 4), "Sugaring and seed-starting"),
    ((5, 6), "Planting out"),
    ((7, 8), "High summer"),
    ((9, 10), "Harvest and garlic"),
    ((11,), "Putting the beds to bed"),
)
SEASONAL_WORK = {
    "Deep winter": {
        "Root": "Check the roots in the cellar and turn out any going soft.",
        "Leaf": "Grow greens and microgreens indoors; plan the leaf beds.",
        "Flower": "Order flower and brassica seed; draw up the beds.",
        "Fruit": "Prune apple and pear trees on mild days; sort and test saved seed.",
    },
    "Sugaring and seed-starting": {
        "Root": "Start onions and leeks indoors; dig parsnips left in the ground.",
        "Leaf": "Start cabbage, kale and lettuce indoors; sow spinach under cover.",
        "Flower": "Start broccoli, cauliflower and flowers indoors.",
        "Fruit": "Start tomatoes and peppers indoors; sow peas once the soil can be worked.",
    },
    "Planting out": {
        "Root": "Plant potatoes; sow carrots, beets and radishes; set out onions.",
        "Leaf": "Sow lettuce, greens and herbs; set out the brassicas.",
        "Flower": "Set out broccoli and cauliflower; plant flowers after the last frost.",
        "Fruit": "Once the frost is past, set out tomatoes and squash; sow beans and corn.",
    },
    "High summer": {
        "Root": "Hill the potatoes; sow carrots and beets for fall; lift the garlic.",
        "Leaf": "Sow fall greens and kale; cut leaf crops to eat fresh.",
        "Flower": "Cut flowers and broccoli; make hay.",
        "Fruit": "Pick beans, cucumbers and tomatoes; save seed.",
    },
    "Harvest and garlic": {
        "Root": "Dig potatoes, carrots and beets for the cellar; plant the garlic.",
        "Leaf": "Eat kale and cabbage now rather than store them; sow cover crops.",
        "Flower": "Cut the last flowers; bring in broccoli and cauliflower before hard frost.",
        "Fruit": "Pick apples and cure squash for storage; save seed.",
    },
    "Putting the beds to bed": {
        "Root": "Mulch the garlic; dig the last roots before the ground freezes.",
        "Leaf": "Pull the last kale; spread leaves over the beds.",
        "Flower": "Clean and put away the tools; plan next year's flowers.",
        "Fruit": "Look over the stored apples and squash; spread compost and manure.",
    },
}
# Thun: a crop keeps best when it is harvested on its own kind of day.
KEEPING = {
    "Root": "Roots lifted today keep well in the cellar.",
    "Leaf": "Leaf crops cut today are for eating, not keeping.",
    "Flower": "Flowers cut today hold their colour and scent.",
    "Fruit": "Fruit and seed gathered today keep well.",
}


def season(when, place=None) -> str:
    month = when.month
    if place and place[0] < 0:
        month = (month + 5) % 12 + 1
    for months, name in SEASONS:
        if month in months:
            return name
    return SEASONS[0][1]


def work(day: str, when, place=None) -> str:
    return SEASONAL_WORK[season(when, place)][day]


RISING = {
    True: "The Moon climbs, and the sap with it.",
    False: "The Moon sinks, and the sap with it.",
}
# What the climbing (True) and sinking (False) Moon favour, season by season.
SAP_WORK = {
    "Deep winter": {
        True: "Cut scions for grafting; start cuttings indoors.",
        False: "Prune fruit trees and berry canes.",
    },
    "Sugaring and seed-starting": {
        True: "Graft; sow under cover.",
        False: "Prune; prick out and pot on seedlings.",
    },
    "Planting out": {
        True: "Sow seed; graft.",
        False: "Transplant seedlings; spread compost.",
    },
    "High summer": {
        True: "Gather fruit and leaf for eating.",
        False: "Cut hay; transplant the fall crops.",
    },
    "Harvest and garlic": {
        True: "Gather apples and seed.",
        False: "Plant garlic and bulbs; spread compost; move perennials.",
    },
    "Putting the beds to bed": {
        True: "Gather the last of the fruit.",
        False: "Spread compost and mulch; plant trees while they sleep.",
    },
}


def sap(rising: bool, when, place=None) -> str:
    return f"{RISING[rising]} {SAP_WORK[season(when, place)][rising]}"


UNFAVOURABLE = {
    "node": "The Moon crosses the dragon's path. Leave the seed in its packet.",
    "perigee": "The Moon leans close to the Earth. Its pull unsettles the beds.",
}


DWELLS = {"earth": "rests", "water": "drifts", "air": "rides", "fire": "burns"}


def entering(c: moon.Constellation) -> str:
    return f"The Moon {VERBS[c.element]} into {c.name}. {DAY_LINES[c.day]}"


def dwelling(c: moon.Constellation) -> str:
    return f"The Moon {DWELLS[c.element]} in {c.name}. {DAY_LINES[c.day]}"


# Printing ------------------------------------------------------------------


def _sgr(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return f"\033[38;2;{int(h[0:2], 16)};{int(h[2:4], 16)};{int(h[4:6], 16)}m"


# The almanac's window lists Athanor right after the text face. Zodiac signs,
# moon phases and the nodes are also emoji, so each carries U+FE0E to ask for
# the text form, which Athanor draws. Terminals disagree on how many cells
# such a sign takes, and Athanor's signs spill past their cell anyway, so
# every column is placed at a fixed position rather than trusting widths.
TEXT = "\ufe0e"
DAY_SIGNS = {day: sign for day, sign in moon.DAYS.values()}

COLUMNS = {
    "date": 3,
    "phase": 11,
    "daysign": 15,
    "day": 18,
    "zodiac": 26,
    "name": 30,
    "arrow": 42,
    "sun": 46,
}
EVENTS_AT, EVENT_WIDTH = 63, 34
LEGEND = {"sign": 3, "word": 9, "text": 18}


def _row(cells: list[tuple[int, str]], ansi: bool) -> str:
    """Lay out (column, text) cells: cursor moves in a terminal, spaces elsewhere."""
    out, at = "", 1
    for column, text in cells:
        if ansi:
            out += f"\033[{column}G{text}"
        else:
            out += " " * max(1, column - at) + text
            at = column + len(re.sub(r"\033\[[0-9;]*m", "", text))
    return out


def page(first, count: int, tz, roles: dict[str, str], color: bool = True, place=None) -> str:
    """A month of days as a terminal page; with a place, each day's sunrise and sunset."""

    def c(text: str, role: str, bold: bool = False) -> str:
        if not color:
            return text
        return ("\033[1m" if bold else "") + _sgr(roles[role]) + text + "\033[0m"

    def glyph(sign: str) -> str:
        return sign + TEXT if color else sign

    out = [
        "",
        "  " + c("THE ALMANAC OF THE ATHANOR", "active", True),
        "  "
        + c(f"the Moon among the stars, after Maria Thun   \u00b7   {season(first, place)}", "dim")
        + (c(f"   \u00b7   at {place[0]:.2f}, {place[1]:.2f}", "dim") if place else ""),
        "",
    ]
    last_month = None
    for d in days(first, count, tz):
        if d.date.month != last_month:
            last_month = d.date.month
            out.append("  " + c(f"{d.date:%B %Y}", "fg", True))
        noon = datetime.combine(d.date, time(12), tz)
        day_role = "bar_warn" if d.unfavourable else "active" if d.date == first else "fg"
        cells = [
            (COLUMNS["date"], f"{d.date:%a %e}"),
            (COLUMNS["phase"], glyph(phase_sign(noon))),
            (COLUMNS["daysign"], c(d.kind.day_sign, day_role)),
            (COLUMNS["day"], c(d.kind.day, day_role, True)),
            (COLUMNS["zodiac"], glyph(d.kind.sign)),
            (COLUMNS["name"], d.kind.name),
            (COLUMNS["arrow"], "\u2191" if moon.ascending(noon) else "\u2193"),
        ]
        sun = sky.sun_times(d.date, *place, tz) if place else None
        if sun:
            rise, set_ = (t.astimezone(tz) for t in sun)
            cells.append((COLUMNS["sun"], c(f"\u2609 {rise:%H:%M}\u2013{set_:%H:%M}", "dim")))
        for n, e in enumerate(d.events):
            role = (
                "bar_warn" if e.kind in SPILL else "fg" if e.kind in ("enters", "phase") else "dim"
            )
            at = EVENTS_AT + n * EVENT_WIDTH
            cells.append((at, c(f"{e.when.astimezone(tz):%H:%M}", role)))
            if e.sign:
                cells.append((at + 6, c(glyph(e.sign), role)))
            cells.append((at + 9, c(e.text, role)))
        out.append(_row(cells, color))

    def legend(sign: str, word: str, text: str, role: str = "fg") -> str:
        return _row(
            [
                (LEGEND["sign"], c(sign, role)),
                (LEGEND["word"], c(word, role, True)),
                (LEGEND["text"], text),
            ],
            color,
        )

    out += [
        "",
        *(
            legend(DAY_SIGNS[name], name, work(name, first, place))
            for name in ("Root", "Leaf", "Flower", "Fruit")
        ),
        legend("\u2191", "Rising", sap(True, first, place)),
        legend("\u2193", "Sinking", sap(False, first, place)),
        legend(glyph("\u260a") + " " + glyph("\u260b"), "Node", UNFAVOURABLE["node"], "bar_warn"),
        legend("", "Perigee", UNFAVOURABLE["perigee"], "bar_warn"),
        "",
        "  "
        + c(
            "Constellations as they stand in the sky; edges good to a few hours "
            "against a printed calendar.",
            "dim",
        ),
        "",
    ]
    return "\n".join(out)
