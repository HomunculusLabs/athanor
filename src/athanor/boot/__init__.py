"""The screens before the session: Limine, the Plymouth splash, the console and the greeter.

`athanor boot` stages them in ~/.local/share/athanor/system. They are root's to
install, so `sudo athanor-system install` puts them in place. Boot takes one scheme,
not the hour's: the machine starts in the dark as often as not, so umber unless
[boot] scheme says otherwise.
"""

import getpass
import shutil
import socket
import subprocess
from importlib.resources import files
from pathlib import Path

from .. import config, palette, sigil, wall
from ..paths import _xdg, cache_dir, write_atomic
from ..render import render

# Code page 437 below the printable range, which Python's cp437 codec leaves as controls.
CP437_LOW = " ☺☻♥♦♣♠•◘○◙♂♀♪♫☼►◄↕‼¶§▬↨↑↓→←∟↔▲▼"

FONTS = {
    "vellum": "Vellum:style=Regular",
    "ossuary": "Ossuary Display",
    "vga": "PxPlus IBM VGA 8x16",
}

# Ossuary Display is drawn for 32px and Vellum for 12px, so these land on the grid.
TITLE_PX = 128
LABEL_PX = 24


class MissingFont(RuntimeError):
    pass


def stage_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "athanor" / "system"


def _source(name: str) -> str:
    return (files("athanor") / "boot" / name).read_text()


def font_file(pattern: str) -> Path:
    out = subprocess.run(
        ["fc-match", "-f", "%{file}\n%{family}", pattern], capture_output=True, text=True
    )
    path, _, family = out.stdout.partition("\n")
    wanted = pattern.split(":")[0]
    if out.returncode != 0 or not path or wanted.lower() not in family.lower():
        raise MissingFont(f"no font {wanted!r}; run ./install.sh to fetch Athanor's fonts")
    return Path(path)


def _magick(*args: str) -> bytes:
    exe = shutil.which("magick")
    if not exe:
        raise wall.MissingTool("the boot screens need ImageMagick 7. pacman -S imagemagick")
    return subprocess.run([exe, *args], capture_output=True, check=True).stdout


def _escape(ch: str) -> str:
    # -annotate reads % as a format escape and a leading @ as a file name.
    return {"%": "%%", "\\": "\\\\", "@": "\\@"}.get(ch, ch)


def cp437_chars() -> list[str]:
    high = bytes(range(128, 256)).decode("cp437")
    return list(CP437_LOW) + [chr(c) for c in range(32, 127)] + ["⌂"] + list(high)


def vga_font(ttf: Path) -> bytes:
    """Limine's term_font: 256 CP437 glyphs, 8x16, one byte per row."""
    chars = cp437_chars()
    draws: list[str] = []
    for i, ch in enumerate(chars):
        if ch != " ":
            # +x+y is the baseline; the VGA face's sits 12px down its 16px cell.
            draws += ["-annotate", f"+{i * 8}+12", _escape(ch)]
    raw = _magick(
        "-size", f"{len(chars) * 8}x16", "xc:black",
        "-font", str(ttf), "-pointsize", "16", "+antialias",
        "-fill", "white", *draws,
        "-depth", "8", "gray:-",
    )  # fmt: skip
    width = len(chars) * 8
    out = bytearray()
    for i in range(len(chars)):
        for y in range(16):
            row = raw[y * width + i * 8 : y * width + i * 8 + 8]
            out.append(sum(1 << (7 - x) for x, v in enumerate(row) if v > 127))
    return bytes(out)


