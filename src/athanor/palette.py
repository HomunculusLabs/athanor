import tomllib
from dataclasses import dataclass
from importlib.resources import files

SCHEMES = ("umber", "vellum", "orpiment", "cinnabar")
RETIRED = {"dore": "cinnabar"}
ANSI_NAMES = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
PIGMENTS = ("ink", "vermilion", "olive", "ochre", "slate", "madder", "verdigris", "paper")
ROLES = ("bg", "fg", "dim", "border", "active", "bar", "barfg", "bar_warn", "sigil")
# The bar's named hues, each the first ANSI slot that reads on the bar.
BAR_HUES = {
    "red": (9, 1),
    "green": (10, 2),
    "ochre": (3, 11),
    "gold": (11, 3),
    "blue": (12, 4),
    "rose": (13, 5),
    "teal": (14, 6),
    "silver": (15, 7),
    "lead": (8, 7),
}


@dataclass(frozen=True)
class Scheme:
    name: str
    label: str
    roles: dict[str, str]
    ansi: tuple[str, ...]
    wall_desk: tuple[str, str]
    wall_lock: tuple[str, str]

    def colors(self) -> dict[str, str]:
        return {**self.roles, **{f"a{i}": c for i, c in enumerate(self.ansi)}}


def _table() -> dict:
    return tomllib.loads((files("athanor") / "palette.toml").read_text())


def load(name: str) -> Scheme:
    raw = _table().get(name)
    if raw is None:
        raise KeyError(f"no scheme {name!r}; the schemes are {' '.join(SCHEMES)}")
    return Scheme(
        name=name,
        label=raw["label"],
        roles={role: raw[role] for role in ROLES},
        ansi=tuple(raw["ansi"]),
        wall_desk=tuple(raw["wall_desk"]),
        wall_lock=tuple(raw["wall_lock"]),
    )


def following(name: str) -> str:
    return SCHEMES[(SCHEMES.index(name) + 1) % len(SCHEMES)]


def rgb(hex_color: str) -> tuple[int, int, int]:
    n = int(hex_color.lstrip("#"), 16)
    return n >> 16, (n >> 8) & 255, n & 255


def blend(a: str, b: str, t: float) -> str:
    """The colour t of the way from a to b."""
    return "#" + "".join(
        f"{round(x + (y - x) * t):02x}" for x, y in zip(rgb(a), rgb(b), strict=True)
    )


def is_dark(scheme: Scheme) -> bool:
    return luminance(scheme.roles["bg"]) < 0.2


def gtk(scheme: Scheme) -> dict[str, str]:
    """Surfaces for GTK, between the ground and the border, as template tokens."""
    bg, border = scheme.roles["bg"], scheme.roles["border"]
    return {
        "gtk_sunk": blend(bg, border, 0.45),
        "gtk_raised": blend(bg, border, 0.7),
    }


def luminance(hex_color: str) -> float:
    def channel(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def readable(scheme: Scheme, slots: tuple[int, ...]) -> str:
    """The first of the scheme's slots that reads on its bar, or the first lifted until it does."""
    bar = scheme.roles["bar"]
    for index in slots:
        if contrast(scheme.ansi[index], bar) >= 4.5:
            return scheme.ansi[index]
    # Lift toward white on a dark bar, sink toward black on a light one, so it keeps its hue.
    light_bar = luminance(bar) > 0.5
    base, toward = rgb(scheme.ansi[slots[0]]), (0, 0, 0) if light_bar else (255, 255, 255)
    for step in range(1, 11):
        t = step / 10
        mixed = "#" + "".join(
            f"{round(a + (b - a) * t):02x}" for a, b in zip(base, toward, strict=True)
        )
        if contrast(mixed, bar) >= 4.5:
            return mixed
    return scheme.roles["barfg"]


def bar_hues(scheme: Scheme) -> dict[str, str]:
    """The named hues as template tokens: bar_red, bar_gold and the rest."""
    return {f"bar_{name}": readable(scheme, slots) for name, slots in BAR_HUES.items()}
