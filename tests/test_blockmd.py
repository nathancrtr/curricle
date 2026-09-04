"""blockmd renders the corpus's block dialect — and only claims that much.

The census that sized this renderer (DIRECTION.md, "The material
contract") found the lesson/task/question-bank corpus using exactly: ATX
headings, paragraphs, bullet lists with one nesting level, short ordered
lists, blockquotes, one pipe table, and a few indented code lines. These
tests pin that dialect; the corpus round-trip lives in test_corpus-style
spirit but stays synthetic here so the suite passes with the sibling repos
absent.
"""

import unittest

from curricle.blockmd import block_html


class TestBlockMd(unittest.TestCase):
    def test_headings_and_paragraphs(self):
        out = block_html("# Title\n\nOne para\nsame para.\n\n## Sub\n\nTwo.")
        self.assertIn("<h1>Title</h1>", out)
        self.assertIn("<p>One para same para.</p>", out)
        self.assertIn('<h2 id="sub">Sub</h2>', out)

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


class TestChapterDialect(unittest.TestCase):
    """The three constructs chapters added (docs/chapter-pattern.md), each
    chosen because GitHub renders it too."""

    def test_footnotes_number_by_first_reference_and_gather_at_the_end(self):
        out = block_html("Claim.[^src] Again.[^src] Other.[^two]\n\n"
                         "[^two]: Second source.\n"
                         "[^src]: First source,\n    continued line.\n")
        self.assertIn('<sup class="fn" id="fnref-src"><a href="#fn-src">1</a></sup>', out)
        self.assertIn('<a href="#fn-two">2</a>', out)
        # definitions come out in reference order, not file order
        self.assertLess(out.index('id="fn-src"'), out.index('id="fn-two"'))
        self.assertIn("First source, continued line.", out)
        self.assertIn('class="fnback" href="#fnref-src"', out)
        self.assertIn('<section class="footnotes">', out)

    def test_footnote_syntax_inside_code_is_left_alone(self):
        out = block_html("Use `[^1]` for a note.[^1]\n\n[^1]: Yes.")
        self.assertIn("<code>[^1]</code>", out)
        self.assertEqual(out.count('class="fn"'), 1)

    def test_no_footnotes_means_no_footnote_section(self):
        self.assertNotIn("footnotes", block_html("Plain.\n\nText."))

    def test_callout_from_github_alert_syntax(self):
        out = block_html("> [!WARNING] Mind the gap\n> Body one.\n>\n> Body two.")
        self.assertIn('<div class="callout warning">', out)
        self.assertIn('<p class="callout-title">Mind the gap</p>', out)
        self.assertIn("<p>Body one.</p><p>Body two.</p>", out)
        # the default title is the kind
        self.assertIn('<p class="callout-title">Tip</p>',
                      block_html("> [!TIP]\n> Do this."))

    def test_blank_quote_line_splits_paragraphs_in_a_plain_blockquote(self):
        out = block_html("> One.\n>\n> Two.")
        self.assertIn("<blockquote><p>One.</p><p>Two.</p></blockquote>", out)

    def test_details_pass_through_with_markdown_inside(self):
        out = block_html("<details>\n<summary>Check yourself: **why?**</summary>\n\n"
                         "Because.\n\n- one\n\n</details>")
        self.assertIn("<details>\n<summary>Check yourself: <b>why?</b></summary>", out)
        self.assertIn("<p>Because.</p>", out)
        self.assertIn("<li>one</li>", out)
        self.assertTrue(out.rstrip().endswith("</details>"))
        # an unterminated collapsible still closes
        self.assertEqual(block_html("<details>\ntext").count("</details>"), 1)

    def test_other_html_stays_escaped(self):
        out = block_html("<summary>not inside details</summary>\n\n<div>x</div>")
        self.assertNotIn("<summary>", out)
        self.assertNotIn("<div>", out)

    def test_headings_get_slug_ids_and_duplicates_disambiguate(self):
        out = block_html("## Sub head!\n\n## Sub head!\n\n### Third & more")
        self.assertIn('<h2 id="sub-head">', out)
        self.assertIn('<h2 id="sub-head-2">', out)
        self.assertIn('<h3 id="third-more">', out)
