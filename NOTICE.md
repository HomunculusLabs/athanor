# Notices

## Plates

Gustave Doré's wood engravings for Tennyson's *Idylls of the King* (Moxon,
1868), Ariosto's *Orlando Furioso* (Hachette, 1879), Poe's *The Raven* (Harper,
1884) and Milton's *Paradise Lost* (Cassell, 1866). They're in the public
domain. The scans come from Wikimedia Commons and are committed in grayscale
under `src/athanor/plates/`. `plates.toml` lists the source of each one.

## Tarot

The Rider-Waite-Smith deck was drawn by Pamela Colman Smith and published by
Rider in 1909. It's in the public domain. The scans aren't in this repository.
`athanor cards fetch` downloads them from Wikimedia Commons. The card keywords
are condensed from A. E. Waite's *The Pictorial Key to the Tarot* (1910). That's
in the public domain too.

## Fonts

These are included in `fonts/`:

- Athanor, Vellum (Regular, Bold, Italic, Bold Italic) and Ossuary Display by
  Claude, 2026, dedicated to the public domain under
  [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)
- MEK Mono, copyright 2023 Michael Alexander (MEK.txt), included with the
  author's permission

`src/athanor/adwaita/` holds GTK's own stylesheets (Adwaita for GTK 3 and the
default theme for GTK 4), taken unchanged from GTK 3.24 and 4.22, copyright the
GTK Team, under the [LGPL 2.1 or later](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html).
`athanor transmute` recolours them for each scheme.

The installer downloads the rest:

- IBM VGA 8x16, Compaq Thin 8x16, Tandy 2000 and AT&T PC6300 from VileR's
  [Oldschool PC Font Pack](https://int10h.org/oldschool-pc-fonts/), CC BY-SA 4.0
- [Terminus](https://files.ax86.net/terminus-ttf/) by Dimitar Toshkov Zhekov, in
  the TTF build by Tilman Blumenbach, SIL Open Font License 1.1
- [Cozette](https://github.com/the-moonwitch/Cozette) by Samhain and
  contributors, MIT
- Jacquard 24 and IM Fell English from Google Fonts, SIL Open Font License 1.1
- [UW ttyp0](https://people.mpi-inf.mpg.de/~uwe/misc/uw-ttyp0/) by Uwe Waldmann,
  the 16px italic only, ttyp0 License
