"""blockmd renders the corpus's block dialect — and only claims that much.

The census that sized this renderer (SPIKE: one-stop-shop) found the
lesson/task/question-bank corpus using exactly: ATX headings, paragraphs,
bullet lists with one nesting level, short ordered lists, blockquotes, one
pipe table, and a few indented code lines. These tests pin that dialect;
the corpus round-trip lives in test_corpus-style spirit but stays synthetic
here so the suite passes with the sibling repos absent.
"""

import unittest

from curricle.blockmd import block_html


class TestBlockMd(unittest.TestCase):
    def test_headings_and_paragraphs(self):
        out = block_html("# Title\n\nOne para\nsame para.\n\n## Sub\n\nTwo.")
        self.assertIn("<h1>Title</h1>", out)
        self.assertIn("<p>One para same para.</p>", out)
        self.assertIn("<h2>Sub</h2>", out)

    def test_inline_markup_reaches_blocks(self):
        out = block_html("A **bold** claim with `code` and *stress*.")
        self.assertIn("<b>bold</b>", out)
        self.assertIn("<code>code</code>", out)
        self.assertIn("<i>stress</i>", out)

    def test_lists_including_one_nested_level(self):
        out = block_html("- top\n  - inner\n- top two\n\n1. first\n2. second")
        self.assertEqual(out.count("<ul>"), 2)
        self.assertIn("<li>inner</li>", out)
        self.assertIn("<ol>", out)
        self.assertIn("<li>second</li>", out)
        # every opened list closes
        self.assertEqual(out.count("<ul>"), out.count("</ul>"))
        self.assertEqual(out.count("<ol>"), out.count("</ol>"))

    def test_bold_containing_italics(self):
        # Lesson guides write **"ask this, with *stress* inside"** — the
        # greedy-free bold pattern must close at the first `**`, not choke
        # on the inner single asterisks (found by the Unit 4 lesson).
        out = block_html('Ask: **"are they *not* relatives?"**')
        self.assertIn('<b>"are they <i>not</i> relatives?"</b>', out)

    def test_blockquote(self):
        out = block_html("> PAUSE. Ask the question.\n> Wait for it.")
        self.assertIn("<blockquote><p>PAUSE. Ask the question. "
                      "Wait for it.</p></blockquote>", out)

    def test_pipe_table(self):
        out = block_html("| a | b |\n|---|---|\n| 1 | 2 |\n")
        self.assertIn("<th>a</th>", out)
        self.assertIn("<td>2</td>", out)
        self.assertIn('class="tablewrap"', out)

    def test_fenced_code_is_escaped_verbatim(self):
        out = block_html("```\nx = a < b  # **not** markdown\n```")
        self.assertIn("a &lt; b", out)
        self.assertIn("**not**", out)      # inline markup must not run in code

    def test_html_in_prose_is_escaped(self):
        out = block_html("A line with <script>alert(1)</script> in it.")
        self.assertNotIn("<script>", out)

    def test_outside_the_dialect_degrades_to_paragraph_never_loss(self):
        # Setext headings aren't in the dialect; the text must still appear.
        out = block_html("Title\n=====")
        self.assertIn("Title", out)
