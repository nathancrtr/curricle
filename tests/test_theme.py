"""The design system's invariants — the ones no renderer can check for us.

`theme.py` is data: two palettes and a pile of CSS. A mistake in it is
invisible — a token deleted from one palette only, a `var(--x)` with no `--x`
behind it, a color pair that quietly falls under its floor. Each of those
breaks a page months later, in one theme, in a PR that did not touch this
file. So the contract is asserted here directly.

The same mistakes are just as invisible in the *renderers*, which is why the
token and --faint guards below run over every stylesheet on the site (see
SHEETS), not only the shared base. Hand-verifying a renderer's slice at
review time is exactly the labor these guards exist to retire.

The contrast math is *computed*, not transcribed from DIRECTION.md: the
document's table is the claim, this is the check. The helper is validated
against two known WCAG values before it is trusted with the palette.
"""

import importlib
import pathlib
import re
import unittest
from typing import NamedTuple

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
    # the hub's hot row when it is also a milestone: the ring sits on the
    # green fill, not on --panel, so it is its own pairing
    ("--accent-strong", "--good-soft", 3.0),
    ("--faint", "--bg", 3.0),
]

# --------------------------------------------------------------------------
# Every stylesheet on the site, not only the shared one
# --------------------------------------------------------------------------

# Each renderer appends its own slice of CSS to the shared sheet, and that
# slice is where the novel token references and the novel color pairings
# actually live — currender's alone spends tokens forty times over. Guarding
# BASE_CSS only left the larger half of the site to be verified by hand at
# review time, so the sheets are registered here and every guard below runs
# over all of them.
#
# The CSS is read off the imported modules rather than out of their source
# text: composition has already happened at import time, so what we inspect
# is exactly what the browser receives. The one bit of surgery is isolating a
# module's *own* slice, by removing the shared prefix — and a slice that came
# out wrong is precisely the failure that would turn these guards into
# no-ops that still pass. Two things stop that: `themed` records how the
# sheet is composed and is asserted rather than sniffed, and `sentinel` names
# a selector that exists only in the module's own CSS, so an extraction that
# silently returned the wrong text fails loudly.


class Sheet(NamedTuple):
    module: str      # dotted path; imported, and how a failure names the sheet
    attr: str        # the module-level constant holding the composed sheet
    sentinel: str    # a selector found only in this module's own slice
    themed: bool     # composed through theme.style()?


SHEETS = [
    Sheet("curricle.hubrender", "STYLE", ".spine", themed=True),
    Sheet("curricle.currender", "STYLE", ".gloss-mark", themed=True),
    Sheet("curricle.resrender", "STYLE", ".why-mark", themed=True),
    Sheet("curricle.profilerender", "_STYLE", ".pendingbox", themed=True),
    # Not a renderer: the web app draws the front door itself, and that page
    # spends tokens like any other surface, so its sheet is guarded like any
    # other sheet.
    Sheet("curricle.webapp", "INDEX_STYLE", ".wordmark", themed=True),
]

SHARED_PREFIX = theme.TOKENS_CSS + theme.BASE_CSS


def _own_css(sheet: Sheet) -> str:
    """The CSS a renderer contributes itself, with the shared sheet removed."""
    css = getattr(importlib.import_module(sheet.module), sheet.attr)
    if not sheet.themed:
        return css
    head, found, own = css.partition(SHARED_PREFIX)
    if not found or head:
        raise AssertionError(
            f"{sheet.module}.{sheet.attr} no longer begins with "
            "theme.style()'s tokens+base; the own-CSS slice cannot be "
            "isolated, so the guards below would check the wrong text")
    return own


def _stylesheets() -> list[tuple[str, str]]:
    """(label, css) for the shared base and for each renderer's own slice."""
    return ([("theme.BASE_CSS", theme.BASE_CSS)]
            + [(s.module, _own_css(s)) for s in SHEETS])


_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _rules(css: str) -> list[tuple[str, str]]:
    """[(selector, declarations)] for every rule, at-rule blocks flattened."""
    css = _COMMENT.sub("", css)
    out, i = [], 0
    while (opened := css.find("{", i)) >= 0:
        depth, j = 1, opened + 1
        while depth:
            if j >= len(css):
                raise AssertionError(f"unbalanced braces after {css[i:opened]!r}")
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        selector, body = " ".join(css[i:opened].split()), css[opened + 1:j - 1]
        if "{" in body:                   # @media, @keyframes: recurse inside
            out.extend(_rules(body))
        else:
            out.append((selector, body))
        i = j
    return out


