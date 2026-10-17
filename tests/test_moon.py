from datetime import UTC, datetime, timedelta

from athanor import almanac, cli, config, moon


def test_position_matches_meeus_example_47a():
    # 1992 April 12, 0h TD: longitude 133.162655, latitude -3.229126, 368409.7 km.
    p = moon.position(datetime(1992, 4, 12, tzinfo=UTC) - moon.TT_MINUS_UTC)
    assert abs(p.longitude - 133.162655) < 0.01
    assert abs(p.latitude - -3.229126) < 0.01
    assert abs(p.distance - 368409.7) < 50


def test_constellation_and_day():
    # Checked against PyEphem: the Moon at 151 degrees on 2026-10-07 is in Leo.
    here = moon.constellation(datetime(2026, 10, 7, 5, tzinfo=UTC))
    assert (here.name, here.day) == ("Leo", "Fruit")
    assert moon.constellation(datetime(2026, 10, 10, 5, tzinfo=UTC)).day == "Root"


def test_every_element_has_its_day():
    days = {moon.Constellation(n, s, e).day for _, n, s, e in moon.CONSTELLATIONS}
    assert days == {"Root", "Leaf", "Flower", "Fruit"}


def test_ascending_turns_in_sagittarius():
    assert not moon.ascending(datetime(2026, 10, 10, tzinfo=UTC))
    assert moon.ascending(datetime(2026, 10, 18, tzinfo=UTC))


def test_next_change_lands_on_the_boundary():
    start = datetime(2026, 10, 7, 5, tzinfo=UTC)
    when, nxt = moon.next_change(start)
    assert nxt.name == "Virgo"
    assert moon.constellation(when - timedelta(minutes=2)).name == "Leo"
    assert moon.constellation(when).name == "Virgo"


def test_bar_markup_carries_planet_and_moon_signs():
    text = cli._bar_markup(datetime(2026, 10, 7, 0, 35).astimezone(), config.load())
    assert "Hour of the Moon" in text
    assert cli.SIGN_FONT in text
    assert text.index("♂") < text.index("☽")  # the day of Mars, the hour of the Moon
    assert 'fallback="false"' in text


def test_moon_signs_ink_the_light():
    # Light ink on a dark bar: a new moon is the empty ring, a full moon solid.
    assert almanac.lit_sign(0) == "\U0001f315"
    assert almanac.lit_sign(4) == "\U0001f311"
    assert almanac.lit_sign(1) == "\U0001f316"  # waxing crescent: ink on the right


def test_moon_line_names_the_constellation_and_day():
    text, tip = cli._moon_lines(datetime(2026, 10, 7, 0, 35).astimezone())
    assert "Fruit" in text and "Leo" not in text  # the bar keeps to the day itself
    assert "Root Thu 17:53" in text
    assert "\u260b" in text  # the dragon's tail, last night
    assert "The Moon burns in Leo" in tip
    assert "Wed fruit (unlucky)" in tip  # the dragon's tail the night before


def test_brief_moon_line_leaves_the_turn_to_the_tooltip():
    text, tip = cli._moon_lines(datetime(2026, 10, 7, 0, 35).astimezone(), brief=True)
    assert "Fruit" in text and "then" not in text
    assert "Into Virgo (root)" in tip


def test_hour_tooltip_gives_local_sun_times():
    from dataclasses import replace
    from datetime import timezone

    cfg = replace(config.load(), place=(40.71, -74.01))  # the sample place
    edt = datetime(2026, 10, 7, 12, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert cli._hour_lines(edt, cfg)["sun"] == "Sunrise 06:58, sunset 18:28"
