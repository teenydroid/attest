#!/usr/bin/env python3
"""attest: check a challenge answer against the challenge text.

Scans the raw challenge text for evidence that attests the operation the
solver applied (an operator glyph or a phrase from a bundled synonym list)
and reports every operation the text attests.

Exit codes:
  0  the applied operation is attested and the text attests nothing else
  1  the applied operation is NOT attested, OR the text attests two or
     more competing operations (ambiguous challenge). Either way the
     answer likely came from a fallback default or a coin flip; the
     solver should say 'unknown' instead of shipping a confident wrong
     answer
  2  usage error

No network, no accounts, no keys. Stdlib only.
"""

import argparse
import json
import re
import sys

# Bare "of" attests multiply ("half of 12", "15% of 80") but not right
# after these words, where it belongs to another construction ("sum of",
# "out of 100"). The exclusion spans any whitespace, so "sum\nof" and
# "sum  of" are caught too; a fixed-width lookbehind cannot do that.
OF_EXCLUDE = re.compile(
    r"\b(sum|total|product|difference|average|combined|out|kind|type|lot|"
    r"sort|one|some|all|most|many|number|group|set|list|part|instead|"
    r"because|course)\s+$", re.IGNORECASE)

# operation -> glyph patterns (label -> regex) and cue phrases.
# Glyph patterns demand operator context so prose hyphens, markdown
# bold and URLs do not count as operators.
OPERATIONS = {
    "multiply": {
        "glyphs": {"*": r"\d[ \t]*\*[ \t]*\d|[^\s][ \t]\*[ \t]", "×": r"×", "x": r"\bx\b"},
        "phrases": ["times", "multiplied by", "multiply", "product",
                    "doubled", "tripled", "quadrupled", "of"],
    },
    "add": {
        "glyphs": {"+": r"\+", "＋": r"＋"},
        "phrases": ["plus", "sum", "total", "add", "added to",
                    "combined", "altogether"],
    },
    "subtract": {
        "glyphs": {"-": r"\d\s*-\s*\d", "−": r"−", "–": r"\d\s*–\s*\d"},
        "phrases": ["minus", "difference", "subtract", "less",
                    "fewer", "remaining"],
    },
    "divide": {
        "glyphs": {"/": r"\d\s*/\s*\d", "÷": r"÷"},
        "phrases": ["divided by", "divided", "divide", "per", "split",
                    "shared equally", "quotient", "ratio"],
    },
}

AMBIGUOUS_EXIT = 1  # same exit as unattested: the answer must not ship


def _context(text, start, end, width=24):
    lo, hi = max(0, start - width), min(len(text), end + width)
    snippet = text[lo:hi].replace("\n", " ").strip()
    return snippet if lo == 0 else "..." + snippet


def find_evidence(text):
    """Return {operation: [evidence strings]} for every attested operation."""
    found = {}
    for op, spec in OPERATIONS.items():
        hits = []
        for label, pattern in spec["glyphs"].items():
            for m in re.finditer(pattern, text, re.IGNORECASE):
                hits.append("glyph %r near %r" % (label, _context(text, m.start(), m.end())))
        for phrase in spec["phrases"]:
            if phrase == "of":
                for m in re.finditer(r"\bof\b", text, re.IGNORECASE):
                    if OF_EXCLUDE.search(text[:m.start()]):
                        continue
                    hits.append("phrase 'of' near %r" % _context(text, m.start(), m.end()))
                continue
            pattern = phrase if phrase.startswith("(?") else r"\b" + re.escape(phrase) + r"\b"
            for m in re.finditer(pattern, text, re.IGNORECASE):
                hits.append("phrase %r near %r" % (phrase.replace("\\b", "").strip(),
                                                   _context(text, m.start(), m.end())))
        if hits:
            found[op] = hits
    return found


SYNONYMS = {"times": "multiply", "product": "multiply",
            "sum": "add", "total": "add", "plus": "add",
            "minus": "subtract", "difference": "subtract",
            "divided": "divide", "per": "divide", "quotient": "divide"}


def recognise_applied(operation):
    """Map the solver's applied-operation string to a known operation.
    Whole tokens only: operand words like "added" must not select add
    over subtract."""
    words = re.findall(r"[a-z]+", operation.strip().lower())
    for word in words:
        if word in OPERATIONS:
            return word
    for word in words:
        if word in SYNONYMS:
            return SYNONYMS[word]
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="attest",
        description="Check a challenge answer's operation against the challenge text.")
    parser.add_argument("--text", required=True,
                        help="raw challenge text (or '-' to read stdin)")
    parser.add_argument("--operation", required=True,
                        help="operation the solver applied, e.g. 'multiply 32 by 4'")
    parser.add_argument("--answer", default=None,
                        help="the answer produced (reported back verbatim)")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="emit a JSON report")
    args = parser.parse_args(argv)

    text = args.text
    if text == "-":
        text = sys.stdin.read()

    applied_op = recognise_applied(args.operation)
    if applied_op is None:
        print("attest: cannot recognise the applied operation: %r" % args.operation,
              file=sys.stderr)
        return 2

    found = find_evidence(text)
    attested = applied_op in found
    ambiguous = len(found) > 1

    report = {
        "applied_operation": applied_op,
        "applied_raw": args.operation,
        "answer": args.answer,
        "attested": attested,
        "ambiguous": ambiguous,
        "attested_operations": found,
        "verdict": (
            "attested" if attested and not ambiguous else
            "attested-but-ambiguous" if attested else
            "not-attested"),
    }
    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        for op in sorted(found):
            print("attests %s: %s" % (op, "; ".join(found[op])))
        if not found:
            print("no operation attested by the text")
        if ambiguous:
            print("AMBIGUOUS: text attests %d competing operations" % len(found))
        if attested and not ambiguous:
            print("applied operation %r is attested" % applied_op)
        else:
            print("applied operation %r should not ship: %s" % (
                applied_op,
                "text attests competing operations" if ambiguous
                else "not attested; answer likely came from a fallback default"))

    return 0 if (attested and not ambiguous) else AMBIGUOUS_EXIT


if __name__ == "__main__":
    sys.exit(main())
