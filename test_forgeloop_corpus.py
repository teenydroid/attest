"""forgeloop's 23-frame corpus (posted 2026-11-23, comment 8f556091).

Grading plan (from the corpus author):
- verified rows are positives: attest must exit 0 (operation attested, unambiguous).
- f07 is rejected for add only; the right operation is unknown, so attest must
  NOT exit 0 on add (refuse to bless it).
- refused rows (f01, f10, f13, f17) must return unknown (non-zero), not pass.
- f01 and f17 are operand-ambiguous (23 or 323, 22 or 24); attest checks the
  operation, not the operands, so the operand question is out of scope.

Measured 2026-11-24: 14 of 18 good answers are blocked ("per <unit>" attests
divide, "total force" attests add over multiply, obfuscated words defeat
word-boundary matching, inflected verbs missing), and two unknown frames are
blessed on "total" alone (f01, f07). Those failures are marked expectedFailure
below: the day attest is fixed, they become unexpected successes and force a
look. Do not "fix" the expectations to match attest; they are the corpus
author's ground-truth outcomes.
"""

import json
import os
import unittest

from test_attest import run_code

HERE = os.path.dirname(os.path.abspath(__file__))


def _frames():
    with open(os.path.join(HERE, "fixtures-forgeloop.json")) as f:
        return json.load(f)


class TestForgeloopCorpus(unittest.TestCase):
    def test_verified_frames_ship(self):
        blocked = []
        for fr in _frames():
            if fr["outcome"] != "verified":
                continue
            code, _ = run_code(["--text", fr["text"],
                                "--operation", fr["op"],
                                "--answer", fr["answer"]])
            if code != 0:
                blocked.append(fr["id"])
        # 2026-11-24: 14 of 18 blocked. Tighten this number as attest improves;
        # 0 is the goal.
        self.assertEqual(len(blocked), 14,
                         "blocked good answers changed: %s" % blocked)

    @unittest.expectedFailure
    def test_f07_rejected_add_not_blessed(self):
        # KNOWN BUG (measured 2026-11-24): the gate rejected forgeloop's add
        # answer, but attest exits 0 on add because "total" vouches for it and
        # the standalone ^ between the operands is ignored.
        f07 = [fr for fr in _frames() if fr["id"] == "f07"][0]
        code, _ = run_code(["--text", f07["text"],
                            "--operation", "add",
                            "--answer", f07["answer"]])
        self.assertNotEqual(code, 0,
                            "f07: add was rejected by the gate but attest blesses it")

    def test_f17_refused_returns_unknown(self):
        f17 = [fr for fr in _frames() if fr["id"] == "f17"][0]
        code, _ = run_code(["--text", f17["text"],
                            "--operation", "add",
                            "--answer", f17["answer"]])
        self.assertNotEqual(code, 0, "f17: nobody knows the right operation")

    @unittest.expectedFailure
    def test_f01_refused_returns_unknown(self):
        # KNOWN BUG (measured 2026-11-24): exits 0 on "total" alone.
        f01 = [fr for fr in _frames() if fr["id"] == "f01"][0]
        code, _ = run_code(["--text", f01["text"],
                            "--operation", "add",
                            "--answer", f01["answer"]])
        self.assertNotEqual(code, 0, "f01: nobody knows the right operation")

    def test_f10_f13_refused_return_unknown(self):
        for fid in ("f10", "f13"):
            fr = [x for x in _frames() if x["id"] == fid][0]
            code, _ = run_code(["--text", fr["text"],
                                "--operation", "add",
                                "--answer", fr["answer"]])
            self.assertNotEqual(code, 0,
                                "%s: nobody knows the right operation" % fid)


if __name__ == "__main__":
    unittest.main()
