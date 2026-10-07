from datetime import UTC, date, datetime, timedelta, timezone

from athanor import almanac, moon, palette

EDT = timezone(timedelta(hours=-4))


def test_full_and_new_moon_land_on_the_minute():
    # PyEphem: new Moon 2026-10-10 15:50 UTC, full Moon 2026-10-26 04:11 UTC.
    found = almanac.events(datetime(2026, 10, 10, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC))
    phases = {e.text: e.when for e in found if e.kind == "phase"}
    assert abs(phases["New Moon"] - datetime(2026, 10, 10, 15, 50, tzinfo=UTC)) < timedelta(
        minutes=3
    )
    assert abs(phases["Full Moon"] - datetime(2026, 10, 26, 4, 11, tzinfo=UTC)) < timedelta(
        minutes=3
    )


def test_constellation_change_is_found():
    found = almanac.events(datetime(2026, 10, 8, tzinfo=UTC), datetime(2026, 10, 9, tzinfo=UTC))
    enters = [e for e in found if e.kind == "enters"]
    assert len(enters) == 1 and enters[0].text == "enters Virgo"
    assert moon.constellation(enters[0].when).name == "Virgo"
    assert moon.constellation(enters[0].when - timedelta(minutes=2)).name == "Leo"


def test_nodes_come_as_head_then_tail():
    found = almanac.events(datetime(2026, 10, 15, tzinfo=UTC), datetime(2026, 11, 5, tzinfo=UTC))
    nodes = [e.text for e in found if e.kind == "node"]
    assert nodes == ["the dragon's head", "the dragon's tail"]


def test_ascending_turns_with_sagittarius():
    found = almanac.events(datetime(2026, 10, 15, tzinfo=UTC), datetime(2026, 10, 17, tzinfo=UTC))
    assert any(e.text == "turns ascending" for e in found)


def test_unfavourable_spills_across_midnight():
    # The dragon's tail at about 22:00 EDT on the 6th still darkens the 7th.
    assert almanac.day(date(2026, 10, 7), EDT).unfavourable
    assert not almanac.day(date(2026, 10, 9), EDT).unfavourable


def test_day_takes_the_constellation_that_holds_most_of_it():
    d = almanac.day(date(2026, 10, 8), EDT)  # Leo until 17:53, then Virgo
    assert d.kind.name == "Leo"


def test_flavour_lines():
    leo = moon.Constellation("Leo", "♌", "fire")
    assert almanac.entering(leo) == "The Moon kindles into Leo. Seed and fruit swell with warmth."
    assert almanac.dwelling(leo).startswith("The Moon burns in Leo.")


def test_page_without_colour():
    text = almanac.page(date(2026, 10, 7), 3, EDT, palette.load("umber").roles, color=False)
    assert "THE ALMANAC OF THE ATHANOR" in text
    assert "enters Virgo" in text
    assert "\033[" not in text


def test_page_gives_sunrise_and_sunset_for_a_place():
    nyc = (40.71, -74.01)  # the sample place in config/athanor/athanor.toml
    text = almanac.page(date(2026, 10, 7), 1, EDT, palette.load("umber").roles, False, nyc)
    assert "06:58–18:28" in text


def test_work_follows_the_season():
    nyc = (40.71, -74.01)
    assert almanac.season(date(2026, 10, 7), nyc) == "Harvest and garlic"
    assert "garlic" in almanac.work("Root", date(2026, 10, 7), nyc)
    assert "tomatoes" not in almanac.work("Fruit", date(2026, 10, 7), nyc)
    assert "set out tomatoes" in almanac.work("Fruit", date(2026, 6, 1), nyc)
    assert almanac.season(date(2027, 1, 15), nyc) == "Deep winter"


def test_southern_hemisphere_shifts_half_a_year():
    hobart = (-42.88, 147.33)
    assert almanac.season(date(2026, 10, 7), hobart) == "Sugaring and seed-starting"
    assert almanac.season(date(2026, 4, 7), hobart) == "Harvest and garlic"


def test_sinking_moon_work_is_seasonal():
    nyc = (40.71, -74.01)
    assert "garlic" in almanac.sap(False, date(2026, 10, 7), nyc)
    assert "hay" in almanac.sap(False, date(2026, 7, 15), nyc)
