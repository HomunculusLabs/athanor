"""Small menus for the status line's controls, drawn by fuzzel.

Bluetooth: turn the radio on or off, connect or disconnect a paired device.
Sound: choose the output. Brightness: jump to a level. Each acts through
Omarchy's own commands, so its OSD and memory of settings stay in step.
"""

import json
import re
import shutil
import subprocess

from .paths import current_dir


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


def sound() -> None:
    sinks = _sinks()
    default = ""
    for line in _run("wpctl", "inspect", "@DEFAULT_AUDIO_SINK@").splitlines():
        if "node.name" in line:
            default = line.split("=", 1)[1].strip().strip('"')
            break
    rows = [f"{'✓' if name == default else ' '} {desc}" for _, name, desc in sinks]
    choice = _menu("Sound out:", rows)
    if choice is None:
        return
    node_id, name, _ = sinks[rows.index(choice)]
    _run("omarchy", "audio", "output", "set", "default", str(node_id), name)


LEVELS = (100, 90, 75, 60, 50, 40, 25, 10)


def brightness() -> None:
    rows = [f"{level}%" for level in LEVELS]
    choice = _menu("Brightness:", rows)
    if choice:
        _run("omarchy", "brightness", "display", choice)
