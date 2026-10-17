import argparse
import contextlib
import getpass
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import (
    agents,
    almanac,
    ansi,
    config,
    guide,
    hypr,
    inventory,
    moon,
    palette,
    pick,
    sigil,
    sky,
    stages,
    status,
    tarot,
    tomb,
    transmute,
    wall,
)
from .paths import cache_dir, runtime_dir, state_dir, write_atomic


def _now() -> datetime:
    return datetime.now().astimezone()


def _size(text: str) -> tuple[int, int]:
    w, _, h = text.lower().partition("x")
    return int(w), int(h)


def _hour_lines(now: datetime, cfg) -> dict[str, str]:
    ph = sky.planetary_hour(now, cfg.place)
    trump = tarot.trump_for(ph.planet)
    approx = "~" if ph.approximate else ""
    day, hour = sky.with_article(ph.day_ruler), sky.with_article(ph.planet)
    seed, _ = sigil.host_digest()
    card = tarot.card_of_day(now.date(), seed)
    return {
        "date": f"{now:%A}, the {sky.ordinal(now.day)} of {now:%B}",
        "ruler": f"Day of {day}, hour of {hour}{approx}",
        "trump": f"The hour's trump: {trump.title}",
        "moon": f"Moon {sky.moon_phase(now)}, {sky.moon_age(now):.0f} days old",
        "card": f"Card of the day: {card.title}",
        "bar": f"{now:%a %-d %b  %H:%M}  Hour of {hour}{approx}  Moon: {sky.moon_trend(now)}",
        "sun": f"Sunrise {ph.sunrise.astimezone(now.tzinfo):%H:%M}, "
        f"sunset {ph.sunset.astimezone(now.tzinfo):%H:%M}"
        + ("  (no [place] set; using 6:00 and 18:00)" if ph.approximate else ""),
    }


# Athanor draws the classical planets and the moon's phases on
# the same pixel grid as the bar text.
PLANET_SIGNS = {
    "Saturn": "\u2644",
    "Jupiter": "\u2643",
    "Mars": "\u2642",
    "Sun": "\u2609",
    "Venus": "\u2640",
    "Mercury": "\u263f",
    "Moon": "\u263d",
}
# Each planet in its traditional colour (its metal, or its ray): Saturn lead,
# Jupiter blue, Mars red, the Sun gold, Venus green, Mercury orange, the Moon
# silver.
PLANET_HUES = {
    "Saturn": "bar_lead",
    "Jupiter": "bar_blue",
    "Mars": "bar_red",
    "Sun": "bar_gold",
    "Venus": "bar_green",
    "Mercury": "bar_ochre",
    "Moon": "bar_silver",
}
# The biodynamic day by its element: root earth, leaf water, flower air,
# fruit warmth. Red is kept for the unlucky hours.
ELEMENT_HUES = {"earth": "bar_ochre", "water": "bar_teal", "air": "bar_rose", "fire": "bar_gold"}
SIGN_FONT = "Athanor 32px"
# Signs and moon phases are also emoji. Without fallback Pango keeps them in
# Athanor's line art instead of reaching for a colour emoji font (and its
# taller line, which stretches the bar).


def _sign(text: str, color: str, underline: bool = False) -> str:
    under = ' underline="single"' if underline else ""
    return (
        f'<span font_desc="{SIGN_FONT}" fallback="false"{under} foreground="{color}">{text}</span>'
    )


def _moon_sign(now: datetime) -> str:
    index = int(sky.moon_age(now) / sky.SYNODIC_MONTH * 8 + 0.5) % 8
    return almanac.lit_sign(index)


