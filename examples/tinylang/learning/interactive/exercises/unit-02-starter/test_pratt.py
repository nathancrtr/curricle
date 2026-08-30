"""The failing tests for Unit 2. Make them pass.

Ordered easiest to hardest, so the suite doubles as a worklist: work top to
bottom and run it constantly. Everything asserts on the rendered
s-expression, never on your node objects, so the tree's shape stays yours.
"""

import unittest

from pratt import ParseError, parse_text


class LiteralsTest(unittest.TestCase):
    def test_a_bare_number(self):
        self.assertEqual(parse_text("42"), "42")

    def test_a_bare_identifier(self):
        self.assertEqual(parse_text("x"), "x")


class PrecedenceTest(unittest.TestCase):
    def test_multiplication_binds_tighter_than_addition(self):
        self.assertEqual(parse_text("1 + 2 * 3"), "(+ 1 (* 2 3))")

    def test_and_on_the_other_side_too(self):
        self.assertEqual(parse_text("1 * 2 + 3"), "(+ (* 1 2) 3)")

    def test_parentheses_override_precedence(self):
        self.assertEqual(parse_text("(1 + 2) * 3"), "(* (+ 1 2) 3)")

    def test_comparison_is_looser_than_arithmetic(self):
        self.assertEqual(parse_text("1 + 2 < 4"), "(< (+ 1 2) 4)")

    def test_equality_is_loosest(self):
        self.assertEqual(parse_text("1 < 2 == x"), "(== (< 1 2) x)")


class AssociativityTest(unittest.TestCase):
    def test_left_associative_subtraction(self):
        # The one that hides in every expression using only + and *.
        self.assertEqual(parse_text("1 - 2 - 3"), "(- (- 1 2) 3)")

    def test_left_associative_division(self):
        self.assertEqual(parse_text("8 / 4 / 2"), "(/ (/ 8 4) 2)")

    def test_right_associative_exponent(self):
        self.assertEqual(parse_text("2 ^ 3 ^ 4"), "(^ 2 (^ 3 4))")


class UnaryTest(unittest.TestCase):
    def test_unary_minus(self):
        self.assertEqual(parse_text("-x + 1"), "(+ (- x) 1)")

    def test_unary_minus_binds_tighter_than_multiplication(self):
        # Prefix operators need their own binding power, separate from the
        # infix table. If you reused the infix power for `-`, this is `(- (* x
        # y))` and the test tells you so.
        self.assertEqual(parse_text("-x * y"), "(* (- x) y)")


class ErrorTest(unittest.TestCase):
    def test_operator_where_an_operand_belongs(self):
        with self.assertRaises(ParseError):
            parse_text("1 + + 2")

    def test_unclosed_parenthesis(self):
        with self.assertRaises(ParseError):
            parse_text("(1 + 2")

    def test_trailing_tokens_after_a_complete_expression(self):
        # A parser that returns as soon as it has something valid will happily
        # ignore the `3` here. It should not.
        with self.assertRaises(ParseError):
            parse_text("1 + 2 3")


if __name__ == "__main__":
    unittest.main()
