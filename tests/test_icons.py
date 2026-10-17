import re
import struct
import zlib

import pytest

from athanor import icons, palette

ALL = list(icons.signs())


def pixels(data: bytes) -> tuple[int, set[bytes]]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    side = struct.unpack_from(">I", data, 16)[0]
    start = data.index(b"IDAT") + 4
    length = struct.unpack_from(">I", data, start - 8)[0]
    raw = zlib.decompress(data[start : start + length])
    stride = 1 + side * 4
    colors = set()
    for y in range(side):
        row = raw[y * stride + 1 : (y + 1) * stride]
        colors |= {row[i : i + 4] for i in range(0, len(row), 4)}
    return side, colors


def fake_theme(root, name, places=(), mimetypes=(), inherits=""):
    base = root / "icons" / name
    for context, names in (("places", places), ("mimetypes", mimetypes)):
        d = base / "48x48" / context
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / f"{n}.png").write_bytes(b"")
    (base / "index.theme").write_text(f"[Icon Theme]\nName={name}\nInherits={inherits}\n")


@pytest.mark.parametrize("kind", ["folder", "file", "app"])
@pytest.mark.parametrize("name", ALL)
def test_each_sign_fits_inside_with_air(kind, name):
    if name.startswith("bija-") and kind != "folder":
        pytest.skip("bijas only mark folders")
    rows = icons.signs()[name]
    assert set("".join(rows)) <= {"#", " "}
    g = icons.grid(kind, name)
    assert sum(row.count(2) for row in g) == "".join(rows).count("#"), "nothing clipped"
    for y, row in enumerate(g):
        for x, v in enumerate(row):
            if v == 2:
                around = [g[y + dy][x + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
                assert 1 not in around, f"the sign touches the outline at {x},{y}"


def test_the_seal_is_symmetric():
    g = icons.grid("folder", "bindu")
    line = [[int(v == 1) for v in row] for row in g]
    assert line == [list(r) for r in zip(*line, strict=True)], "the same down as across"
    c = icons.CENTRE
    assert all(line[c - k] == line[c + k] for k in range(c + 1)), "the same above as below"


def test_folders_and_files_stand_the_same_height():
    for kind in ("folder", "file", "app"):
        rows = [y for y, row in enumerate(icons.grid(kind, "bindu")) if 1 in row]
        assert (rows[0], rows[-1]) == (icons.TOP, icons.BOTTOM)


def test_every_rule_names_a_sign():
    for kind in ("folder", "file", "app", "status", "symbolic"):
        for r in icons.rules(kind):
            assert r.sign in icons.signs()
    assert icons.rules("file")[-1].match[-1] == "*", "every file type gets a tablet"


def test_names_are_sorted_into_signs():
    got = icons.assign(
        {
            "places": {"folder", "folder-dropbox", "user-home", "network-server"},
            "mimetypes": {
                "inode-directory",
                "image-png",
                "application-epub+zip",
                "application-zip",
                "application-vnd.oasis.opendocument.spreadsheet",
                "text-x-python",
                "text-markdown",
                "model-stl",
                "weird-thing",
            },
        }
    )
    assert got["folder"]["user-home"] == "sol"
    assert got["folder"]["folder-dropbox"] == "bindu"
    assert got["folder"]["inode-directory"] == "bindu"
    assert "network-server" not in got["folder"] and "inode-directory" not in got["file"]
    assert got["file"]["image-png"] == "eye"
    assert got["file"]["application-epub+zip"] == "recipe"
    assert got["file"]["application-zip"] == "salt"
    assert got["file"]["application-vnd.oasis.opendocument.spreadsheet"] == "earth"
    assert got["file"]["text-x-python"] == "sulphur"
    assert got["file"]["text-markdown"] == "heaven"
    assert got["file"]["weird-thing"] == "bindu"
    assert got["file"]["text-x-generic"] == "heaven", "literal names are drawn without a theme"


def test_inherited_names_follow_the_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "none"))
    fake_theme(tmp_path, "Blue", places=["folder-blue"], inherits="Base")
    fake_theme(tmp_path, "Base", mimetypes=["text-x-rust", "text-x-rust-symbolic"])
    found = icons.inherited_names("Blue")
    assert found["places"] == {"folder-blue"}
    assert found["mimetypes"] == {"text-x-rust"}


