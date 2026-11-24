"""MicroPython's str lacks some CPython methods: the tests run on CPython, so a call to one passes here and fails
on the Pico ('str' object has no attribute 'isalnum': turning on Online backup with an invite code, v1.3.32-33)."""
import os
import re
import unittest

FW = os.path.join(os.path.dirname(__file__), '..', 'firmware')
MISSING = ('isalnum', 'isdecimal', 'isnumeric', 'isidentifier', 'isprintable', 'casefold', 'removeprefix',
           'removesuffix', 'swapcase', 'title', 'zfill', 'expandtabs', 'ljust', 'rjust', 'maketrans', 'translate', 'format_map', 'bit_length')


class UpyStr(unittest.TestCase):
    def test_no_missing_str_methods(self):
        bad = []
        for n in sorted(os.listdir(FW)):
            if n.endswith('.py'):
                with open(os.path.join(FW, n)) as f:
                    for i, line in enumerate(f, 1):
                        for m in re.findall(r'\.(%s)\(' % '|'.join(MISSING), line.split('#')[0]):
                            bad.append('%s:%d .%s()' % (n, i, m))
        self.assertEqual(bad, [])


if __name__ == '__main__':
    unittest.main()
