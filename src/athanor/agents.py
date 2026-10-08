"""Subscription usage for the status line.

Reads the records Omarchy's `omarchy-agent-usage-update` writes (one JSON file
per agent in ~/.local/state/omarchy/agents/usage) and shows how much of each
plan's allowance is spent. When the records go stale it asks the updater to
refresh the limits, so the bar keeps working without Omarchy's own panel.
Omarchy has no collector for the z.ai Coding Plan, so that record is written
here, in the same shape, from z.ai's quota endpoint.
"""

import contextlib
import fcntl
import html
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import palette
from .paths import state_dir, write_atomic

# Which records to show, in order, and the name each gets on the bar.
AGENTS = (("claude", "Claude"), ("codex", "ChatGPT"), ("zai", "Z.ai"))
OMARCHY = ("claude", "codex")  # the ones Omarchy's updater collects
# Wells meant to be spent: the z.ai plan has only a 5-hour window and the aim
# is to use all of it, so its bar fills as it burns instead of draining.
BURN = frozenset({"zai"})
STALE = 300  # seconds before the limits are refreshed
ZAI_STALE = 60  # one cheap request, so the burn can be watched more closely
ZAI_QUOTA = "https://api.z.ai/api/monitor/usage/quota/limit"
WARN = 0.5  # spent before a model's own weekly limit joins the bar


def usage_dir() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(state) / "omarchy/agents/usage"


@dataclass(frozen=True)
class Limit:
    label: str
    percent: float
    resets: datetime | None

    @property
    def short(self) -> str:
        text = self.label.lower()
        if "5-hour" in text or "session" in text:
            return "5h"
        if "weekly" in text or "7-day" in text:
            words = self.label.split()
            # "Fable Weekly" keeps its model name; plain "Weekly (7-day)" is wk.
            return "wk" if words[0].lower() == "weekly" else words[0].lower()
        return self.label.split()[0].lower()


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    tier: str
    limits: tuple[Limit, ...]
    problem: str
    updated: datetime | None


def _when(text) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def _tier(label) -> str:
    label = str(label or "")
    return label[:1].upper() + label[1:]


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load(root: Path | None = None) -> list[Plan]:
    root = root or usage_dir()
    plans = []
    for agent, name in AGENTS:
        record = _read(root / f"{agent}.json")
        if record is None:
            continue
        # The collectors sometimes come back empty-handed (Codex's app-server
        # doesn't always answer). Hold on to the last reading that had limits
        # rather than blanking the bar until the next refresh.
        last = root / f".athanor-{agent}-last.json"
        if record.get("limits"):
            if _read(last) != record:
                with contextlib.suppress(OSError):
                    last.write_text(json.dumps(record))
        else:
            record = _read(last) or record
        limits = tuple(
            Limit(
                str(entry.get("label", "")), float(entry["percent"]), _when(entry.get("resetsAt"))
            )
            for entry in record.get("limits") or ()
            if isinstance(entry.get("percent"), (int, float)) and entry["percent"] >= 0
        )
        problem = ""
        if not record.get("ready"):
            problem = str(record.get("usageStatusText") or "signed out")
        elif not limits:
            problem = str(record.get("usageStatusText") or "no limits")
        plans.append(
            Plan(
                agent,
                name,
                _tier(record.get("tierLabel")),
                limits,
                problem,
                _when(record.get("updatedAt")),
            )
        )
    return plans


