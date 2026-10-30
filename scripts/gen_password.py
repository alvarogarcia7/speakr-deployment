#!/usr/bin/env python3
"""Print a random password: letters, digits and symbols, at least one of each.

Symbols are limited to characters that are safe to copy, paste and pass
through the shell (no quotes, $, backtick, backslash or spaces).
Usage: gen_password.py [length]   (default 24)
"""
import secrets
import string
import sys

SYMBOLS = "!#%+,-.:=?@^_~"
CLASSES = [string.ascii_letters, string.digits, SYMBOLS]


def generate(length=24):
    if length < len(CLASSES):
        raise ValueError("length too short")
    alphabet = "".join(CLASSES)
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if all(any(c in cls for c in pw) for cls in CLASSES):
            return pw


if __name__ == "__main__":
    print(generate(int(sys.argv[1]) if len(sys.argv) > 1 else 24))
