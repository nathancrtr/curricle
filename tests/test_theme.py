"""The design system's invariants — the ones no renderer can check for us.

`theme.py` is data: two palettes and a pile of CSS. Nothing imports it yet,
so a mistake in it is invisible — a token deleted from one palette only, a
`var(--x)` with no `--x` behind it, a color pair that quietly falls under its
floor. Each of those breaks a page months later, in one theme, in a PR that
did not touch this file. So the contract is asserted here directly.

The contrast math is *computed*, not transcribed from DIRECTION.md: the
document's table is the claim, this is the check. The helper is validated
against two known WCAG values before it is trusted with the palette.
"""

import re
import unittest

from curricle import theme


def _palette(block: str) -> dict[str, str]:
    """Parse a `--name:value;` variable block into a dict (custom props only)."""
    out = {}
    for decl in block.split(";"):
        decl = decl.strip()
        if not decl.startswith("--"):
            continue                      # color-scheme, and any future plain prop
        name, _, value = decl.partition(":")
        out[name.strip()] = value.strip()
    return out


LIGHT = _palette(theme.LIGHT_VARS)
DARK = _palette(theme.DARK_VARS)


def _luminance(hex_color: str) -> float:
    """WCAG relative luminance of an #rrggbb color."""
    h = hex_color.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    r, g, b = linear
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two #rrggbb colors, (L1+.05)/(L2+.05)."""
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# The pairs DIRECTION.md commits to, with the floor each is held to: 4.5 for
# text, 3.0 for meaningful non-text (fills, the waypath's lit stone). --faint
# is decorative and sits below the text floor by design; it still has to
# clear the non-text floor to be seen at all.
CONTRAST_PAIRS = [
    ("--ink", "--bg", 4.5),
    ("--ink", "--panel", 4.5),
    ("--ink", "--chip", 4.5),
    ("--muted", "--bg", 4.5),
    ("--muted", "--panel", 4.5),
    ("--muted", "--chip", 4.5),
    ("--accent-text", "--bg", 4.5),
    ("--accent-text", "--panel", 4.5),
    ("--accent-text", "--accent-soft", 4.5),
    ("--good-text", "--panel", 4.5),
    ("--good-text", "--good-soft", 4.5),
    ("--warn-text", "--panel", 4.5),
    ("--warn-text", "--warn-soft", 4.5),
    ("--on-accent", "--accent-strong", 4.5),
    ("--accent", "--bg", 3.0),
    ("--accent", "--panel", 3.0),
    ("--accent-strong", "--stone", 3.0),
    ("--accent-strong", "--bg", 3.0),
    ("--faint", "--bg", 3.0),
]

# Selectors in BASE_CSS allowed to reach for --faint. It computes 4.27 on
# light --panel, under the 4.5 text floor, so it may color decoration and
# nothing a learner has to read. Adding to this list is a deliberate act:
# check the use is a mark, not copy. (Placeholder text is copy.)
FAINT_DECORATIVE_SELECTORS = {".eyebrow .sep"}


class TestPalettes(unittest.TestCase):
    def test_light_and_dark_define_the_same_tokens(self):
        # A token defined in one palette only breaks exactly one theme, and
        # only for whoever is running that theme — the failure a renderer
        # test would never see.
        self.assertEqual(sorted(LIGHT), sorted(DARK))
        self.assertEqual(len(LIGHT), 21)   # grow deliberately; renderers know these

    def test_each_palette_declares_its_color_scheme(self):
        # Without color-scheme the browser paints native controls and
        # scrollbars for the wrong theme.
        self.assertIn("color-scheme:light", theme.LIGHT_VARS)
        self.assertIn("color-scheme:dark", theme.DARK_VARS)

    def test_dark_is_served_by_preference_and_by_attribute(self):
        # Both entry points must carry the same block: the media query for
        # the system preference, [data-theme] so a toggle or a test can pin.
        self.assertIn("@media (prefers-color-scheme: dark)", theme.TOKENS_CSS)
        self.assertIn(":root:not([data-theme=light])", theme.TOKENS_CSS)
        self.assertIn(":root[data-theme=dark]", theme.TOKENS_CSS)
        self.assertEqual(theme.TOKENS_CSS.count(theme.DARK_VARS), 2)
        self.assertEqual(theme.TOKENS_CSS.count(theme.LIGHT_VARS), 1)