def text_png(out: Path, text: str, ttf: Path, px: int, color: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    _magick(
        "-background", "none", "-fill", color, "-font", str(ttf),
        "-pointsize", str(px), "+antialias", f"label:{text}", str(out),
    )  # fmt: skip


def box_png(out: Path, w: int, h: int, fill: str, edge: str | None = None, t: int = 2) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if edge is None:
        _magick("-size", f"{w}x{h}", f"xc:{fill}", str(out))
        return
    _magick(
        "-size", f"{w}x{h}", f"xc:{edge}", "-fill", fill,
        "-draw", f"rectangle {t},{t} {w - t - 1},{h - t - 1}", str(out),
    )  # fmt: skip


def vtrgb(scheme: palette.Scheme) -> str:
    rgb = [palette.rgb(c) for c in scheme.ansi]
    return "\n".join(",".join(str(c[i]) for c in rgb) for i in range(3)) + "\n"


def console_font() -> Path | None:
    """MEK Mono for the console, as the terminals have it. Destroyer Gray left a PSF of it."""
    for path in (
        Path("/usr/share/kbd/consolefonts/athanor-mekmono.psf.gz"),
        Path("/usr/share/kbd/consolefonts/dg-mekmono.psf.gz"),
    ):
        if path.exists():
            return path
    return None


def limine_block(scheme: palette.Scheme) -> str:
    r, a = scheme.roles, scheme.ansi

    def hx(c: str) -> str:
        return c.lstrip("#")

    return "\n".join(
        [
            "# >>> athanor >>>",
            f"# {scheme.label}, from `athanor boot`. athanor-system uninstall undoes it.",
            "interface_branding: Athanor",
            f"interface_branding_color: {hx(r['active'])}",
            f"interface_help_color: {hx(r['dim'])}",
            f"interface_help_color_bright: {hx(r['fg'])}",
            "wallpaper: boot():/athanor/plate.png",
            "wallpaper_style: stretched",
            f"backdrop: {hx(r['bg'])}",
            "term_font: boot():/athanor/vga.f16",
            "term_font_size: 8x16",
            # Fully transparent behind text: the plate sits at the left, the menu in the middle.
            f"term_background: ff{hx(r['bg'])}",
            f"term_background_bright: {hx(r['border'])}",
            f"term_foreground: {hx(r['fg'])}",
            f"term_foreground_bright: {hx(a[15])}",
            "term_palette: " + ";".join(hx(c) for c in a[:8]),
            "term_palette_bright: " + ";".join(hx(c) for c in a[8:]),
            "# <<< athanor <<<",
            "",
        ]
    )


def _ordinal(n: int) -> str:
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def stage(scheme_name: str | None = None, size: tuple[int, int] | None = None, log=print) -> Path:
    from ..transmute import MARGIN, TEXT_COLUMN, lock_layout, screen_size

    cfg = config.load()
    scheme = palette.load(scheme_name or cfg.boot_scheme)
    size = size or screen_size()
    out = stage_dir()
    if out.exists():
        shutil.rmtree(out)

    vellum, ossuary, vga = (font_file(FONTS[k]) for k in ("vellum", "ossuary", "vga"))
    walls = wall.render(scheme, size, cache_dir() / "wall", cfg.pixel_scale)
    layout = lock_layout(size, walls.lock_panel_x, walls.scale)
    digest, fingerprint = sigil.host_digest()
    sigil_png = sigil.png(sigil.grid(digest), scheme.roles["sigil"])
    r = scheme.roles
    user = getpass.getuser()

    # Limine
    lim = out / "limine"
    lim.mkdir(parents=True)
    shutil.copyfile(walls.lock, lim / "plate.png")
    write_atomic(lim / "vga.f16", vga_font(vga))
    write_atomic(lim / "limine.conf.athanor", limine_block(scheme))

    # Plymouth
    ply = out / "plymouth" / "athanor"
    ply.mkdir(parents=True)
    shutil.copyfile(walls.lock, ply / "plate.png")
    write_atomic(ply / "sigil.png", sigil_png)
    text_png(ply / "title.png", "Athanor", ossuary, TITLE_PX, r["fg"])
    text_png(ply / "sealed.png", "The vessel is sealed. Speak the word:", vellum, LABEL_PX, r["fg"])
    text_png(ply / "warming.png", "The fire is lit.", vellum, LABEL_PX, r["dim"])
    text_png(ply / "banked.png", "The fire is banked.", vellum, LABEL_PX, r["dim"])
    box_png(ply / "entry.png", TEXT_COLUMN, 44, r["bg"], r["active"])
    box_png(ply / "bullet.png", 8, 8, r["fg"])
    box_png(ply / "track.png", TEXT_COLUMN, 4, r["border"])
    box_png(ply / "fill.png", TEXT_COLUMN, 4, r["active"])
    toks = {
        **scheme.colors(),
        "label": scheme.label,
        "screen_w": str(size[0]),
        "lock_x": str(layout["lock_x"]),
        **{
            f"{k}_f": ", ".join(f"{v / 255:.3f}" for v in palette.rgb(r[k]))
            for k in ("bg", "fg", "dim")
        },
    }
    write_atomic(ply / "athanor.plymouth", render(_source("athanor.plymouth"), toks))
    write_atomic(ply / "athanor.script", render(_source("athanor.script"), toks))

    # Console
    con = out / "console"
    con.mkdir(parents=True)
    write_atomic(con / "vtrgb", vtrgb(scheme))
    psf = console_font()
    if psf:
        shutil.copyfile(psf, con / "athanor-mekmono.psf.gz")
    else:
        log("no MEK Mono console font; the console keeps its font and takes the colours")

    # Greeter
    gr = out / "greeter"
    gr.mkdir(parents=True)
    shutil.copyfile(walls.lock, gr / "plate.png")
    write_atomic(gr / "sigil.png", sigil_png)
    write_atomic(
        gr / "shell.qml",
        render(
            _source("greeter.qml"),
            {
                **toks,
                "user": user,
                "name": cfg.name or user,
                "title": cfg.title,
                "host": socket.gethostname(),
                "fingerprint": fingerprint if len(fingerprint) <= 24 else fingerprint[:23] + "…",
                "margin": str(MARGIN),
                "text_w": str(TEXT_COLUMN),
            },
        ),
    )

    # Fonts the greeter user and the initramfs can read.
    fonts = out / "fonts"
    fonts.mkdir()
    for f in (vellum, ossuary):
        shutil.copyfile(f, fonts / f.name)
    write_atomic(fonts / "61-athanor-pixel.conf", _source("61-athanor-pixel.conf"))

    write_atomic(out / "scheme", scheme.name + "\n")
    write_atomic(out / "user", user + "\n")
    return out


def preview_font(f16: Path, out: Path) -> None:
    """The Limine font as a 32x8 sheet, for checking the glyphs landed."""
    data = f16.read_bytes()
    rows = []
    for gy in range(8):
        for y in range(16):
            line = []
            for gx in range(32):
                byte = data[(gy * 32 + gx) * 16 + y]
                line += [255 if byte & (1 << (7 - x)) else 0 for x in range(8)]
            rows.append(bytes(line))
    raw = b"".join(rows)
    subprocess.run(
        ["magick", "-size", "256x128", "-depth", "8", "gray:-", "-scale", "400%", str(out)],
        input=raw,
        check=True,
    )
