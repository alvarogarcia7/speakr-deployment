#!/usr/bin/env python3
"""Turn spoken punctuation words in a transcript into symbols.

Reads text from stdin and writes the converted text to stdout:
    "this is a test period new line" -> "This is a test.\nNew line"

Rules: a spoken mark attaches to the word before it, the next word starts a
new sentence after . ? ! and "new line" becomes a line break.
"""
import re
import sys

# Longest phrases first so "question mark" wins over a bare word.
MARKS = [
    (r"question mark", "?"),
    (r"exclamation (?:mark|point)", "!"),
    (r"full stop", "."),
    (r"period", "."),
    (r"comma", ","),
    (r"semicolon", ";"),
    (r"colon", ":"),
    (r"open quote", '"'),
    (r"close quote", '"'),
]
NEW_LINE = r"new (?:line|paragraph)"
SENTENCE_END = {".", "?", "!"}

MARK_RE = re.compile(
    r"\s*\b(" + "|".join(p for p, _ in MARKS) + r"|" + NEW_LINE + r")\b\s*",
    re.IGNORECASE,
)
MARK_MAP = {p: s for p, s in MARKS}


def convert(text):
    out = []
    pos = 0
    for m in MARK_RE.finditer(text):
        out.append(text[pos:m.start()])
        word = m.group(1).lower()
        if re.fullmatch(NEW_LINE, word):
            out.append("\n")
        else:
            symbol = next(s for p, s in MARKS if re.fullmatch(p, word, re.IGNORECASE))
            out.append(symbol + " ")
        pos = m.end()
    out.append(text[pos:])
    result = "".join(out).strip()
    result = re.sub(r"[ \t]+([.,?!;:])", r"\1", result)
    result = re.sub(r"[ \t]*\n[ \t]*", "\n", result)
    # Capitalise the first letter of each sentence and the pronoun "I".
    result = re.sub(
        r"(^|[.?!]\s+|\n)([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        result,
    )
    result = re.sub(r"\bi\b", "I", result)
    return result


if __name__ == "__main__":
    sys.stdout.write(convert(sys.stdin.read()) + "\n")
