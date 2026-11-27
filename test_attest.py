import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout

import attest


def run_code(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = attest.main(argv)
    return code, out.getvalue()


class TestAttest(unittest.TestCase):

    def test_multiply_attested(self):
        code, _ = run_code(["--text", "What is 32 times 4?",
                            "--operation", "multiply 32 by 4", "--answer", "128"])
        self.assertEqual(code, 0)

    def test_glyph_attested(self):
        code, _ = run_code(["--text", "32 * 4 = ?", "--operation", "multiply"])
        self.assertEqual(code, 0)

    def test_fallback_add_not_attested(self):
        # solver fell back to add; text says 'times'
        code, out = run_code(["--text", "What is 32 times 4?", "--operation", "add"])
        self.assertEqual(code, 1)
        self.assertIn("not attested", out)
        self.assertIn("fallback default", out)

    def test_no_evidence_not_attested(self):
        code, out = run_code(["--text", "How many roads?", "--operation", "add"])
        self.assertEqual(code, 1)
        self.assertIn("no operation attested", out)

    def test_ambiguous_detected(self):
        # 'product' attests multiply, 'sum' attests add: competing operations
        code, out = run_code(["--text", "the product of 3 and the sum of 2",
                              "--operation", "add"])
        self.assertEqual(code, 1)
        self.assertIn("AMBIGUOUS", out)

    def test_json_report_shape(self):
        code, out = run_code(["--text", "32 times 4", "--operation", "multiply",
                              "--answer", "128", "--json"])
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertTrue(report["attested"])
        self.assertFalse(report["ambiguous"])
        self.assertEqual(report["verdict"], "attested")
        self.assertEqual(report["applied_operation"], "multiply")
        self.assertEqual(report["answer"], "128")
        self.assertIn("multiply", report["attested_operations"])

    def test_json_ambiguous_report(self):
        code, out = run_code(["--text", "the product of 3 and the sum of 2",
                              "--operation", "add", "--json"])
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertTrue(report["ambiguous"])
        self.assertEqual(report["verdict"], "attested-but-ambiguous")
        self.assertIn("add", report["attested_operations"])
        self.assertIn("multiply", report["attested_operations"])

    def test_json_unattested_report(self):
        code, out = run_code(["--text", "What is 32 times 4?",
                              "--operation", "add", "--json"])
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertFalse(report["attested"])
        self.assertEqual(report["verdict"], "not-attested")

    def test_synonym_in_applied_operation(self):
        code, _ = run_code(["--text", "the sum of 5 and 3",
                            "--operation", "plus 5 and 3"])
        self.assertEqual(code, 0)

    def test_divide_per(self):
        code, _ = run_code(["--text", "miles per hour", "--operation", "divide"])
        self.assertEqual(code, 0)

    def test_subtract_difference(self):
        code, _ = run_code(["--text", "find the difference between 9 and 4",
                            "--operation", "subtract"])
        self.assertEqual(code, 0)

    def test_bad_operation_is_usage_error(self):
        code, _ = run_code(["--text", "hi", "--operation", "frobnicate"])
        self.assertEqual(code, 2)

    def test_cli_exit_codes(self):
        p = subprocess.run([sys.executable, "attest.py", "--text", "32 times 4",
                            "--operation", "multiply"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        p = subprocess.run([sys.executable, "attest.py", "--text", "32 times 4",
                            "--operation", "add"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)

    def test_cli_json(self):
        p = subprocess.run([sys.executable, "attest.py", "--text", "32 times 4",
                            "--operation", "multiply", "--json"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        report = json.loads(p.stdout)
        self.assertEqual(report["verdict"], "attested")

    def test_prose_hyphen_is_not_subtract(self):
        # 'well-known' must not attest subtract
        code, _ = run_code(["--text", "a well-known fact", "--operation", "subtract"])
        self.assertEqual(code, 1)

    def test_sum_of_does_not_attest_multiply(self):
        code, _ = run_code(["--text", "the sum of 5 and 3", "--operation", "add"])
        self.assertEqual(code, 0)

    def test_stdin_text(self):
        code, _ = run_code(["--text", "-", "--operation", "multiply"])
        # no stdin wired in-process; argparse path only, expect clean exit 1
        self.assertIn(code, (1,))


if __name__ == "__main__":
    unittest.main()

class TestFalsifierSweep(unittest.TestCase):
    """the sweep mode: saved listings in, aggregate verdict out"""

    def test_load_listing_shapes(self):
        import os, tempfile, json as j
        import follower_falsifier as ff
        d = tempfile.mkdtemp()
        bare = os.path.join(d, "bare.json")
        j.dump([{"name": "x", "follower_count": 0, "comments_count": 0,
                 "posts_count": 0, "following_count": 0, "is_claimed": False,
                 "created_at": "2026-11-27T00:00:00Z", "last_active": None}], open(bare, "w"))
        rows, total = ff.load_listing(bare)
        self.assertEqual((len(rows), total), (1, 1))
        body = os.path.join(d, "body.json")
        j.dump({"followers": [{"name": "y"}], "total": 7}, open(body, "w"))
        rows, total = ff.load_listing(body)
        self.assertEqual((len(rows), total), (1, 7))

    def test_sweep_aggregate(self):
        import os, tempfile, json as j, io, contextlib
        import follower_falsifier as ff
        d = tempfile.mkdtemp()
        def shell(n): return {"name": n, "follower_count": 0, "comments_count": 0,
                              "posts_count": 1, "following_count": 0, "is_claimed": False,
                              "created_at": "2026-11-27T09:00:00Z", "last_active": "2026-11-27T09:00:00Z"}
        def real(n): return {"name": n, "follower_count": 40, "comments_count": 800,
                             "posts_count": 9, "following_count": 3, "is_claimed": True,
                             "created_at": "2026-06-01T00:00:00Z", "last_active": "2026-11-27T08:00:00Z"}
        j.dump({"followers": [shell("s-arch"), shell("t-oss"), real("h")], "total": 3},
               open(os.path.join(d, "farmy.json"), "w"))
        j.dump([real("a"), real("b")], open(os.path.join(d, "clean.json"), "w"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ff.sweep(d)
        out = buf.getvalue()
        self.assertIn("SWEEP FLAGGED", out)
        self.assertIn("farmy", out)
        self.assertIn("2 shell rows of 5", out)
