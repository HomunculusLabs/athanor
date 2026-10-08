import os
import re
import shutil
import struct
import subprocess
import tomllib
import zlib
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cache
from importlib.resources import files
from pathlib import Path

from . import palette
from .paths import state_dir, write_atomic

THEME = "athanor-icons"

# Each icon is drawn on a 32-pixel grid and only ever scaled by whole pixels.
GRID = 32
SIZES = (32, 64, 96, 128, 256)
CENTRE = 15
# Folders and files share their height: rows 1 to 29.
TOP, BOTTOM = 1, 29
# Folders are a seal, files a tablet, apps and dialogs a ring.
CONTEXTS = {
    "folder": ("places", "Places"),
    "file": ("mimetypes", "MimeTypes"),
    "app": ("apps", "Applications"),
    "status": ("status", "Status"),
}
# Symbolic icons are one colour on the font's own 16 px em; GTK paints them in the text colour.
SYMBOLIC = 16
SYMBOLIC_DIR = "16x16/symbolic"

GSETTINGS = ("org.gnome.desktop.interface", "icon-theme")


@dataclass(frozen=True)
class Rule:
    sign: str
    match: tuple[str, ...]


@cache
def _data() -> dict:
    return tomllib.loads((files("athanor") / "icons.toml").read_text())


@cache
def signs() -> dict[str, tuple[str, ...]]:
    out = {}
    arts = {name: s["art"] for name, s in _data()["signs"].items()}
    arts |= {f"letter-{ch}": art for ch, art in _data()["letters"].items()}
    for name, art in arts.items():
        rows = art.strip("\n").split("\n")
        width = max(map(len, rows))
        out[name] = tuple(r.ljust(width) for r in rows)
    return out


@cache
def rules(kind: str) -> tuple[Rule, ...]:
    return tuple(Rule(r["sign"], tuple(r["match"])) for r in _data()[kind])


def theme_dir() -> Path:
    return _data_home() / "icons" / THEME


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def _circle(r: int) -> list[tuple[int, int]]:
    """A midpoint circle round the centre, as the font computes its seals."""
    pts, x, y, e = [], r, 0, 1 - r
    while x >= y:
        for a, b in ((x, y), (y, x), (-y, x), (-x, y), (-x, -y), (-y, -x), (y, -x), (x, -y)):
            pts.append((CENTRE + a, CENTRE + b))
        y += 1
        if e < 0:
            e += 2 * y + 1
        else:
            x -= 1
            e += 2 * (y - x) + 1
    return pts


def _seal() -> list[tuple[int, int]]:
    """A circle in a square, the first two of the font's seals."""
    lo, hi = TOP, BOTTOM
    pts = [(x, y) for x in range(lo, hi + 1) for y in (lo, hi)]
    pts += [(x, y) for y in range(lo, hi + 1) for x in (lo, hi)]
    return pts + _circle(12)


def _tablet() -> list[tuple[int, int]]:
    """An upright tablet as tall as the seal, its top right corner cut and folded."""
    left, right, fold = 4, 26, 5
    pts = [(x, TOP) for x in range(left, right - fold + 1)]
    pts += [(x, BOTTOM) for x in range(left, right + 1)]
    pts += [(left, y) for y in range(TOP, BOTTOM + 1)]
    pts += [(right, y) for y in range(TOP + fold, BOTTOM + 1)]
    pts += [(right - fold + k, TOP + k) for k in range(1, fold + 1)]
    pts += [(right - fold, y) for y in range(TOP, TOP + fold + 1)]
    pts += [(x, TOP + fold) for x in range(right - fold, right + 1)]
    return pts


def _ring() -> list[tuple[int, int]]:
    """A single circle as tall as the seal."""
    return _circle(BOTTOM - CENTRE)


def grid(kind: str, sign: str) -> list[list[int]]:
    """0 is empty, 1 the outline, 2 the sign."""
    g = [[0] * GRID for _ in range(GRID)]
    shape = {"folder": _seal, "file": _tablet}.get(kind, _ring)
    for x, y in shape():
        g[y][x] = 1
    # A tablet's sign sits a pixel low, clear of the fold.
    cy = CENTRE + 1 if kind == "file" else CENTRE
    rows = signs()[sign]
    h, w = len(rows), len(rows[0])
    x0, y0 = CENTRE - (w - 1) // 2, cy - (h - 1) // 2
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch == "#":
                g[y0 + j][x0 + i] = 2
    return g