@pytest.mark.parametrize("name", palette.SCHEMES)
def test_each_scheme_draws_line_and_sign_in_its_own_colors(tmp_path, monkeypatch, name):
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "none"))
    scheme = palette.load(name)
    root = icons.render(scheme, tmp_path / "athanor-icons")
    want = {bytes.fromhex(scheme.roles[k].lstrip("#")) + b"\xff" for k in ("dim", "active")}
    for n in icons.SIZES:
        for icon in ("places/folder-documents.png", "mimetypes/text-x-generic.png"):
            side, colors = pixels((root / f"{n}x{n}" / icon).read_bytes())
            assert side == n
            assert colors - {bytes(4)} == want


def test_the_theme_links_every_name_and_inherits_the_rest(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "none"))
    fake_theme(tmp_path, "Yaru-blue", mimetypes=["audio-flac"])
    root = icons.render(palette.load("umber"), tmp_path / "out", inherits="Yaru-blue")
    index = (root / "index.theme").read_text()
    assert "Inherits=Yaru-blue" in index
    for n in icons.SIZES:
        assert f"[{n}x{n}/places]" in index and f"[{n}x{n}/mimetypes]" in index
        flac = root / f"{n}x{n}" / "mimetypes" / "audio-flac.png"
        assert flac.resolve().name == "athanor-file-mercury.png"
        assert (root / f"{n}x{n}" / "places" / "athanor-folder-fire.png").is_file()
    icons.render(palette.load("vellum"), root, inherits="Yaru-blue")


def test_the_previous_theme_is_kept_once_ours_is_in_use(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    current = {"theme": "Yaru-blue"}
    monkeypatch.setattr(icons, "_gsettings", lambda *a: current["theme"] if a[0] == "get" else None)
    assert icons.previous_theme() == "Yaru-blue"
    current["theme"] = icons.THEME
    assert icons.previous_theme() == "Yaru-blue"


def test_marks_skip_missing_folders_and_unknown_signs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(icons.shutil, "which", lambda _: "/usr/bin/gio")
    calls = []
    monkeypatch.setattr(icons.subprocess, "run", lambda args, **k: calls.append(args))
    (tmp_path / "projects").mkdir()
    skipped = icons.mark(
        {str(tmp_path / "projects"): "fire", str(tmp_path / "gone"): "fire", str(tmp_path): "nope"}
    )
    assert skipped == [str(tmp_path / "gone"), str(tmp_path)]
    assert calls == [
        [
            "gio",
            "set",
            str(tmp_path / "projects"),
            "metadata::custom-icon-name",
            "athanor-folder-fire",
        ]
    ]
    marks = (tmp_path / "state" / "athanor" / "folder-marks").read_text()
    assert marks == f"{tmp_path / 'projects'}\tathanor-folder-fire\n"


def test_folders_get_a_word_sign_or_one_from_the_pool(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    home = tmp_path / "home"
    for name in ("Music", "src", "notes", ".cache", "farm", "zzq", "qqz", "Seed-Bank"):
        (home / name).mkdir(parents=True)
    (home / "file.txt").write_text("")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "user-dirs.dirs").write_text(f'XDG_MUSIC_DIR="{home}/Music"\n')
    got, _ = icons.marks({str(home / "farm"): "fire"}, [str(home)])
    assert got[str(home / "farm")] == "athanor-folder-fire", "[folders] wins"
    assert str(home / "Music") not in got and str(home / ".cache") not in got
    assert got[str(home / "notes")] == "athanor-folder-ouroboros"
    assert got[str(home / "src")] == "athanor-folder-sulphur"
    assert got[str(home / "Seed-Bank")] == "athanor-folder-leaf"
    a, b = got[str(home / "zzq")], got[str(home / "qqz")]
    assert a != b and {a, b} <= {f"athanor-folder-{p}" for p in icons.pool()}
    assert icons.marks({}, [str(home)])[0][str(home / "zzq")] == a, "it stays put"
    own, _ = icons.marks({}, [str(home)], {"note*": "flower", "zz*": "nope"})
    assert own[str(home / "notes")] == "athanor-folder-flower", "your words come first"
    assert own[str(home / "zzq")] == a, "a word with an unknown sign is ignored"


def test_names_split_into_words():
    assert icons.words("BonzAi-Buddy_audio streaming.v2") == [
        "bonzai",
        "buddy",
        "audio",
        "streaming",
        "v",
        "2",
    ]
    assert icons.words("nq138-alt") == ["nq", "138", "alt"]


def test_every_word_rule_names_a_sign_and_the_pool_is_big():
    for r in icons.rules("words"):
        assert r.sign in icons.signs()
    assert len(icons.pool()) >= 200


def test_marking_skips_what_is_already_set_and_unsets_what_left(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(icons.shutil, "which", lambda _: "/usr/bin/gio")
    calls = []
    monkeypatch.setattr(icons.subprocess, "run", lambda args, **k: calls.append(args))
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    icons.mark({str(a): "fire", str(b): "water"})
    calls.clear()
    icons.mark({str(a): "fire"})
    assert calls == [["gio", "set", "-t", "unset", str(b), "metadata::custom-icon-name"]]


def test_symbolic_signs_fit_the_em():
    for r in icons.rules("symbolic"):
        rows = icons.signs()[r.sign]
        assert len(rows) <= icons.SYMBOLIC and len(rows[0]) <= icons.SYMBOLIC, r.sign
        assert all(name.endswith("-symbolic") for name in r.match)


def test_symbolic_icons_are_crisp_svgs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "none"))
    root = icons.render(palette.load("umber"), tmp_path / "t")
    assert f"[{icons.SYMBOLIC_DIR}]" in (root / "index.theme").read_text()
    art = (root / icons.SYMBOLIC_DIR / "go-previous-symbolic.svg").read_text()
    assert 'shape-rendering="crispEdges"' in art
    cells = sum(int(w) for w in re.findall(r'width="(\d+)" height="1"', art))
    assert cells == "".join(icons.signs()["back"]).count("#")