def until(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return ""
    minutes = max(0, int((moment - now).total_seconds() // 60))
    days, hours, mins = minutes // 1440, minutes // 60 % 24, minutes % 60
    if days:
        return f"{days}d{hours:02d}h"
    return f"{hours}h{mins:02d}"


def shown(plan: Plan) -> tuple[Limit, ...]:
    # The bar carries the session and the main weekly window; the rest
    # (model-specific weeklies) wait in the tooltip unless they run hot.
    main = [lim for lim in plan.limits if lim.short in ("5h", "wk")]
    if plan.id in BURN:
        return tuple(main) or plan.limits[:1]
    hot = [lim for lim in plan.limits if lim not in main and lim.percent >= WARN]
    return tuple(main + hot) or plan.limits[:1]


# Each subscription is a well of its own kind of energy: the bar shows what is
# left, full when the window resets and draining as it is spent. The three are
# the tria prima: Claude is Mercury, ChatGPT Sulphur, z.ai Salt, which burns
# rather than drains. Sigils are drawn in Athanor.
@dataclass(frozen=True)
class Energy:
    name: str
    sigil: str
    hues: tuple[int, ...]  # ANSI slots to try, in order, for the energy's colour


ENERGIES = {
    "claude": Energy("Mercury", "\u263f", (1, 9)),  # red
    "codex": Energy("Sulphur", "\U0001f70d", (4, 12)),  # blue
    "zai": Energy("Salt", "\U0001f714", (2, 10)),  # green
}
OTHER = Energy("Aether", "\u2609", (15, 7))
METER = 10
LOW, DRAINED = 0.5, 0.2  # energy left before the bar turns amber, then red
SIGN_FONT = "Athanor 32px"


def energy(agent: str) -> Energy:
    return ENERGIES.get(agent, OTHER)


def meter(left: float) -> tuple[str, str]:
    """Full and spent cells (Vellum's slanted segments nest).

    A well with anything left keeps one cell lit, and one that has been
    touched at all loses its last cell, so the bar never claims more or less
    than is true.
    """
    full = round(left * METER)
    if 0 < left < 1:
        full = min(METER - 1, max(1, full))
    return "\u25b0" * full, "\u25b1" * (METER - full)


def hue(scheme, slots: tuple[int, ...]) -> str:
    return palette.readable(scheme, slots)


def colors(scheme) -> dict[str, str]:
    out = {**scheme.roles}
    for agent, kind in ENERGIES.items():
        out[f"energy.{agent}"] = hue(scheme, kind.hues)
    out["energy"] = hue(scheme, OTHER.hues)
    return out


def _paint(text: str, color: str | None) -> str:
    text = html.escape(text)
    return f'<span foreground="{color}">{text}</span>' if color else text


def _sigil(text: str, color: str) -> str:
    # No fallback: alchemical signs otherwise wander off to an emoji font.
    return f'<span font_desc="{SIGN_FONT}" fallback="false" foreground="{color}">{text}</span>'


def pools(plan: Plan) -> tuple[Limit, ...]:
    return shown(plan)


def chosen(plan: Plan, choice: str | None) -> Limit | None:
    """The pool on show: the one picked by clicking, else the first (the session)."""
    options = pools(plan)
    for lim in options:
        if lim.short == choice:
            return lim
    return options[0] if options else None


def markup_one(
    plan: Plan, choice: str | None, colors: dict[str, str], now: datetime
) -> tuple[str, list[str]]:
    dim, low, drained = colors["dim"], colors["active"], colors["bar_warn"]
    own = colors.get(f"energy.{plan.id}", colors.get("energy", colors["fg"]))

    def tint(left: float) -> str:
        return drained if left < DRAINED else low if left < LOW else own

    # The bar keeps one shape, sigil and meter, so it never changes width.
    # Which pool is on show, the numbers and the refill times live in the
    # tooltip. The sigil carries the lowest of all the pools, so a pool out of
    # sight that runs low still shows.
    lowest = min((1 - lim.percent for lim in pools(plan)), default=1.0)
    lim = chosen(plan, choice)

    if plan.id in BURN:
        # Spending is the point here, so nothing warns: the meter fills with
        # what has been burnt.
        bits = [_sigil(energy(plan.id).sigil, own)]
        if lim is None:
            bits.append(_paint("unread", dim))
        else:
            burnt = min(1.0, max(0.0, lim.percent))
            full, empty = meter(burnt)
            bits.append(_paint(full, own) + _paint(empty, dim))
        return "  ".join(bits), []
    bits = [_sigil(energy(plan.id).sigil, tint(lowest))]
    if lim is None:
        bits.append(_paint("unread", dim))
    else:
        left = max(0.0, 1 - lim.percent)
        full, spent = meter(left)
        bits.append(_paint(full, tint(left)) + _paint(spent, dim))
    classes = ["hurt"] if lowest < DRAINED else ["warn"] if lowest < LOW else []
    return "  ".join(bits), classes


def markup(plans: list[Plan], colors: dict[str, str], now: datetime) -> tuple[str, list[str]]:
    """Every source on one line, each showing its first pool."""
    parts, classes = [], set()
    for plan in plans:
        text, cls = markup_one(plan, None, colors, now)
        parts.append(text)
        classes.update(cls)
    order = ["hurt"] if "hurt" in classes else ["warn"] if "warn" in classes else []
    return "   ".join(parts), order


def tooltip(plans: list[Plan], now: datetime, picks: dict[str, str] | None = None) -> str:
    """Every pool with its numbers; ▸ marks the one on the bar where there is a choice."""
    lines = []
    for plan in plans:
        on_show = chosen(plan, (picks or {}).get(plan.id)) if len(pools(plan)) > 1 else None
        kind = energy(plan.id)
        head = f"{kind.name}: {plan.name} {plan.tier}".strip()
        if plan.problem:
            head += f"  ({plan.problem})"
        lines.append(head)
        for lim in plan.limits:
            reset = until(lim.resets, now)
            mark = "\u25b8 " if lim == on_show else "  "
            if plan.id in BURN:
                burnt = max(0, round(lim.percent * 100))
                lines.append(
                    f"{mark}{lim.label:<18} {burnt:>3}% burnt"
                    + (f", new window in {reset}" if reset else "")
                )
                continue
            left = max(0, round((1 - lim.percent) * 100))
            lines.append(
                f"{mark}{lim.label:<18} {left:>3}% left"
                + (f", full again in {reset}" if reset else "")
            )
        if plan.updated:
            age = int((now - plan.updated).total_seconds() // 60)
            lines.append(f"  read {age} min ago")
    if len(plans) == 1 and len(pools(plans[0])) > 1:
        lines.append("Click to switch pools, right-click to read them again.")
    return "\n".join(lines) or "No usage records yet."


def _choices_path() -> Path:
    return state_dir() / "pools.json"


def choices(path: Path | None = None) -> dict[str, str]:
    data = _read(path or _choices_path())
    return {str(k): str(v) for k, v in (data or {}).items()}


def toggle(agent: str, root: Path | None = None, path: Path | None = None) -> str | None:
    """Show the next of an agent's pools; returns the pool now on show."""
    path = path or _choices_path()
    plan = next((p for p in load(root) if p.id == agent), None)
    if plan is None or not pools(plan):
        return None
    options = [lim.short for lim in pools(plan)]
    current = chosen(plan, choices(path).get(agent))
    nxt = options[(options.index(current.short) + 1) % len(options)]
    write_atomic(path, json.dumps({**choices(path), agent: nxt}))
    return nxt


def zai_key() -> str:
    """The z.ai key: $ZAI_API_KEY, else the one opencode's z.ai provider uses."""
    key = os.environ.get("ZAI_API_KEY", "")
    if key:
        return key
    config = _read(Path.home() / ".config/opencode/opencode.json") or {}
    provider = (config.get("provider") or {}).get("zai-coding-plan") or {}
    return str((provider.get("options") or {}).get("apiKey") or "")


def _zai_ms(value) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, UTC).isoformat()


def zai_record(data: dict, now: datetime) -> dict:
    """An Omarchy-shaped usage record from z.ai's quota/limit answer."""
    limits = []
    for entry in data.get("limits") or ():
        kind = entry.get("type")
        if kind == "TOKENS_LIMIT":
            label = "Session (5-hour)"
        elif kind == "TIME_LIMIT":
            label = "MCP calls (month)"
        else:
            continue
        if not isinstance(entry.get("percentage"), (int, float)):
            continue
        limits.append(
            {
                "label": label,
                "percent": entry["percentage"] / 100,
                "resetsAt": _zai_ms(entry.get("nextResetTime")),
            }
        )
    limits.sort(key=lambda lim: lim["label"] != "Session (5-hour)")
    return {
        "schemaVersion": 1,
        "id": "zai",
        "name": "Z.ai",
        "updatedAt": now.isoformat(),
        "ready": True,
        "tierLabel": str(data.get("level") or ""),
        "usageStatusText": "" if limits else "z.ai limits unavailable",
        "limits": limits,
    }


def collect_zai(root: Path) -> None:
    """Read the z.ai Coding Plan quota and write it as zai.json."""
    key = zai_key()
    now = datetime.now(UTC)
    if not key:
        record = {**zai_record({}, now), "ready": False, "usageStatusText": "no z.ai key"}
        write_atomic(root / "zai.json", json.dumps(record))
        return
    request = urllib.request.Request(
        ZAI_QUOTA, headers={"Authorization": key, "Accept-Language": "en-US,en"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as answer:
            body = json.loads(answer.read())
    except (OSError, ValueError):
        return  # keep the last record; the next round tries again
    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        return
    write_atomic(root / "zai.json", json.dumps(zai_record(body["data"], now)))


def refresh_zai(root: Path, force: bool = False) -> None:
    """Fetch the z.ai quota in the background, at most one fetch at a time."""
    if not force:
        try:
            if time.time() - (root / "zai.json").stat().st_mtime < ZAI_STALE:
                return
        except OSError:
            pass
    root.mkdir(parents=True, exist_ok=True)
    lock = open(root / ".athanor-zai.lock", "w")  # noqa: SIM115 - the thread closes it
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return

    def run() -> None:
        with lock:
            collect_zai(root)

    # Not a daemon: a one-shot `agents --refresh` waits for the fetch to land.
    threading.Thread(target=run, name="zai-quota").start()


_running: list[subprocess.Popen] = []


def refresh(root: Path, force: bool = False) -> None:
    """Ask the collectors for fresh limits, at most one run of each at a time."""
    refresh_zai(root, force)
    # Reap finished runs so they don't linger as zombies under the bar.
    _running[:] = [p for p in _running if p.poll() is None]
    updater = shutil.which("omarchy-agent-usage-update")
    if not updater:
        return
    if not force:
        ages = []
        for agent in OMARCHY:
            try:
                ages.append(time.time() - (root / f"{agent}.json").stat().st_mtime)
            except OSError:
                ages.append(float("inf"))
        if min(ages) < STALE:
            return
    root.mkdir(parents=True, exist_ok=True)
    with open(root / ".athanor-refresh.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return
        # The child inherits the lock and holds it until it finishes.
        child = subprocess.Popen(
            [updater, "--limits-only", *OMARCHY],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            pass_fds=(lock.fileno(),),
            start_new_session=True,
        )
        _running.append(child)


def waybar(colors_for, only: str | None = None, interval: float = 30.0) -> None:
    """Print a Waybar line for one agent (or all), again on a click or every interval."""
    root = usage_dir()
    picks = _choices_path()
    last_pick = None
    due = 0.0
    while True:
        try:
            pick_stamp = picks.stat().st_mtime
        except OSError:
            pick_stamp = None
        if time.monotonic() >= due or pick_stamp != last_pick:
            last_pick = pick_stamp
            due = time.monotonic() + interval
            refresh(root)
            now = datetime.now(UTC)
            plans = [p for p in load(root) if only is None or p.id == only]
            if only is None:
                text, classes = markup(plans, colors_for(), now)
            else:
                text, classes = ("", [])
                if plans:
                    text, classes = markup_one(plans[0], choices().get(only), colors_for(), now)
            out = {"text": text, "class": classes, "tooltip": tooltip(plans, now, choices())}
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()
        # A click writes the pick file; looking for it twice a second costs nothing.
        time.sleep(0.5)


def plain() -> str:
    now = datetime.now(UTC)
    return tooltip(load(), now)