def _var_refs(css: str) -> list[tuple[str, str]]:
    """[(selector, token)] for every var() reference, so failures locate."""
    return [(selector, token)
            for selector, body in _rules(css)
            for token in re.findall(r"var\((--[a-z-]+)\)", body)]


def _faint_uses(css: str) -> set[tuple[str, str]]:
    """{(selector, property)} for every declaration painting with --faint."""
    return {(selector, decl.partition(":")[0].strip())
            for selector, body in _rules(css)
            for decl in body.split(";") if "var(--faint)" in decl}


def _describe(uses: set[tuple[str, str, str]]) -> str:
    """Spell a set of --faint uses out for a failure message."""
    return "; ".join(f"{label}: `{selector}` {{ {prop}:var(--faint) }}"
                     for label, selector, prop in sorted(uses))


# Every (stylesheet, selector, property) allowed to reach for --faint. It
# computes 4.27 on light --panel, under the 4.5 text floor, so it may color
# decoration and nothing a learner has to read. The property is part of the
# entry deliberately: `.step-row.done label` is copy in --muted whose
# strikethrough is drawn in --faint, and the entry licenses the strikethrough
# only. Adding a line here is a deliberate act: check the use is a mark, not
# copy. (Placeholder text is copy — both textareas take --muted.)
FAINT_DECORATIVE_USES = {
    ("theme.BASE_CSS", ".eyebrow .sep", "color"),            # the "·" between crumbs
    ("curricle.currender", ".dot", "border"),                # hollow ring: step to do
    ("curricle.currender", ".step-row.done label", "text-decoration-color"),
    ("curricle.hubrender", ".unit.done label", "text-decoration-color"),
    ("curricle.resrender", ".dot", "border"),                # same ring: unread
}


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


class TestEveryStylesheet(unittest.TestCase):
    """The two token guards, run over the base sheet and every renderer's."""

    def test_every_var_reference_resolves_in_both_palettes(self):
        # An undefined token renders as nothing at all: no error in the
        # console, no visual test that catches it, just a missing color.
        for label, css in _stylesheets():
            refs = _var_refs(css)
            self.assertTrue(refs, f"expected {label} to use tokens")
            for selector, token in refs:
                for name, palette in (("light", LIGHT), ("dark", DARK)):
                    if token not in palette:
                        self.fail(f"{label}: `{selector}` references {token}, "
                                  f"which the {name} palette does not define")

    def test_faint_colors_decoration_only(self):
        found = {(label, selector, prop)
                 for label, css in _stylesheets()
                 for selector, prop in _faint_uses(css)}
        if undeclared := found - FAINT_DECORATIVE_USES:
            self.fail("--faint (4.27 on light --panel, under the 4.5 text "
                      "floor) paints something not on the decorative "
                      "allowlist; copy takes --muted — " + _describe(undeclared))
        if stale := FAINT_DECORATIVE_USES - found:
            self.fail("allowlisted --faint uses that no longer exist; trim the "
                      "list so it stays reviewable — " + _describe(stale))

    def test_each_own_css_slice_is_real(self):
        # If the extraction ever comes back empty or holding the wrong text,
        # the guards above pass by checking nothing. The sentinel is the
        # proof they are reading the module they claim to read.
        for sheet in SHEETS:
            with self.subTest(module=sheet.module):
                own = _own_css(sheet)
                self.assertTrue(own.strip(), f"{sheet.module}: empty own CSS")
                if sheet.sentinel in SHARED_PREFIX:
                    self.fail(f"`{sheet.sentinel}` is in the shared sheet, so "
                              "it cannot witness this module's own slice — "
                              "pick another selector")
                self.assertTrue(
                    any(sheet.sentinel in selector for selector, _ in _rules(own)),
                    f"{sheet.module}: `{sheet.sentinel}` missing from the "
                    "extracted slice — the extraction is wrong, not the CSS")
                self.assertEqual(
                    [other for other, css in _stylesheets()
                     if other != sheet.module and sheet.sentinel in css], [],
                    f"`{sheet.sentinel}` is not unique to {sheet.module}, so "
                    "it cannot tell that slice from another's — pick another")

    def test_each_sheet_is_composed_the_way_it_declares(self):
        # `themed` is asserted, never inferred: a renderer that starts (or
        # stops) going through theme.style() fails here, where the registry
        # can be corrected, rather than silently changing what gets guarded.
        for sheet in SHEETS:
            with self.subTest(module=sheet.module):
                css = getattr(importlib.import_module(sheet.module), sheet.attr)
                if sheet.themed and not css.startswith(SHARED_PREFIX):
                    self.fail(f"{sheet.module} no longer composes through "
                              "theme.style(); own-CSS slicing is broken")
                if not sheet.themed and theme.BASE_CSS in css:
                    self.fail(f"{sheet.module} now carries the shared sheet: "
                              "mark it themed=True in SHEETS")

    def test_every_module_with_css_is_registered(self):
        # A fifth renderer that nobody adds to SHEETS is an unguarded
        # stylesheet, which is the whole defect this file is closing.
        package = pathlib.Path(theme.__file__).parent
        with_css = {f"curricle.{path.stem}" for path in package.glob("*.py")
                    if "var(--" in path.read_text(encoding="utf-8")}
        registered = {sheet.module for sheet in SHEETS} | {"curricle.theme"}
        if unguarded := with_css - registered:
            self.fail("modules spending theme tokens with no entry in SHEETS, "
                      "so nothing guards their CSS: " + ", ".join(sorted(unguarded)))
        if gone := registered - with_css - {"curricle.theme"}:
            self.fail("SHEETS entries whose module no longer carries CSS: "
                      + ", ".join(sorted(gone)))


