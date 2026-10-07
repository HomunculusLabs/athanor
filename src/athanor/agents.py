"""Subscription usage for the status line.

Reads the records Omarchy's `omarchy-agent-usage-update` writes (one JSON file
per agent in ~/.local/state/omarchy/agents/usage) and shows how much of each
plan's allowance is spent. When the records go stale it asks the updater to
refresh the limits, so the bar keeps working without Omarchy's own panel.
"""

import contextlib
import fcntl
import html
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import palette
from .paths import state_dir, write_atomic

# Which records to show, in order, and the name each gets on the bar.
AGENTS = (("claude", "Claude"), ("codex", "ChatGPT"))
STALE = 300  # seconds before the limits are refreshed
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
    hot = [lim for lim in plan.limits if lim not in main and lim.percent >= WARN]
    return tuple(main + hot) or plan.limits[:1]


# Each subscription is a well of its own kind of energy: the bar shows what is
# left, full when the window resets and draining as it is spent. Claude runs on
# quicksilver under Mercury's sign, ChatGPT on green vitriol. Sigils are drawn
# in Athanor.
@dataclass(frozen=True)
class Energy:
    name: str
    sigil: str
    hues: tuple[int, ...]  # ANSI slots to try, in order, for the energy's colour


ENERGIES = {
    "claude": Energy("Quicksilver", "\u263f", (12, 4)),  # Mercury, silver-blue
    "codex": Energy("Vitriol", "\U0001f716", (10, 2, 14, 6)),  # green vitriol
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
    """The first of the scheme's slots that reads on its bar, or the first lifted until it does."""
    bar = scheme.roles["bar"]
    for index in slots:
        if palette.contrast(scheme.ansi[index], bar) >= 4.5:
            return scheme.ansi[index]
    # Lift toward white on a dark bar, sink toward black on a light one, so it keeps its hue.
    light_bar = palette.luminance(bar) > 0.5
    base, toward = palette.rgb(scheme.ansi[slots[0]]), (0, 0, 0) if light_bar else (255, 255, 255)
    for step in range(1, 11):
        t = step / 10
        mixed = "#" + "".join(
            f"{round(a + (b - a) * t):02x}" for a, b in zip(base, toward, strict=True)
        )
        if palette.contrast(mixed, bar) >= 4.5:
            return mixed
    return scheme.roles["barfg"]


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

    # The bar keeps one shape, sigil, pool, meter, number, so it never changes
    # width. The sigil carries the lowest of all the pools, so a pool out of
    # sight that runs low still shows; the refill times live in the tooltip.
    lowest = min((1 - lim.percent for lim in pools(plan)), default=1.0)
    bits = [_sigil(energy(plan.id).sigil, tint(lowest))]
    lim = chosen(plan, choice)
    if lim is None:
        bits.append(_paint("unread", dim))
    else:
        left = max(0.0, 1 - lim.percent)
        full, spent = meter(left)
        bits.append(
            _paint(f"{lim.short[:2]} ", dim)
            + _paint(full, tint(left))
            + _paint(spent, dim)
            + _paint(f" {round(left * 100)}", tint(left) if left < LOW else None)
        )
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


def tooltip(plans: list[Plan], now: datetime) -> str:
    lines = []
    for plan in plans:
        kind = energy(plan.id)
        head = f"{kind.name}: {plan.name} {plan.tier}".strip()
        if plan.problem:
            head += f"  ({plan.problem})"
        lines.append(head)
        for lim in plan.limits:
            reset = until(lim.resets, now)
            left = max(0, round((1 - lim.percent) * 100))
            lines.append(
                f"  {lim.label:<18} {left:>3}% left" + (f", full again in {reset}" if reset else "")
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


def refresh(root: Path, force: bool = False) -> None:
    """Ask Omarchy's collectors for fresh limits, at most one run at a time."""
    updater = shutil.which("omarchy-agent-usage-update")
    if not updater:
        return
    if not force:
        ages = []
        for agent, _ in AGENTS:
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
        subprocess.Popen(
            [updater, "--limits-only", *(agent for agent, _ in AGENTS)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            pass_fds=(lock.fileno(),),
            start_new_session=True,
        )


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
            out = {"text": text, "class": classes, "tooltip": tooltip(plans, now)}
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()
        # A click writes the pick file; looking for it twice a second costs nothing.
        time.sleep(0.5)


def plain() -> str:
    now = datetime.now(UTC)
    return tooltip(load(), now)
