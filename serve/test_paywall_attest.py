"""The /attest grading resource: an unpaid call gets the frozen price and
the corpus count; a settled payment grades the body and writes one inflow
row, a `sale` with ref `x402:attest`; a body that can never grade is
refused before payment (nobody pays for a doomed call); a paid call whose
grading fails is recorded (the money settled) and answered with a
refundable 422, never a silent 200. The verdict is never free. Reuses the /stats harness: the core, the chain and the
facilitator are faked; Teeny's wallet signs nothing."""

from __future__ import annotations

import base64
import json
import unittest
from pathlib import Path

from wallet.support import OWN, USDC_MAINNET
from wallet.test_paywall import PRICE, TX, PaywallTest, header
from teeny_hands import hand
from teeny_hands.wallet import paywall

ATTEST_PRICE = 10_000  # evals/prices.toml: attest_grade_usdc = "0.01"
DESCRIPTION = "One challenge answer graded against the challenge text (attest corpus, 23 frames)"

TEXT = "What is 32 times 4?"
GOOD = {"text": TEXT, "operation": "multiply 32 by 4", "answer": "128"}
BAD = {"text": "What is 32 plus 4?", "operation": "multiply 32 by 4", "answer": "36"}


class AttestTest(PaywallTest):
    def post(self, body=None, payment=None):
        return paywall.handle("POST", "/attest", {"X-PAYMENT": payment} if payment else {}, body)

    def test_an_unpaid_call_gets_the_attest_price_and_the_corpus_count(self):
        status, _, body = self.post(GOOD)
        self.assertEqual(status, 402)
        (req,) = body["accepts"]
        self.assertEqual((req["scheme"], req["network"], req["maxAmountRequired"], req["payTo"], req["asset"]),
                         ("exact", "solana", str(ATTEST_PRICE), OWN, USDC_MAINNET))
        self.assertEqual(req["description"], DESCRIPTION)
        self.assertEqual(self.facilitator.calls, [])

    def test_an_unpaid_call_never_carries_the_verdict(self):
        status, _, body = self.post(GOOD)
        self.assertEqual(status, 402)
        self.assertNotIn("verdict", body)
        self.assertNotIn("attested_operations", body)

    def test_an_ungradeable_body_is_refused_for_free(self):
        for body in ({"text": "x"}, {"operation": "add"}, {"text": "", "operation": "add"},
                     {"text": "x" * 4001, "operation": "add"}, "not an object", None):
            status, _, resp = self.post(body)
            self.assertEqual(status, 402, body)
            self.assertIn("accepts", resp)
        self.assertEqual(self.facilitator.calls, [])

    def test_a_settled_payment_grades_and_records_the_sale(self):
        status, extra, body = self.post(GOOD, header())
        self.assertEqual(status, 200, body)
        self.assertEqual(body["verdict"], "attested")
        self.assertEqual(body["applied_operation"], "multiply")
        self.assertEqual(body["corpus_frames"], 23)
        self.assertIn("phrase 'times' near", body["attested_operations"]["multiply"][0])
        receipt = json.loads(base64.b64decode(extra["X-PAYMENT-RESPONSE"]))
        self.assertEqual(receipt["transaction"], TX)
        (row,) = self.inflows()
        self.assertEqual((row["signature"], row["category"], row["ref"], row["amount_raw"]),
                         (TX, "sale", "x402:attest", ATTEST_PRICE))
        # Teeny's wallet moved nothing and signed nothing.
        self.assertEqual(self.moved(), [])

    def test_a_wrong_operation_still_costs_and_still_says_not_attested(self):
        status, _, body = self.post(BAD, header())
        self.assertEqual(status, 200, body)
        self.assertEqual(body["verdict"], "not-attested")
        (row,) = self.inflows()
        self.assertEqual((row["category"], row["ref"]), ("sale", "x402:attest"))

    def test_a_paid_call_whose_grading_fails_is_refundable_not_silent(self):
        original = paywall.grade_request

        def broken(body):
            raise RuntimeError("grader exploded")

        paywall.grade_request = broken
        try:
            status, _, body = self.post(GOOD, header())
        finally:
            paywall.grade_request = original
        self.assertEqual(status, 422, body)
        self.assertEqual(body["payment"], TX)
        # The money arrived and is on the books; the 422 is what a person
        # refunds from.
        (row,) = self.inflows()
        self.assertEqual((row["category"], row["ref"]), ("sale", "x402:attest"))

    def test_get_on_attest_is_405(self):
        self.assertEqual(paywall.handle("GET", "/attest", {})[0], 405)

    def test_unknown_paths_stay_404(self):
        self.assertEqual(paywall.handle("POST", "/other", {}, GOOD)[0], 404)

    def test_stats_price_is_untouched(self):
        status, _, body = paywall.handle("GET", "/stats", {})
        self.assertEqual(status, 402)
        (req,) = body["accepts"]
        self.assertEqual(req["maxAmountRequired"], str(PRICE))


class AttestCorpusMirror(unittest.TestCase):
    """The vendored grader must keep reproducing the measured corpus truth
    (forgeloop's 23 frames, measured 2026-11-24): 14 of the 18 verified
    frames blocked, f01 blessed on 'total' alone (known bug), f07's
    rejected add blessed (known bug), f10/f13/f17 refused. If this drifts
    the grader changed and the corpus receipt is stale: stop and
    re-measure before selling."""

    def test_the_measured_truth_holds(self):
        from teeny_hands.wallet import attest

        with open(Path(__file__).resolve().parent / "fixtures" / "forgeloop-corpus.json") as f:
            frames = json.load(f)
        blocked, blessed, rejected_shipped = [], [], []
        for fr in frames:
            op = fr["op"] if fr["op"] != "-" else "add"
            report = attest.grade(fr["text"], op, fr.get("answer"))
            ships = report["verdict"] == "attested"
            if fr["outcome"] == "verified" and not ships:
                blocked.append(fr["id"])
            if fr["outcome"] == "refused" and ships:
                blessed.append(fr["id"])
            if fr["outcome"] == "rejected" and ships:
                rejected_shipped.append(fr["id"])
        self.assertEqual(sorted(blocked),
                         ["f02", "f03", "f04", "f05", "f06", "f08", "f09", "f11",
                          "f12", "f15", "f16", "f19", "f21", "f23"])
        self.assertEqual(blessed, ["f01"])
        self.assertEqual(rejected_shipped, ["f07"])


if __name__ == "__main__":
    unittest.main()
