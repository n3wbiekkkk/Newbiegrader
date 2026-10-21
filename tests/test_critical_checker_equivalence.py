"""Checker optimization must preserve formatting and tolerance contracts."""
import random
import re
import unittest

import grader


def decimal_contract(expected, actual, tol):
    pattern = re.compile(r"^-?\d+\.\d{2}$")
    el = expected.rstrip("\r\n").split("\n")
    al = actual.rstrip("\r\n").split("\n")
    if len(el) != len(al):
        return False
    for e, a in zip(el, al):
        et, at = e.split(), a.split()
        if len(et) != len(at):
            return False
        for u, v in zip(et, at):
            if not pattern.match(u) or not pattern.match(v):
                return False
            if abs(float(u) - float(v)) > tol:
                return False
    return True


class CheckerEquivalence(unittest.TestCase):
    def test_token_whitespace_and_mismatches(self):
        for whitespace in (chr(n) for n in range(0x110000) if chr(n).isspace()):
            answer = whitespace + 'ไทย' + whitespace + '123' + whitespace
            self.assertTrue(grader.check_token('ไทย 123', answer))
            self.assertFalse(grader.check_token('ไทย 124', answer))
        self.assertTrue(grader.check_token('a ' * 200000, 'a ' * 200000))
        self.assertFalse(grader.check_token('a ' * 200000, 'a ' * 199999 + 'b'))

    def test_decimal_equality_still_checks_format_and_tolerance(self):
        cases = ['', ' \n\t', '1.00', '-0.00', '١.٢٣', '３.００',
                 '1.00\n\n2.00\r\n', '9' * 400 + '.00',
                 '+1.00', '1', '1.0', '1.000', '.00', 'NaN', 'inf', '1.00\x00']
        for text in cases:
            for tol in (-1.0, 0.0, 1e-6, float('inf'), float('nan')):
                with self.subTest(text=text[:30], tol=tol):
                    self.assertEqual(grader.check_decimal2(text, text, tol),
                                     decimal_contract(text, text, tol))

    def test_decimal_line_lock_and_numeric_tolerance(self):
        for expected, actual, tol in [
            ('1.00\n2.00', '1.00 2.00', 1e-6),
            ('1.00 2.00', ' 1.00\t2.00\n', 1e-6),
            ('1.00', '1.01', .02), ('1.00', '1.01', .001),
            ('1.00\n\n2.00', '1.00\n2.00', 1e-6),
        ]:
            self.assertEqual(grader.check_decimal2(expected, actual, tol),
                             decimal_contract(expected, actual, tol))

    def test_seeded_differential_inputs(self):
        rng = random.Random(20261021)
        atoms = ['0', '-1', '1.00', '-0.00', '1.01', '', ' ', '\t', '\r', '\n',
                 '\x1c', '\u00a0', '\u3000', 'ไทย', '١.٢٣', '３.００', '\x00']
        for _ in range(4000):
            expected = ''.join(rng.choices(atoms, k=rng.randrange(9)))
            actual = expected if rng.random() < .5 else ''.join(rng.choices(atoms, k=rng.randrange(9)))
            self.assertEqual(grader.check_token(expected, actual), expected.split() == actual.split())
            tol = rng.choice((-1.0, 0.0, 1e-6, .02))
            self.assertEqual(grader.check_decimal2(expected, actual, tol),
                             decimal_contract(expected, actual, tol))


if __name__ == '__main__':
    unittest.main()