class TestRuleParser(unittest.TestCase):
    """The parser the guards stand on: if it under-reads, they under-check."""

    def test_reads_selectors_declarations_and_nested_at_rules(self):
        rules = _rules("""
          /* a comment { with a brace } */
          .a,
          .b { color:var(--ink); }
          @media (max-width:620px) { .c { color:var(--muted); } }
        """)
        self.assertEqual(rules, [(".a, .b", " color:var(--ink); "),
                                 (".c", " color:var(--muted); ")])

    def test_refuses_unbalanced_braces(self):
        with self.assertRaises(AssertionError):
            _rules(".a { color:var(--ink);")

    def test_finds_what_the_guards_look_for(self):
        css = ".x { border:2px solid var(--faint); color:var(--nope); }"
        self.assertEqual(_var_refs(css), [(".x", "--faint"), (".x", "--nope")])
        self.assertEqual(_faint_uses(css), {(".x", "border")})


class TestBaseCss(unittest.TestCase):
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


def _decls(selector: str, css: str) -> dict[str, str]:
    """The declarations of one rule, by property."""
    for sel, body in _rules(css):
        if sel == selector:
            return {d.partition(":")[0].strip(): d.partition(":")[2].strip()
                    for d in body.split(";") if d.strip()}
    raise AssertionError(f"no rule `{selector}`")


def _px(value: str) -> float:
    return float(value.removesuffix("px"))


class TestEyebrowRhythm(unittest.TestCase):
    """The breadcrumb's spacing, which is three numbers that must agree.

    The crumb link is padded so its hover pill has a hit area, and the
    padding is then cancelled by negative margins so it never reaches the
    rhythm — the crumbs are meant to sit on one even beat, the flex gap. That
    held on the left only until #16: the uncompensated right padding stacked
    onto the gap and every subpage's first separator sat 20px out instead of
    8. Two numbers therefore have to track the gap, and neither is visible
    from the other's line, which is why they are asserted together here.
    """

    def setUp(self):
        self.eyebrow = _decls(".eyebrow", theme.BASE_CSS)
        self.crumb = _decls(".eyebrow a", theme.BASE_CSS)

    def test_the_padding_is_cancelled_on_both_sides(self):
        pad = self.crumb["padding"].split()
        self.assertEqual(len(pad), 2, "expected `padding:<v> <h>`")
        for side in ("margin-left", "margin-right"):
            self.assertEqual(_px(self.crumb[side]), -_px(pad[1]),
                             f"{side} does not cancel the horizontal padding, "
                             "so the crumb's text edge sits off the beat")

    def test_the_hover_pill_stops_where_the_next_crumb_starts(self):
        # Padding wider than the gap would put the pill under the separator
        # dot; narrower would leave the pill's cap short of the crumb it is
        # meant to fill the space beside. Equal is the one value that works.
        self.assertEqual(_px(self.crumb["padding"].split()[1]),
                         _px(self.eyebrow["gap"]))


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
