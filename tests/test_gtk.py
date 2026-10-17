import re

import pytest

from athanor import gtk, palette


@pytest.fixture
def home(tmp_path, monkeypatch):
    for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data")):
        monkeypatch.setenv(var, str(tmp_path / sub))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path


def colors(css: str) -> set[str]:
    return {m.group(0).lower() for m in re.finditer(r"#[0-9a-fA-F]{6}\b", css)}


@pytest.mark.parametrize("name", palette.SCHEMES)
def test_gtk_ground_text_and_accent_become_the_scheme(name):
    scheme = palette.load(name)
    variant = "dark" if palette.is_dark(scheme) else "light"
    ground, text = gtk.GROUND[variant]
    accent = "#15539e" if variant == "dark" else "#3584e4"
    css = gtk.recolor(
        f"a {{ color: {ground}; }} b {{ color: {text}; }} c {{ color: {accent}; }}"
        f" d {{ color: {accent}; }}",
        scheme,
        variant,
    )
    assert f"color: {scheme.roles['bg']};" in css
    assert f"color: {scheme.roles['fg']};" in css
    assert f"color: {scheme.roles['active']};" in css


def test_alpha_is_kept_and_greys_stay_on_the_ramp():
    scheme = palette.load("umber")
    css = gtk.recolor("a { color: rgba(0, 0, 0, 0.7); } b { color: #ffffff; }", scheme, "dark")
    assert re.search(r"rgba\(\d+, \d+, \d+, 0\.7\)", css)
    assert "#ffffff" not in css


@pytest.mark.parametrize(
    "name", ["gtk3-dark.css", "gtk3-light.css", "gtk4-dark.css", "gtk4-light.css"]
)
def test_vendored_sheets_are_square_and_find_their_images(name):
    css = gtk._vendored(name)
    assert not re.search(r"radius:\s*[^;}%]*[1-9][^;}%]*px", css)
    assert 'url("assets/' not in css
    assert "resource:///org/gtk/libgtk/theme/" in css


@pytest.mark.parametrize("name", palette.SCHEMES)
def test_no_blue_survives_a_whole_sheet(name):
    scheme = palette.load(name)
    variant = "dark" if palette.is_dark(scheme) else "light"
    css = gtk.recolor(gtk._vendored(f"gtk3-{variant}.css"), scheme, variant)
    for c in ("#15539e", "#3584e4", "#1b6acb", "#353535", "#f6f5f4"):
        assert c not in colors(css)


def test_render_writes_both_toolkits(home, monkeypatch):
    monkeypatch.setattr(gtk, "rendered", lambda: home / "gtk")
    (home / "gtk" / "gtk-4.0").mkdir(parents=True)
    (home / "gtk" / "gtk-4.0" / "athanor.css").write_text("/* ours */\n")
    root = gtk.render(palette.load("vellum"))
    assert 'font-family: "Vellum"' in (root / "gtk-3.0" / "gtk.css").read_text()
    assert (root / "gtk-4.0" / "gtk.css").read_text().rstrip().endswith("/* ours */")


def test_use_links_the_theme_and_keeps_what_was_there(home, monkeypatch):
    monkeypatch.setattr(gtk, "rendered", lambda: home / "current" / "gtk")
    monkeypatch.setattr(gtk, "current_dir", lambda: home / "current")
    (home / "current" / "gtk" / "gtk-4.0").mkdir(parents=True)
    settings = {"gtk-theme": "Adwaita-dark", "color-scheme": "prefer-dark"}

    def fake(*args):
        if args[0] == "get":
            return settings[args[2]]
        settings[args[2]] = args[3]

    monkeypatch.setattr(gtk, "gsettings", fake)
    assert gtk.use(palette.load("vellum")) == []
    assert gtk.theme_link().resolve() == (home / "current" / "gtk").resolve()
    assert settings == {"gtk-theme": "athanor", "color-scheme": "prefer-light"}
    state = home / "state" / "athanor"
    assert (state / "gtk-theme").read_text() == "Adwaita-dark\n"
    assert (state / "color-scheme").read_text() == "prefer-dark\n"
    gtk.use(palette.load("umber"))
    assert (state / "color-scheme").read_text() == "prefer-dark\n", "the first value is kept"


def test_a_stylesheet_of_the_users_is_left_alone(home, monkeypatch):
    monkeypatch.setattr(gtk, "rendered", lambda: home / "current" / "gtk")
    monkeypatch.setattr(gtk, "current_dir", lambda: home / "current")
    monkeypatch.setattr(gtk, "gsettings", lambda *a: None)
    gtk.user_css().parent.mkdir(parents=True)
    gtk.user_css().write_text("/* mine */")
    assert gtk.use(palette.load("umber")) == [str(gtk.user_css())]
    assert gtk.user_css().read_text() == "/* mine */"