def _bar_markup(now: datetime, cfg) -> str:
    ph = sky.planetary_hour(now, cfg.place)
    scheme = palette.load(transmute.saved_scheme())
    roles, hues = scheme.roles, palette.bar_hues(scheme)

    def planet(name: str) -> str:
        return _sign(PLANET_SIGNS[name], hues[PLANET_HUES[name]])

    def dim(text: str) -> str:
        return f'<span foreground="{roles["dim"]}">{html.escape(text)}</span>'

    approx = dim("~") if ph.approximate else ""
    hour = sky.with_article(ph.planet)
    # The date steps back so the time is what the eye lands on. The moon's
    # phase lives with the rest of the moon, in its own box.
    time_of_day = f'<span foreground="{hues["bar_silver"]}">{now:%H:%M}</span>'
    return "   ".join(
        (
            f"{dim(f'{now:%a %-d %b}')}  {time_of_day}",
            f"{planet(ph.day_ruler)}{planet(ph.planet)} Hour of {hour}{approx}",
        )
    )


def _moon_lines(now: datetime, brief: bool = False) -> tuple[str, str]:
    """The biodynamic reading: bar markup and a tooltip.

    Brief leaves out when the day next turns, for the bar where the moon
    rides beside the clock; the tooltip still says.
    """
    cfg = config.load()
    scheme = palette.load(transmute.saved_scheme())
    roles, hues = scheme.roles, palette.bar_hues(scheme)
    utc = now.astimezone(UTC)
    here = moon.constellation(utc)
    rising = moon.ascending(utc)
    change = moon.next_change(utc)
    node, perigee = moon.at_node(utc), moon.near_perigee(utc)
    week = almanac.days(now.date(), 7, now.tzinfo)

    def dim(text: str) -> str:
        return f'<span foreground="{roles["dim"]}">{html.escape(text)}</span>'

    # Only what matters at a glance: today's kind of day, whether the sap is
    # rising or sinking, a red sign when the hour is unlucky, and when the
    # day next turns. The constellation, the week and the reasons are in the
    # tooltip and the almanac.
    lucky = not (node or perigee)
    parts = [
        _sign(_moon_sign(now), hues["bar_silver"])
        + "  "
        + _sign(here.day_sign, hues[ELEMENT_HUES[here.element]] if lucky else roles["bar_warn"])
        + f" {here.day} "
        + ("\u2191" if rising else "\u2193"),
    ]
    if node:
        north = moon.position(utc + timedelta(hours=1)).latitude > moon.position(utc).latitude
        parts.append(_sign("\u260a" if north else "\u260b", roles["bar_warn"]))
    elif perigee:
        parts.append(_sign("\u2641", roles["bar_warn"]))  # the Earth, too near
    if change and not brief:
        when, nxt = change
        local = when.astimezone(now.tzinfo)
        parts.append(
            dim("then ") + _sign(nxt.day_sign, roles["dim"]) + dim(f" {nxt.day} {local:%a %H:%M}")
        )
    text = "  ".join(parts)

    tip = [
        f"{sky.moon_trend(now).capitalize()} moon. " + almanac.dwelling(here),
        f"{almanac.season(now, cfg.place)}: {almanac.work(here.day, now, cfg.place)}",
        almanac.KEEPING[here.day],
        almanac.sap(rising, now, cfg.place),
    ]
    if node:
        tip.append(almanac.UNFAVOURABLE["node"])
    if perigee:
        tip.append(almanac.UNFAVOURABLE["perigee"])
    if change:
        when, nxt = change
        tip.append(f"Into {nxt.name} ({nxt.day.lower()}) {when.astimezone(now.tzinfo):%A %H:%M}.")
    tip.append("")
    tip.append(
        "The week: "
        + ", ".join(
            f"{d.date:%a} {d.kind.day.lower()}" + (" (unlucky)" if d.unfavourable else "")
            for d in week
        )
    )
    tip.append("Click for the almanac.")
    return text, "\n".join(tip)


def _announce(here: moon.Constellation) -> None:
    """Say so on the message line when the Moon moves into a new constellation."""
    seen = state_dir() / "moon-seen"
    try:
        before = seen.read_text().strip()
    except OSError:
        before = ""
    if before == here.name:
        return
    write_atomic(seen, here.name + "\n")
    if before:
        transmute.run("notify-send", "-a", "athanor", almanac.entering(here))