class TestBaseCss(unittest.TestCase):
    def test_every_var_reference_resolves_in_both_palettes(self):
        referenced = set(re.findall(r"var\((--[a-z-]+)\)", theme.BASE_CSS))
        self.assertTrue(referenced, "expected BASE_CSS to use tokens")
        self.assertEqual(sorted(referenced - set(LIGHT)), [])
        self.assertEqual(sorted(referenced - set(DARK)), [])

    def test_faint_colors_decoration_only(self):
        # Every rule reaching for --faint, by selector.
        users = {m.group(1).strip()
                 for m in re.finditer(r"([^{}]+)\{[^{}]*var\(--faint\)[^{}]*\}",
                                      theme.BASE_CSS)}
        self.assertEqual(users, FAINT_DECORATIVE_SELECTORS)

    def test_f_string_braces_all_resolved(self):
        # BASE_CSS is an f-string, so every literal brace is doubled in the
        # source; a stray pair reaching the output means a mangled escape.
        self.assertNotIn("{{", theme.BASE_CSS)
        self.assertNotIn("}}", theme.BASE_CSS)
        self.assertIn(theme.FONT_BODY, theme.BASE_CSS)

    def test_style_composes_tokens_then_base_then_extra(self):
        out = theme.style("  .own { color:var(--ink); }")
        self.assertLess(out.index("--accent-strong"), out.index(".panel"))
        self.assertTrue(out.endswith("  .own { color:var(--ink); }"))


class TestContrast(unittest.TestCase):
    def test_helper_matches_known_wcag_values(self):
        # Black on white is the maximum; #767676 is the canonical "exactly
        # passes 4.5 on white" gray. If these drift, nothing below is trusted.
        self.assertAlmostEqual(_contrast("#000000", "#FFFFFF"), 21.0, places=2)
        self.assertAlmostEqual(_contrast("#767676", "#FFFFFF"), 4.54, places=2)

    def test_every_committed_pair_clears_its_floor(self):
        for fg, bg, floor in CONTRAST_PAIRS:
            for name, palette in (("light", LIGHT), ("dark", DARK)):
                with self.subTest(pair=f"{fg} on {bg}", theme=name):
                    ratio = _contrast(palette[fg], palette[bg])
                    self.assertGreaterEqual(round(ratio, 2), floor)


class TestWaypathJs(unittest.TestCase):
    def test_waypath_js_is_percent_free(self):
        # It is pasted into a `SCRIPT % {...}` template: one stray percent
        # and every renderer that composes it raises at render time.
        self.assertNotIn("%", theme.WAYPATH_JS)
        self.assertEqual(theme.WAYPATH_JS % {}, theme.WAYPATH_JS)

    def test_base_css_is_not_percent_formattable(self):
        # The other half of the same hazard, asserted so the reason is on
        # record: BASE_CSS carries literal percents (100%, -50%, keyframe
        # stops) and must be concatenated, never %-formatted.
        with self.assertRaises(ValueError):
            theme.BASE_CSS % {}


class TestCopyHelpers(unittest.TestCase):
    def test_strips_the_corpus_milestone_pictograph(self):
        self.assertEqual(
            theme.strip_leading_pictograph(
                "\U0001F4EE Contact milestone: INTF + McCollum emails sent"),
            "Contact milestone: INTF + McCollum emails sent")

    def test_leaves_prose_emoji_alone(self):
        self.assertEqual(theme.strip_leading_pictograph("Email \U0001F4EE sent"),
                         "Email \U0001F4EE sent")

    def test_leaves_letters_and_combining_marks_alone(self):
        # The character class must not be able to eat content: no ASCII, and
        # no combining mark (a leading one belongs to the word after it).
        for label in ("Unit 3 · Local stemmata", "éclair", "אָ",
                      "— an em-dash lede"):
            self.assertEqual(theme.strip_leading_pictograph(label), label)

    def test_greeting_follows_the_clock(self):
        self.assertEqual(theme.greeting(5), "Good morning")
        self.assertEqual(theme.greeting(11), "Good morning")
        self.assertEqual(theme.greeting(12), "Good afternoon")
        self.assertEqual(theme.greeting(17), "Good afternoon")
        self.assertEqual(theme.greeting(18), "Good evening")
        self.assertEqual(theme.greeting(4), "Good evening")


if __name__ == "__main__":
    unittest.main()