def png(cells: list[list[int]], colors: dict[int, str], scale: int) -> bytes:
    def rgba(hexcolor: str) -> bytes:
        h = hexcolor.lstrip("#")
        return bytes((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255))

    ink = {k: rgba(c) for k, c in colors.items()}
    rows = []
    for row in cells:
        line = b"".join(ink.get(c, bytes(4)) * scale for c in row)
        rows.extend([b"\x00" + line] * scale)
    side = len(cells) * scale

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", side, side, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


def _theme_roots() -> list[Path]:
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [Path.home() / ".icons", _data_home() / "icons"] + [
        Path(d) / "icons" for d in dirs.split(":") if d
    ]


def inherited_names(theme: str) -> dict[str, set[str]]:
    """Icon names by context in `theme` and every theme it inherits."""
    found = {"places": set(), "mimetypes": set()}
    queue, seen = [theme, "hicolor"], set()
    while queue:
        name = queue.pop(0)
        if name in seen or name.startswith("athanor"):
            continue
        seen.add(name)
        for root in _theme_roots():
            base = root / name
            index = base / "index.theme"
            if not index.is_file():
                continue
            for line in index.read_text(errors="replace").splitlines():
                if line.startswith("Inherits="):
                    queue += [t.strip() for t in line.split("=", 1)[1].split(",") if t.strip()]
            for context in found:
                for d in base.glob(f"*/{context}"):
                    found[context] |= {
                        p.name.rsplit(".", 1)[0]
                        for p in d.iterdir()
                        if p.suffix in (".png", ".svg") and "-symbolic" not in p.name
                    }
    return found


def apps() -> dict[str, str]:
    """The icon name and name of every app a launcher would list."""
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    found = {}
    for base in [_data_home(), *(Path(d) for d in dirs.split(":") if d)]:
        for path in sorted((base / "applications").glob("*.desktop")):
            entry, section = {}, False
            for line in path.read_text(errors="replace").splitlines():
                if line.startswith("["):
                    section = line.strip() == "[Desktop Entry]"
                elif section and "=" in line:
                    key, value = line.split("=", 1)
                    entry.setdefault(key.strip(), value.strip())
            hidden = entry.get("NoDisplay") == "true" or entry.get("Hidden") == "true"
            icon = entry.get("Icon", "")
            # An icon given as a file path can't be replaced by a theme.
            if hidden or entry.get("Type") != "Application" or not icon or "/" in icon:
                continue
            found.setdefault(icon, entry.get("Name", ""))
    return found


def _letter(name: str) -> str | None:
    first = next((ch for ch in name.upper() if "A" <= ch <= "Z"), None)
    return f"letter-{first}" if first else None


def assign(
    names: dict[str, set[str]], installed: dict[str, str] | None = None
) -> dict[str, dict[str, str]]:
    """Which sign each icon name gets, by kind: {"folder": {name: sign}, ...}."""
    out = {kind: {} for kind in CONTEXTS}
    literal = {
        k: {p for r in rules(k) for p in r.match if not any(c in p for c in "*?[")} for k in out
    }
    for name in literal["status"]:
        out["status"][name] = next(r.sign for r in rules("status") if name in r.match)
    for icon, title in (installed or {}).items():
        sign = next((r.sign for r in rules("app") if icon in r.match), None) or _letter(title)
        if sign:
            out["app"][icon] = sign
    folders = names["places"] | names["mimetypes"] | literal["folder"]
    for name in sorted(folders):
        for r in rules("folder"):
            if any(fnmatchcase(name, p) for p in r.match):
                out["folder"][name] = r.sign
                break
    for name in sorted(names["mimetypes"] | literal["file"]):
        if name in out["folder"]:
            continue
        for r in rules("file"):
            if any(fnmatchcase(name, p) for p in r.match):
                out["file"][name] = r.sign
                break
    return out


def svg(rows: tuple[str, ...]) -> str:
    """A sign as a symbolic SVG: one rectangle per run of ink, centred on the 16 px em."""
    h, w = len(rows), len(rows[0])
    x0, y0 = (SYMBOLIC - w) // 2, (SYMBOLIC - h) // 2
    rects = []
    for j, row in enumerate(rows):
        for run in re.finditer(r"#+", row):
            rects.append(
                f'<rect x="{x0 + run.start()}" y="{y0 + j}" width="{len(run.group())}" height="1"/>'
            )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SYMBOLIC}" height="{SYMBOLIC}" '
        f'viewBox="0 0 {SYMBOLIC} {SYMBOLIC}" shape-rendering="crispEdges">'
        f'<g fill="#2e3436">{"".join(rects)}</g></svg>\n'
    )


