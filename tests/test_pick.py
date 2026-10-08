from datetime import UTC

from athanor import pick

HDMI = "GB203 High Definition Audio Controller Digital Stereo (HDMI) [Odyssey G95NC]"


def sink(index, name, description, percent, mute=False):
    return {
        "index": index,
        "name": name,
        "description": description,
        "mute": mute,
        "volume": {"front-left": {"value_percent": f"{percent}%"}},
    }


def test_short_names_drop_the_controller():
    assert pick._short(HDMI) == "Odyssey G95NC"
    assert pick._short("TCL Alto 6+") == "TCL Alto 6+"


def test_mixer_rows_show_outputs_inputs_and_where_each_app_plays():
    m = pick.Mixer(
        outputs=[sink(57, "hdmi", HDMI, 51), sink(68, "bt", "TCL Alto 6+", 95)],
        inputs=[sink(70, "mic", "USB Mic", 40, mute=True)],
        streams=[
            {
                "index": 6704,
                "sink": 68,
                "mute": False,
                "properties": {"application.name": "Brave"},
                "volume": {"front-left": {"value_percent": "97%"}},
            }
        ],
        default_out="bt",
        default_in="mic",
    )
    rows, picks = pick.mixer_rows(m)
    assert rows == [
        "Out    Odyssey G95NC  51%",
        "Out  ✓ TCL Alto 6+  95%",
        "In   ✓ USB Mic  mute",
        "App    Brave → TCL Alto 6+  97%",
    ]
    assert [kind for kind, _ in picks] == ["out", "out", "in", "app"]


def test_night_temperature_is_the_schedules_warmest(tmp_path):
    conf = tmp_path / "hyprsunset.conf"
    conf.write_text(
        "profile {\n time = 07:15\n identity = true\n}\n"
        "profile {\n time = 15:50\n temperature = 3500\n}\n"
    )
    assert pick.night_temperature(conf) == 3500
    assert pick.night_temperature(tmp_path / "missing.conf") == 4000


SCHEDULE = (
    "profile {\n time = 07:15\n identity = true\n}\n"
    "profile {\n time = 15:50\n temperature = 3500\n}\n"
)


def at(hour, minute=0, day=8):
    from datetime import datetime

    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def test_night_follows_the_schedule(tmp_path, monkeypatch):
    conf = tmp_path / "hyprsunset.conf"
    conf.write_text(SCHEDULE)
    monkeypatch.setattr(pick, "_night_state", lambda: tmp_path / "night.json")
    # hyprsunset's own report is not trusted: it says 3500 after identity.
    monkeypatch.setattr(pick, "_run", lambda *cmd: "3500")
    assert not pick.night_on(at(12), conf)
    assert pick.night_on(at(20), conf)
    assert pick.night_on(at(3), conf)  # yesterday evening's switch still holds


def test_a_change_holds_until_the_next_switch(tmp_path, monkeypatch):
    import json

    conf = tmp_path / "hyprsunset.conf"
    conf.write_text(SCHEDULE)
    state = tmp_path / "night.json"
    monkeypatch.setattr(pick, "_night_state", lambda: state)
    state.write_text(json.dumps({"on": False, "at": at(20).isoformat()}))  # off for a film
    assert not pick.night_on(at(23), conf)
    assert not pick.night_on(at(3, day=9), conf)
    assert not pick.night_on(at(12, day=9), conf)  # the morning switch agrees
    assert pick.night_on(at(16, day=9), conf)  # and the evening brings it back


def test_light_line_is_a_moon_at_night(monkeypatch):
    monkeypatch.setattr(pick, "_run", lambda *cmd: "40\n")
    monkeypatch.setattr(pick, "night_on", lambda: True)
    line = pick.light_line("umber")
    assert "\u263e" in line and line.endswith(" 40%")
    monkeypatch.setattr(pick, "night_on", lambda: False)
    assert "\u263c" in pick.light_line("umber")


def test_night_off_clears_the_filter_and_remembers(tmp_path, monkeypatch):
    import json

    calls = []
    monkeypatch.setattr(pick, "_run", lambda *cmd: calls.append(cmd) or "")
    monkeypatch.setattr(pick, "_night_state", lambda: tmp_path / "night.json")
    pick.set_night(False)
    assert calls == [
        ("hyprctl", "hyprsunset", "temperature", "6000"),
        ("hyprctl", "hyprsunset", "identity"),
    ]
    assert json.loads((tmp_path / "night.json").read_text())["on"] is False
