"""Small menus for the status line's controls, drawn by fuzzel.

Bluetooth: turn the radio on or off, connect or disconnect a paired device.
Sound: a mixer for the outputs, the inputs and each app's stream.
Brightness: the night light and a level. Where Omarchy has a command for the
job it is used, so its OSD and memory of settings stay in step.
"""

import html
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from . import palette
from .paths import current_dir, state_dir, write_atomic


def _menu(prompt: str, rows: list[str]) -> str | None:
    if not rows or not shutil.which("fuzzel"):
        return None
    done = subprocess.run(
        [
            "fuzzel",
            "--dmenu",
            "--config",
            str(current_dir() / "fuzzel/fuzzel.ini"),
            "--prompt",
            f"{prompt} ",
            "--lines",
            str(min(len(rows), 12)),
            "--index",
        ],
        input="\n".join(rows),
        capture_output=True,
        text=True,
    )
    if done.returncode != 0 or not done.stdout.strip().isdigit():
        return None
    return rows[int(done.stdout.strip())]


def _run(*cmd: str) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def _devices(kind: str) -> dict[str, str]:
    found = {}
    for line in _run("bluetoothctl", "devices", kind).splitlines():
        m = re.match(r"Device (\S+) (.+)", line.strip())
        if m:
            found[m.group(1)] = m.group(2)
    return found


def bluetooth() -> None:
    powered = subprocess.run(["omarchy", "bluetooth", "power", "is-on"]).returncode == 0
    if not powered:
        if _menu("Bluetooth is off:", ["Turn Bluetooth on"]):
            _run("omarchy", "bluetooth", "power", "on")
        return
    connected = _devices("Connected")
    paired = _devices("Paired")
    rows, actions = [], []
    for addr, name in sorted(paired.items(), key=lambda kv: (kv[0] not in connected, kv[1])):
        if addr in connected:
            rows.append(f"✓ {name}  (disconnect)")
            actions.append(("disconnect", addr))
        else:
            rows.append(f"  {name}  (connect)")
            actions.append(("connect", addr))
    rows.append("Turn Bluetooth off")
    actions.append(("off", ""))
    choice = _menu("Bluetooth:", rows)
    if choice is None:
        return
    verb, addr = actions[rows.index(choice)]
    if verb == "off":
        _run("omarchy", "bluetooth", "power", "off")
    else:
        _run("omarchy", "bluetooth", "device", verb, addr)


def _sinks() -> list[tuple[int, str, str]]:
    try:
        nodes = json.loads(_run("pw-dump") or "[]")
    except json.JSONDecodeError:
        return []
    sinks = []
    for node in nodes:
        props = (node.get("info") or {}).get("props") or {}
        if (
            node.get("type") == "PipeWire:Interface:Node"
            and props.get("media.class") == "Audio/Sink"
        ):
            sinks.append(
                (
                    node["id"],
                    props.get("node.name", ""),
                    props.get("node.description") or props.get("node.nick") or "",
                )
            )
    return sinks


def _node_ids(media_class: str) -> dict[str, int]:
    """PipeWire node ids by node name, which Omarchy's set-default wants."""
    try:
        nodes = json.loads(_run("pw-dump") or "[]")
    except json.JSONDecodeError:
        return {}
    ids = {}
    for node in nodes:
        props = (node.get("info") or {}).get("props") or {}
        if (
            node.get("type") == "PipeWire:Interface:Node"
            and props.get("media.class") == media_class
        ):
            ids[props.get("node.name", "")] = node["id"]
    return ids


