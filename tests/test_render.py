import unittest

from curricle.inlinemd import inline_html


class TestInlineMd(unittest.TestCase):
    def test_plain_text_escaped(self):
        self.assertEqual(inline_html("a < b & c"), "a &lt; b &amp; c")

    def test_code_span(self):
        self.assertEqual(inline_html("run `python -m x`"),
                         "run <code>python -m x</code>")

    def test_code_protects_contents(self):
        # Asterisks and brackets inside code must not become formatting.
        self.assertEqual(inline_html("`**kwargs` and `[a](b)`"),
                         "<code>**kwargs</code> and <code>[a](b)</code>")

    def test_external_link_gets_new_tab(self):
        self.assertEqual(
            inline_html("[docs](https://example.org/x)"),
            '<a href="https://example.org/x" target="_blank" rel="noopener">docs</a>')

    def test_relative_link_plain(self):
        self.assertEqual(inline_html("[readme](../README.md)"),
                         '<a href="../README.md">readme</a>')

    def test_bold_then_italic(self):
        self.assertEqual(inline_html("**W&G** and *Ausgangstext*"),
                         "<b>W&amp;G</b> and <i>Ausgangstext</i>")

    def test_mixed_row_content(self):
        out = inline_html("Read [W&G](https://x.org) ch. 1; `parse()` — the *initial* text.")
        self.assertIn('<a href="https://x.org" target="_blank" rel="noopener">W&amp;G</a>', out)
        self.assertIn("<code>parse()</code>", out)
        self.assertIn("<i>initial</i>", out)


if __name__ == "__main__":
    unittest.main()
