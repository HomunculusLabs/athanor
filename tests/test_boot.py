import shutil

import pytest

from athanor import boot, palette


def test_cp437_has_256_glyphs():
    chars = boot.cp437_chars()
    assert len(chars) == 256
    assert chars[65] == "A"
    assert chars[219] == "█"
    assert chars[1] == "☺"


def test_vtrgb_is_three_rows_of_sixteen():
    rows = boot.vtrgb(palette.load("umber")).splitlines()
    assert len(rows) == 3
    assert all(len(r.split(",")) == 16 for r in rows)
    assert rows[0].split(",")[0] == "22"  # umber's ink, #16120e


def test_limine_block_is_fenced_and_hexless():
    block = boot.limine_block(palette.load("cinnabar"))
    lines = block.strip().splitlines()
    assert lines[0] == "# >>> athanor >>>"
    assert lines[-1] == "# <<< athanor <<<"
    assert "#" not in "".join(x for x in lines if not x.startswith("#"))
    palette_line = next(x for x in lines if x.startswith("term_palette:"))
    assert len(palette_line.split(": ")[1].split(";")) == 8


@pytest.mark.skipif(not shutil.which("magick"), reason="needs ImageMagick")
def test_vga_font_is_4096_bytes():
    try:
        ttf = boot.font_file(boot.FONTS["vga"])
    except boot.MissingFont:
        pytest.skip("PxPlus IBM VGA 8x16 not installed")
    data = boot.vga_font(ttf)
    assert len(data) == 256 * 16
    # The full block fills every row.
    assert data[219 * 16 : 220 * 16] == b"\xff" * 16