def _pactl(kind: str) -> list[dict]:
    try:
        data = json.loads(_run("pactl", "-f", "json", "list", kind) or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _volume(entry: dict) -> int:
    channels = list((entry.get("volume") or {}).values())
    if not channels:
        return 0
    return int(str(channels[0].get("value_percent", "0")).rstrip("%") or 0)


def _short(description: str) -> str:
    """A device's name without the controller's: "[Odyssey G95NC]" over the HDMI chip."""
    m = re.search(r"\[([^\]]+)\]\s*$", description)
    return m.group(1) if m else description


def _level(entry: dict) -> str:
    return "mute" if entry.get("mute") else f"{_volume(entry)}%"


@dataclass(frozen=True)
class Mixer:
    outputs: list[dict]
    inputs: list[dict]
    streams: list[dict]
    default_out: str
    default_in: str


def mixer() -> Mixer:
    inputs = [s for s in _pactl("sources") if not str(s.get("name", "")).endswith(".monitor")]
    return Mixer(
        _pactl("sinks"),
        inputs,
        _pactl("sink-inputs"),
        _run("pactl", "get-default-sink").strip(),
        _run("pactl", "get-default-source").strip(),
    )


def _app(stream: dict) -> str:
    props = stream.get("properties") or {}
    return str(props.get("application.name") or props.get("media.name") or "?")


def mixer_rows(m: Mixer) -> tuple[list[str], list[tuple[str, dict]]]:
    """The mixer's first page: outputs, inputs, then each app and where it plays."""
    rows, picks = [], []
    names = {s["index"]: _short(s.get("description", "")) for s in m.outputs}
    for sink in m.outputs:
        mark = "\u2713" if sink.get("name") == m.default_out else " "
        rows.append(f"Out  {mark} {_short(sink.get('description', ''))}  {_level(sink)}")
        picks.append(("out", sink))
    for source in m.inputs:
        mark = "\u2713" if source.get("name") == m.default_in else " "
        rows.append(f"In   {mark} {_short(source.get('description', ''))}  {_level(source)}")
        picks.append(("in", source))
    for stream in m.streams:
        where = names.get(stream.get("sink"), "?")
        rows.append(f"App    {_app(stream)} \u2192 {where}  {_level(stream)}")
        picks.append(("app", stream))
    return rows, picks


LEVELS = (100, 90, 75, 60, 50, 40, 25, 10)


def _levels(entry: dict) -> list[str]:
    return ["Unmute" if entry.get("mute") else "Mute"] + [f"{v}%" for v in LEVELS]


def sound() -> None:
    m = mixer()
    rows, picks = mixer_rows(m)
    choice = _menu("Sound:", rows)
    if choice is None:
        return
    kind, entry = picks[rows.index(choice)]
    index, name = str(entry.get("index")), str(entry.get("name", ""))
    if kind == "app":
        others = [s for s in m.outputs if s.get("index") != entry.get("sink")]
        options = _levels(entry) + [f"Play on {_short(s.get('description', ''))}" for s in others]
        pick = _menu(f"{_app(entry)}:", options)
        if pick is None:
            return
        if pick.startswith("Play on "):
            sink = others[options.index(pick) - len(_levels(entry))]
            _run("pactl", "move-sink-input", index, str(sink.get("index")))
        elif pick.endswith("%"):
            _run("pactl", "set-sink-input-volume", index, pick)
        else:
            _run("pactl", "set-sink-input-mute", index, "toggle")
        return
    noun, default = ("sink", m.default_out) if kind == "out" else ("source", m.default_in)
    options = _levels(entry)
    if name != default:
        options.insert(0, "Make this the default")
    pick = _menu(f"{_short(entry.get('description', ''))}:", options)
    if pick is None:
        return
    if pick == "Make this the default":
        media = "Audio/Sink" if kind == "out" else "Audio/Source"
        node = _node_ids(media).get(name)
        way = "output" if kind == "out" else "input"
        if node is not None:
            _run("omarchy", "audio", way, "set", "default", str(node), name)
        else:
            _run("pactl", f"set-default-{noun}", name)
    elif pick.endswith("%"):
        _run("pactl", f"set-{noun}-volume", name, pick)
    else:
        _run("pactl", f"set-{noun}-mute", name, "toggle")


# The night light is hyprsunset's. Its schedule switches at the times in
# hyprsunset.conf; a change made here holds until the next switch, so night
# mode turned off for a film comes back on its own the next evening.
#
# hyprsunset can't be asked whether its filter is on: after `identity` (from
# the schedule or from here) it still reports the last warm temperature. So
# the state is worked out instead: the schedule's latest switch, unless a
# change was made here since.
SUNSET_CONF = Path.home() / ".config/hypr/hyprsunset.conf"
IDENTITY = 6000  # hyprsunset's neutral temperature (Omarchy reads it the same way)


def _night_state() -> Path:
    return state_dir() / "night.json"


def profiles(conf: Path = SUNSET_CONF) -> list[tuple[time, int | None]]:
    """The schedule as (switch time, temperature), None for no filter, in time order."""
    try:
        text = conf.read_text()
    except OSError:
        return []
    found = []
    for body in re.findall(r"profile\s*\{([^}]*)\}", text):
        when = re.search(r"time\s*=\s*(\d{1,2}):(\d{2})", body)
        if not when:
            continue
        temp = re.search(r"temperature\s*=\s*(\d+)", body)
        identity = re.search(r"identity\s*=\s*true", body)
        kelvin = None if identity or not temp else int(temp.group(1))
        found.append((time(int(when.group(1)), int(when.group(2))), kelvin))
    return sorted(found)


def night_temperature(conf: Path = SUNSET_CONF) -> int:
    """The warmest temperature the schedule uses, or Omarchy's 4000."""
    temps = [k for _, k in profiles(conf) if k is not None]
    return min(temps, default=4000)


def last_switch(now: datetime, conf: Path = SUNSET_CONF) -> tuple[datetime, bool] | None:
    """When the schedule last switched, and whether that switch turned the filter on."""
    sched = profiles(conf)
    if not sched:
        return None
    today = [(datetime.combine(now.date(), t, now.tzinfo), k) for t, k in sched]
    past = [(at, k) for at, k in today if at <= now]
    if past:
        at, kelvin = past[-1]
    else:  # before today's first switch: yesterday's last one still holds
        at, kelvin = today[-1]
        at -= timedelta(days=1)
    return at, kelvin is not None and kelvin < IDENTITY


def temperature() -> int | None:
    m = re.search(r"\d+", _run("hyprctl", "hyprsunset", "temperature"))
    return int(m.group()) if m else None


def night_on(now: datetime | None = None, conf: Path = SUNSET_CONF) -> bool:
    now = now or datetime.now().astimezone()
    switch = last_switch(now, conf)
    try:
        chosen = json.loads(_night_state().read_text())
        since = datetime.fromisoformat(chosen["at"])
    except (OSError, ValueError, KeyError, TypeError):
        chosen, since = None, None
    if chosen is not None and (switch is None or since > switch[0]):
        return bool(chosen.get("on"))
    if switch is not None:
        return switch[1]
    temp = temperature()  # no schedule to go by
    return temp is not None and temp < IDENTITY


def set_night(on: bool) -> None:
    if on:
        _run("hyprctl", "hyprsunset", "temperature", str(night_temperature()))
    else:
        # Report the neutral temperature too, for anything else that asks
        # hyprsunset (Omarchy's toggle does), then drop the filter entirely.
        _run("hyprctl", "hyprsunset", "temperature", str(IDENTITY))
        _run("hyprctl", "hyprsunset", "identity")
    now = datetime.now().astimezone().isoformat()
    write_atomic(_night_state(), json.dumps({"on": on, "at": now}))


def toggle_night() -> None:
    set_night(not night_on())


def brightness() -> None:
    night = night_on()
    rows = ["\u263c Night light off" if night else "\u263e Night light on"]
    rows += [f"{level}%" for level in LEVELS]
    choice = _menu("Brightness:", rows)
    if choice is None:
        return
    if choice == rows[0]:
        set_night(not night)
    else:
        _run("omarchy", "brightness", "display", choice)


SIGN = "font_desc='Athanor 32px' fallback='false'"


def light_line(scheme_name: str) -> str:
    """The bar's brightness: a sun by day, a moon while the night light is on."""
    hues = palette.bar_hues(palette.load(scheme_name))
    level = _run("omarchy", "brightness", "display", "--no-osd").strip() or "?"
    if night_on():
        glyph, color = "\u263e", hues["bar_silver"]
    else:
        glyph, color = "\u263c", hues["bar_gold"]
    return f"<span {SIGN} foreground='{color}'>{glyph}</span> {html.escape(level)}%"