def desktop(root, name, **entry):
    path = root / "applications" / f"{name}.desktop"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{k}={v}\n" for k, v in entry.items())
    path.write_text(f"[Desktop Entry]\nType=Application\n{body}")


def test_apps_are_found_like_a_launcher_finds_them(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "sys"))
    desktop(tmp_path / "home", "firefox", Name="Firefox", Icon="firefox")
    desktop(tmp_path / "sys", "firefox", Name="Old Firefox", Icon="firefox-old")
    desktop(tmp_path / "sys", "hidden", Name="Hidden", Icon="hidden", NoDisplay="true")
    desktop(tmp_path / "sys", "figma", Name="Figma", Icon="/opt/figma.png")
    desktop(tmp_path / "sys", "elden", Name="ELDEN RING", Icon="steam_icon_1245620")
    desktop(tmp_path / "home", "wine/Programs/bnet", Name="Battle.net", Icon="0A1B_Battle.net.0")
    assert icons.apps() == {
        "0A1B_Battle.net.0": "Battle.net",
        "firefox": "Firefox",
        "firefox-old": "Old Firefox",
        "steam_icon_1245620": "ELDEN RING",
    }


def test_apps_get_their_sign_or_a_glyph_of_their_own():
    installed = {"firefox": "Firefox", "steam_icon_1245620": "ELDEN RING", "btop": "btop++"}
    got = icons.assign({"places": set(), "mimetypes": set()}, installed)
    assert got["app"]["firefox"] == "fire"
    elden, btop = got["app"]["steam_icon_1245620"], got["app"]["btop"]
    assert elden.startswith("glyph-") and btop.startswith("glyph-") and elden != btop
    again = icons.assign({"places": set(), "mimetypes": set()}, dict(reversed(installed.items())))
    assert again["app"] == got["app"], "the same app keeps its glyph"
    assert got["status"]["dialog-warning"] == "warning"


def test_glyphs_are_not_shared_until_they_run_out():
    pool = len(icons._data()["glyphs"])
    picked = icons.glyphs([f"app {n}" for n in range(pool)])
    assert len(set(picked.values())) == pool
    more = icons.glyphs([f"app {n}" for n in range(pool + 5)])
    assert len(more) == pool + 5


def test_app_icons_can_be_left_out(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "sys"))
    desktop(tmp_path / "sys", "firefox", Name="Firefox", Icon="firefox")
    root = icons.render(palette.load("umber"), tmp_path / "t")
    assert (root / "96x96" / "apps" / "firefox.png").resolve().name == "athanor-app-fire.png"
    icons.render(palette.load("umber"), root, with_apps=False)
    assert not (root / "96x96" / "apps").exists()


def test_the_pool_leaves_word_signs_their_meaning():
    worded = {r.sign for r in icons.rules("words")}
    art = {icons.signs()[s] for s in worded}
    assert not any(icons.signs()[p] in art for p in icons.pool())