def _index(inherits: str) -> str:
    dirs = [(f"{n}x{n}/{d}", ctx, n) for d, ctx in CONTEXTS.values() for n in SIZES]
    sections = "".join(f"\n[{d}]\nContext={ctx}\nSize={n}\nType=Fixed\n" for d, ctx, n in dirs)
    sections += (
        f"\n[{SYMBOLIC_DIR}]\nContext=Actions\nSize={SYMBOLIC}\n"
        "Type=Scalable\nMinSize=8\nMaxSize=512\n"
    )
    names = ",".join([d for d, _, _ in dirs] + [SYMBOLIC_DIR])
    return (
        f"[Icon Theme]\nName={THEME}\nComment=Athanor's icons, drawn by transmute\n"
        f"Inherits={inherits}\nDirectories={names}\n{sections}"
    )


def render(
    scheme: palette.Scheme,
    root: Path | None = None,
    inherits: str = "Adwaita",
    with_apps: bool = True,
) -> Path:
    root = root or theme_dir()
    colors = {1: scheme.roles["dim"], 2: scheme.roles["active"]}
    names = assign(inherited_names(inherits), apps() if with_apps else None)
    if not with_apps:
        for n in SIZES:
            shutil.rmtree(root / f"{n}x{n}" / "apps", ignore_errors=True)
    for kind, (context, _) in CONTEXTS.items():
        # Every sign is drawn as a folder so [folders] in athanor.toml can use any of them.
        drawn = set(signs()) if kind == "folder" else set(names[kind].values())
        for sign in drawn:
            cells = grid(kind, sign)
            for n in SIZES:
                write_atomic(
                    root / f"{n}x{n}" / context / f"athanor-{kind}-{sign}.png",
                    png(cells, colors, n // GRID),
                )
        for n in SIZES:
            out = root / f"{n}x{n}" / context
            for name, sign in names[kind].items():
                target = f"athanor-{kind}-{sign}.png"
                link = out / f"{name}.png"
                if link.is_symlink() and os.readlink(link) == target:
                    continue
                link.unlink(missing_ok=True)
                link.symlink_to(target)
    for r in rules("symbolic"):
        art = svg(signs()[r.sign])
        for name in r.match:
            write_atomic(root / SYMBOLIC_DIR / f"{name}.svg", art)
    write_atomic(root / "index.theme", _index(inherits))
    # GTK notices a changed theme by the directory's mtime.
    os.utime(root)
    return root


def _gsettings(*args: str) -> str | None:
    if not shutil.which("gsettings"):
        return None
    r = subprocess.run(["gsettings", *args], capture_output=True, text=True, check=False)
    return r.stdout.strip().strip("'") if r.returncode == 0 else None


def previous_theme() -> str:
    """The icon theme in use before Athanor's, kept so other icons stay as they were."""
    saved = state_dir() / "icon-theme"
    current = _gsettings("get", *GSETTINGS)
    if current and not current.startswith("athanor"):
        write_atomic(saved, current + "\n")
        return current
    try:
        return saved.read_text().strip() or "Adwaita"
    except FileNotFoundError:
        return "Adwaita"


def use() -> None:
    if _gsettings("get", *GSETTINGS) not in (None, THEME):
        _gsettings("set", *GSETTINGS, THEME)


def mark(paths: dict[str, str]) -> list[str]:
    """Give folders from the [folders] table their sign. Returns what was skipped."""
    if not shutil.which("gio"):
        return []
    marked, skipped = [], []
    for path, name in paths.items():
        target = Path(path).expanduser()
        if name not in signs() or not target.is_dir():
            skipped.append(path)
            continue
        subprocess.run(
            ["gio", "set", str(target), "metadata::custom-icon-name", f"athanor-folder-{name}"],
            capture_output=True,
            check=False,
        )
        marked.append(str(target))
    # The uninstaller unsets these.
    write_atomic(state_dir() / "folder-marks", "".join(f"{p}\n" for p in marked))
    return skipped
