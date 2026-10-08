import dataclasses
import html
import json
import os
import select
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import hypr, palette


@dataclass(frozen=True)
class Reading:
    workspace: int | None
    disk_free: int
    cpu: int | None
    mem_free: int
    mem_total: int
    minutes: int


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


class Cpu:
    def __init__(self, stat: Path = Path("/proc/stat")):
        self.stat = stat
        self.prev: tuple[int, int] | None = None

    def _sample(self) -> tuple[int, int] | None:
        line = _read(self.stat)
        if not line:
            return None
        fields = [int(v) for v in line.splitlines()[0].split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        return idle, sum(fields)

    def percent(self) -> int | None:
        now = self._sample()
        prev, self.prev = self.prev, now
        if now is None or prev is None or now[1] == prev[1]:
            return None
        busy = 1 - (now[0] - prev[0]) / (now[1] - prev[1])
        return max(0, min(100, round(busy * 100)))


def memory(meminfo: Path = Path("/proc/meminfo")) -> tuple[int, int]:
    """Memory still free for the taking (MemAvailable) and the total, in bytes."""
    values = {}
    for line in (_read(meminfo) or "").splitlines():
        key, _, rest = line.partition(":")
        values[key] = int(rest.split()[0]) * 1024
    return values.get("MemAvailable", 0), values.get("MemTotal", 0)


def uptime_minutes(uptime: Path = Path("/proc/uptime")) -> int:
    text = _read(uptime)
    return int(float(text.split()[0]) // 60) if text else 0


def disk_free(path: str = "/") -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def size(n: int, decimals: int = 0) -> str:
    gib = n / 2**30
    if gib >= 1000:
        return f"{gib / 1024:.1f}T"
    return f"{gib:.{decimals}f}G"


def read(cpu: Cpu) -> Reading:
    free, total = memory()
    return Reading(
        workspace=hypr.active_workspace(),
        disk_free=disk_free(),
        cpu=cpu.percent(),
        mem_free=free,
        mem_total=total,
        minutes=uptime_minutes(),
    )


def hp(free: int, total: int) -> str:
    """Hit points are free memory in GiB; the max is all of it."""
    return f"Hp:{free // 2**30}({-(-total // 2**30)})"


def health(r: Reading) -> float:
    return r.mem_free / r.mem_total if r.mem_total else 1.0


def line(r: Reading) -> str:
    return "  ".join(
        (
            f"Dlvl:{r.workspace if r.workspace is not None else '?'}",
            f"$:{size(r.disk_free)}",
            hp(r.mem_free, r.mem_total),
            f"Str:{r.cpu if r.cpu is not None else '--'}%",
            f"T:{r.minutes}",
        )
    )


def markup(r: Reading, roles: dict[str, str], hues: dict[str, str]) -> str:
    """The status line with NetHack's status highlights: labels dim, gold in
    gold, Hp green until memory runs low, Str hot under load."""
    dim, low, hurt = roles["dim"], roles["active"], roles["bar_warn"]

    def field(label: str, value: str, color: str | None = None) -> str:
        value = html.escape(value)
        if color:
            value = f'<span foreground="{color}">{value}</span>'
        return f'<span foreground="{dim}">{label}:</span>{value}'

    left = health(r)
    hp_color = hues["bar_green"] if left > 0.5 else low if left > 0.2 else hurt
    hp_text = hp(r.mem_free, r.mem_total).removeprefix("Hp:")
    cpu = r.cpu
    str_color = None if cpu is None or cpu < 50 else low if cpu < 85 else hurt
    return "  ".join(
        (
            field("Dlvl", str(r.workspace) if r.workspace is not None else "?"),
            field("$", size(r.disk_free), hues["bar_gold"]),
            field("Hp", hp_text, hp_color),
            field("Str", f"{cpu if cpu is not None else '--'}%", str_color),
            field("T", str(r.minutes)),
        )
    )


def short(r: Reading) -> str:
    return f"{hp(r.mem_free, r.mem_total)}  T:{r.minutes}"


def classes(r: Reading) -> list[str]:
    left = health(r)
    if left <= 0.1:
        return ["hurt", "dying"]
    if left <= 0.2:
        return ["hurt"]
    return []


TOOLTIP = (
    "Dlvl workspace. $ disk. Hp free memory. Str CPU. T minutes awake. "
    "The rest is in `athanor guide`."
)


PROMPT_EVENTS = (b"workspace>>", b"workspacev2>>", b"focusedmon>>", b"focusedmonv2>>")


def wants_redraw(chunk: bytes) -> bool:
    return any(line.startswith(PROMPT_EVENTS) for line in chunk.splitlines())


def waybar(interval: float = 2.0) -> None:
    from . import transmute

    cpu = Cpu()
    cpu.percent()
    sock = hypr.events()
    last = None

    def emit(r: Reading) -> None:
        scheme = palette.load(transmute.saved_scheme())
        text = markup(r, scheme.roles, palette.bar_hues(scheme))
        out = {"text": text, "class": classes(r), "tooltip": TOOLTIP}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()

    deadline = time.monotonic() + interval
    while True:
        wait = max(0.0, deadline - time.monotonic())
        ready = select.select([sock], [], [], wait)[0] if sock else time.sleep(wait) or []
        if ready:
            chunk = sock.recv(65536)
            if not chunk:
                sock.close()
                sock = None
            elif wants_redraw(chunk) and last is not None:
                last = dataclasses.replace(last, workspace=hypr.active_workspace())
                emit(last)
            continue
        last = read(cpu)
        emit(last)
        deadline = time.monotonic() + interval


def plain(brief: bool = False) -> str:
    cpu = Cpu()
    cpu.percent()
    time.sleep(0.25)
    r = read(cpu)
    return short(r) if brief else line(r)