def cmd_pick(args) -> None:
    if args.what == "light":
        print(pick.light_line(transmute.saved_scheme()))
        return
    {
        "bluetooth": pick.bluetooth,
        "sound": pick.sound,
        "brightness": pick.brightness,
        "night": pick.toggle_night,
    }[args.what]()


def cmd_moon(args) -> None:
    while True:
        now = _now()
        text, tip = _moon_lines(now)
        if not args.waybar:
            print(tip)
            return
        _announce(moon.constellation(now.astimezone(UTC)))
        print(json.dumps({"text": text, "tooltip": tip}), flush=True)
        time.sleep(300 - time.time() % 300 + 0.5)


def _any_key(prompt: str) -> None:
    """NetHack's --More--: any key goes on."""
    import termios
    import tty

    print(prompt, end="", flush=True)
    try:
        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
    except (OSError, termios.error, ValueError):
        return
    try:
        tty.setcbreak(fd)
        sys.stdin.read(1)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def cmd_almanac(args) -> None:
    if args.window:
        # The terminal's own face for text, Athanor for every
        # sign it lacks: zodiac, moon phases, the nodes, the four day signs.
        face = config.TERMINAL_FONTS[config.load().terminal_font]
        fonts = f"{face.family}:pixelsize={face.px},{SIGN_FONT.split()[0]}:pixelsize=32"
        if face.fallback:
            fonts += f",{face.fallback}"
        subprocess.Popen(
            [
                "uwsm-app",
                "--",
                "foot",
                "--app-id",
                args.app_id,
                "--title",
                "Almanac",
                "--config",
                str(Path.home() / ".config/athanor/current/foot/foot.ini"),
                "-o",
                f"font={fonts}",
                "-e",
                str(Path.home() / ".local/bin/athanor"),
                "almanac",
                "--wait",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return
    now = _now()
    roles = palette.load(transmute.saved_scheme()).roles
    print(
        almanac.page(
            now.date(),
            args.days,
            now.tzinfo,
            roles,
            color=sys.stdout.isatty() or args.color,
            place=config.load().place,
        )
    )
    if args.wait:
        _any_key("  --More--")


def _lock_markup(lines: dict[str, str], colors: str) -> str:
    fg, active, dim = (f"#{c.lstrip('#')}" for c in colors.split(","))
    rows = [("date", fg), ("ruler", active), ("moon", dim), ("card", dim)]
    body = "\n".join(
        f'<span foreground="{c}">{html.escape(lines[k], quote=False)}</span>' for k, c in rows
    )
    return f'<span line_height="1.5">{body}</span>'


def cmd_hour(args) -> None:
    cfg = config.load()
    if not (args.waybar or args.follow):
        lines = _hour_lines(_now(), cfg)
        if args.lock:
            print(_lock_markup(lines, args.lock))
            return
        keys = [args.line] if args.line else ["date", "ruler", "trump", "moon", "card"]
        print("\n".join(lines[k] for k in keys))
        return
    while True:
        now = _now()
        lines = _hour_lines(now, cfg)
        tip = "\n".join(lines[k] for k in ("ruler", "trump", "sun", "moon", "card"))
        text = lines["bar"]
        if args.waybar:
            # The bar's clock box carries the moon too: the day's kind at a
            # glance, the rest of the almanac in the tooltip.
            moon_text, moon_tip = _moon_lines(now, brief=True)
            text = _bar_markup(now, cfg) + "   " + moon_text
            tip = "\n".join(lines[k] for k in ("ruler", "trump", "sun", "card"))
            tip += "\n\n" + moon_tip
            _announce(moon.constellation(now.astimezone(UTC)))
        print(json.dumps({"text": text, "tooltip": tip}), flush=True)
        if not args.follow:
            return
        time.sleep(60.5 - time.time() % 60)


def cmd_inventory(args) -> None:
    if args.list:
        found = inventory.items(hypr.query("clients") or [], hypr.active_workspace())
        print("\n".join(i.text for i in found) or "You are empty handed.")
    else:
        inventory.choose()


def cmd_agents(args) -> None:
    if args.refresh:
        agents.refresh(agents.usage_dir(), force=True)
    if args.toggle:
        agents.toggle(args.toggle)
        return
    if args.waybar:
        agents.waybar(lambda: agents.colors(palette.load(transmute.saved_scheme())), only=args.only)
    else:
        print(agents.plain())


def cmd_status(args) -> None:
    if args.waybar:
        status.waybar()
    else:
        print(status.plain(args.short))


def cmd_transmute(args) -> None:
    name = args.scheme
    if args.next or name is None:
        name = palette.following(transmute.saved_scheme())
    size = _size(args.size) if args.size else None
    scheme, walls = transmute.apply(name, reload=not args.no_reload, size=size)
    print(f"You read a scroll of transmutation. {transmute.HUES[scheme.name]}")
    if walls is None:
        print("No plates were drawn because ImageMagick is missing. pacman -S imagemagick")


def cmd_boot(args) -> None:
    from . import boot

    size = _size(args.size) if args.size else None
    try:
        out = boot.stage(args.scheme, size=size)
    except (boot.MissingFont, wall.MissingTool) as e:
        sys.exit(f"athanor boot: {e}")
    scheme = (out / "scheme").read_text().strip()
    print(f"The boot screens are staged in {out} ({scheme}).")
    print("Put them in place with: sudo athanor-system install")


def cmd_doctor(args) -> None:
    from . import doctor

    sys.exit(doctor.main(as_json=args.json))


def cmd_prerender(_args) -> None:
    transmute.prerender()


def cmd_quit(_args) -> None:
    from . import quit

    quit.ask()


def cmd_wall(args) -> None:
    print(transmute.show_level(args.dlvl))


def cmd_wake(args) -> None:
    transmute.wake(wall=not args.no_wall)


def cmd_stages(args) -> None:
    cfg = config.load()
    if not args.follow:
        scheme = stages.scheme_at(sky.planetary_hour(_now(), cfg.place))
        print(f"The work is in {stages.STAGES[scheme]}: {palette.load(scheme).label}.")
        if not cfg.stages:
            print("Set stages = true under [transmute] to follow it.")
        return
    if not cfg.stages:
        return
    current = stages.scheme_at(sky.planetary_hour(_now(), cfg.place))
    while True:
        time.sleep(60.5 - time.time() % 60)
        scheme = stages.scheme_at(sky.planetary_hour(_now(), cfg.place))
        if scheme != current:
            current = scheme
            transmute.apply(scheme, message=stages.announcement(scheme))


def _sixel_ok() -> bool:
    if os.environ.get("ATHANOR_SIXEL") in ("0", "1"):
        return os.environ["ATHANOR_SIXEL"] == "1"
    return sys.stdout.isatty() and os.environ.get("TERM", "").startswith("foot")


def _art_dir() -> Path:
    return cache_dir() / "tarot"


CARD_HEIGHT = 360


def _caption(draw: tarot.Draw, position: str, color: bool) -> None:
    head = f"{position}: " if position else ""
    print(ansi.paint(head, 8, color) + ansi.paint(draw.title, 15, color))
    print("  " + draw.meaning)


def _show_art(draws: list[tarot.Draw]) -> None:
    cards = [(tarot.art_path(d.card, _art_dir()), d.reversed) for d in draws]
    cards = [(src, rev) for src, rev in cards if src.exists()]
    if not cards:
        return
    scheme = palette.load(transmute.saved_scheme())
    fit = max(1, shutil.get_terminal_size().columns * 8 // (CARD_HEIGHT * 58 // 100 + 16))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pngs = [
                str(
                    wall.card_image(
                        src, scheme, rev, "png", Path(tmp) / f"{i}.png", height=CARD_HEIGHT
                    )
                )
                for i, (src, rev) in enumerate(cards)
            ]
            sixel = wall.spread_image(pngs, scheme, min(fit, len(pngs)))
        sys.stdout.flush()
        sys.stdout.buffer.write(sixel)
        sys.stdout.write("\n")
    except (wall.MissingTool, OSError, subprocess.CalledProcessError):
        pass


def _show(draw: tarot.Draw, position: str, art: bool, color: bool) -> None:
    _caption(draw, position, color)
    if art:
        _show_art([draw])


def cmd_draw(args) -> None:
    color = ansi.enabled()
    art = not args.no_art and _sixel_ok()
    if args.day or args.png:
        seed, _ = sigil.host_digest()
        today = _now().date()
        draw = tarot.card_of_day(today, seed)
        if args.png:
            out = transmute.card_of_day_png(palette.load(transmute.saved_scheme()))
            if out:
                print(out)
            return
        _show(draw, "", art, color)
        return
    if args.card:
        draws = [tarot.draw_by_name(name) for name in args.card]
        for name, draw in zip(args.card, draws, strict=True):
            if draw is None:
                sys.exit(f"There is no card called {name!r}.")
        n = len(draws)
    else:
        n = args.n
        draws = tarot.spread(n)
    positions = tarot.SPREAD_POSITIONS.get(n) or tuple(str(i + 1) for i in range(n))
    for position, draw in zip(positions, draws, strict=True):
        _caption(draw, position, color)
    if art:
        _show_art(draws)


def cmd_cards(args) -> None:
    if args.action == "fetch":
        n = tarot.fetch_art(_art_dir())
        print(f"{n} cards in {_art_dir()}.")
    else:
        for card in tarot.DECK:
            print(f"{card.title:<26} {card.upright}")


def cmd_sigil(args) -> None:
    digest, fingerprint = sigil.host_digest()
    cells = sigil.grid(digest)
    if args.png:
        color = palette.load(transmute.saved_scheme()).roles["sigil"]
        write_atomic(Path(args.png), sigil.png(cells, color, args.scale))
        return
    if args.fingerprint:
        print(fingerprint)
        return
    print(sigil.text(cells))
    print(fingerprint)


def _tomb_state() -> Path:
    return state_dir() / "tomb.json"


def cmd_tomb(args) -> None:
    if args.demo:
        print(tomb.stone("firefox", 11, _now().year, dlvl=2))
        return
    crash = tomb.latest()
    try:
        seen = json.loads(_tomb_state().read_text())
    except (OSError, json.JSONDecodeError):
        seen = {}
    if args.notify:
        if crash is None or crash.stamp <= seen.get("stamp", 0):
            return
        dlvl = hypr.active_workspace()
        write_atomic(_tomb_state(), json.dumps({"stamp": crash.stamp, "dlvl": dlvl}))
        if tomb.from_last_session(crash, hypr.session_start()):
            return
        where = f" on Dlvl {dlvl}" if dlvl is not None else ""
        # The process picked its own name and mako parses Pango markup.
        transmute.run(
            "notify-send",
            "-a",
            "athanor",
            "--",
            f"{html.escape(crash.name)} was killed by a {tomb.cause(crash.signal)}{where}.",
        )
        return
    if crash is None:
        print("No one has died here.")
        return
    dlvl = seen.get("dlvl") if seen.get("stamp") == crash.stamp else None
    print(tomb.stone(crash.name, crash.signal, crash.when.year, dlvl))


def cmd_room(args) -> None:
    from . import room

    cfg = config.load()
    if args.once:
        marker = runtime_dir() / "athanor-room"
        if marker.exists():
            return
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    color = ansi.enabled()
    greeted = state_dir() / "greeted"
    if args.once and not greeted.exists():
        print(guide.greeting(cfg.name or getpass.getuser(), cfg.title) + "\n")
        write_atomic(greeted, "")
    card = None
    if cfg.tarot_on_login:
        seed, _ = sigil.host_digest()
        card = tarot.card_of_day(_now().date(), seed).title
    print(room.room(cfg, card, color))
    note = guide.moon_note(sky.moon_phase(_now()))
    if note:
        print(ansi.paint(note, 3, color))


def cmd_guide(_args) -> None:
    text = guide.text(ansi.enabled())
    if sys.stdout.isatty() and len(text.splitlines()) >= shutil.get_terminal_size().lines:
        pager = os.environ.get("PAGER") or "less"
        if shutil.which(pager.split()[0]):
            subprocess.run(
                [*pager.split(), "-R"] if pager == "less" else pager.split(),
                input=text,
                text=True,
                check=False,
            )
            return
    print(text)


def cmd_sheet(_args) -> None:
    from . import room

    print(room.sheet(config.load(), ansi.enabled()))


def cmd_font(_args) -> None:
    face = config.TERMINAL_FONTS[config.load().terminal_font]
    bold = f", with {face.bold} for bold" if face.bold else ""
    print(f"{face.family} at {face.px}px ({face.px * 72 / 96:g}pt at 96 dpi){bold}")


def cmd_palette(args) -> None:
    scheme = palette.load(args.scheme or transmute.saved_scheme())
    print(scheme.label)
    for i, c in enumerate(scheme.ansi):
        r, g, b = palette.rgb(c)
        name = ("br " if i > 7 else "") + palette.ANSI_NAMES[i % 8]
        pigment = palette.PIGMENTS[i % 8]
        print(f"\033[48;2;{r};{g};{b}m      \033[0m {i:>2} {pigment:<10} {name:<11} {c}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="athanor", description="An alchemical layer for Arch and Hyprland."
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("transmute", help="switch color scheme")
    s.add_argument("scheme", nargs="?", choices=palette.SCHEMES)
    s.add_argument("--next", action="store_true", help="switch to the next scheme")
    s.add_argument("--no-reload", action="store_true", help="render without reloading anything")
    s.add_argument("--size", metavar="WxH", help="screen size")
    s.set_defaults(fn=cmd_transmute)

    s = sub.add_parser("boot", help="stage the bootloader, splash, console and greeter")
    s.add_argument("scheme", nargs="?", choices=palette.SCHEMES, help="default: [boot] scheme")
    s.add_argument("--size", metavar="WxH", help="screen size")
    s.set_defaults(fn=cmd_boot)

    s = sub.add_parser("doctor", help="check the install")
    s.add_argument("--json", action="store_true", help="print JSON")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("prerender", help="render the wallpapers for every scheme")
    s.set_defaults(fn=cmd_prerender)

    s = sub.add_parser("quit", help="ask, then quit Hyprland")
    s.set_defaults(fn=cmd_quit)

    s = sub.add_parser("wall", help="set the wallpaper for a workspace")
    s.add_argument("dlvl", nargs="?", type=int, help="workspace number (default: current)")
    s.set_defaults(fn=cmd_wall)

    s = sub.add_parser("wake", help="render and set the wallpaper at login")
    s.add_argument("--no-wall", action="store_true", help="skip the wallpaper")
    s.set_defaults(fn=cmd_wake)

    s = sub.add_parser("stages", help="show the stage for this hour")
    s.add_argument("--follow", action="store_true", help="keep switching schemes with the stages")
    s.set_defaults(fn=cmd_stages)

    s = sub.add_parser("windows", help="pick an open window")
    s.add_argument("--list", action="store_true", help="print the list instead")
    s.set_defaults(fn=cmd_inventory)

    s = sub.add_parser("status", help="print the status line")
    s.add_argument("--waybar", action="store_true", help="JSON for Waybar")
    s.add_argument("--short", action="store_true", help="only Hp and T")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("agents", help="show Claude, ChatGPT and z.ai subscription usage")
    s.add_argument("--waybar", action="store_true", help="JSON for Waybar, every 30 seconds")
    s.add_argument("--refresh", action="store_true", help="fetch fresh limits now")
    s.add_argument("--only", metavar="AGENT", help="one agent's line (claude, codex, zai)")
    s.add_argument("--toggle", metavar="AGENT", help="show that agent's next pool")
    s.set_defaults(fn=cmd_agents)

    s = sub.add_parser("pick", help="a menu for Bluetooth, the sound mixer or brightness")
    s.add_argument("what", choices=("bluetooth", "sound", "brightness", "night", "light"))
    s.set_defaults(fn=cmd_pick)

    s = sub.add_parser("almanac", help="the biodynamic almanac for the month ahead")
    s.add_argument("--days", type=int, default=31)
    s.add_argument("--color", action="store_true", help="colour even when piped")
    s.add_argument("--wait", action="store_true", help="wait for a key before leaving")
    s.add_argument("--window", action="store_true", help="open it in a floating terminal")
    s.add_argument("--app-id", default="athanor-almanac", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_almanac)

    s = sub.add_parser("moon", help="the Moon's constellation for the biodynamic calendar")
    s.add_argument("--waybar", action="store_true", help="JSON for Waybar, every five minutes")
    s.set_defaults(fn=cmd_moon)

    s = sub.add_parser("hour", help="show the planetary hour, the moon and the card of the day")
    s.add_argument("--line", choices=("date", "ruler", "trump", "moon", "card", "bar", "sun"))
    s.add_argument("--lock", metavar="FG,ACTIVE,DIM", help="Pango markup for hyprlock")
    s.add_argument("--waybar", action="store_true", help="JSON for Waybar")
    s.add_argument("--follow", action="store_true", help="print again every minute")
    s.set_defaults(fn=cmd_hour)

    s = sub.add_parser("draw", help="draw tarot cards")
    s.add_argument(
        "n",
        nargs="?",
        type=int,
        default=1,
        choices=range(1, 11),
        metavar="N",
        help="how many, 1 to 10",
    )
    s.add_argument("--day", action="store_true", help="show the card of the day")
    s.add_argument(
        "--card",
        action="append",
        help='pick a card by name, like "the magician, reversed" (repeatable)',
    )
    s.add_argument("--png", action="store_true", help="render today's card and print its path")
    s.add_argument("--no-art", action="store_true", help="text only")
    s.set_defaults(fn=cmd_draw)

    s = sub.add_parser("cards", help="list the deck, or fetch the card images")
    s.add_argument("action", nargs="?", choices=("list", "fetch"), default="list")
    s.set_defaults(fn=cmd_cards)

    s = sub.add_parser("sigil", help="show this machine's sigil")
    s.add_argument("--png", metavar="PATH", help="write it as a PNG")
    s.add_argument("--scale", type=int, default=8, help="pixels per cell")
    s.add_argument("--fingerprint", action="store_true", help="print only the host key fingerprint")
    s.set_defaults(fn=cmd_sigil)

    s = sub.add_parser("tomb", help="show the last crash")
    s.add_argument(
        "--notify", action="store_true", help="send a notification if there is a new crash"
    )
    s.add_argument("--demo", action="store_true", help="show a sample tombstone")
    s.set_defaults(fn=cmd_tomb)

    s = sub.add_parser("guide", help="explain the screen, keys and commands")
    s.set_defaults(fn=cmd_guide)

    s = sub.add_parser("room", help="describe the room")
    s.add_argument("--once", action="store_true", help="only once per boot")
    s.set_defaults(fn=cmd_room)

    s = sub.add_parser("sheet", help="show the character sheet")
    s.set_defaults(fn=cmd_sheet)

    s = sub.add_parser("font", help="print the terminal font and size")
    s.set_defaults(fn=cmd_font)

    s = sub.add_parser("palette", help="print a scheme's colors")
    s.add_argument("scheme", nargs="?", choices=palette.SCHEMES)
    s.set_defaults(fn=cmd_palette)
    return p


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    with contextlib.suppress(BrokenPipeError, KeyboardInterrupt):
        args.fn(args)
