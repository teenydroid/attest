# serve/: the paid grading endpoint

This directory holds Teeny's proposal to sell attest gradings through the
paywall: `POST https://x402.<DEPLOY_DOMAIN>/attest`, priced per grading,
settled in USDC on Solana through the same x402 facilitator as `/stats`.

The paywall's paths are frozen (evals/frozen.txt: `hands/lib/teeny_hands/
wallet/`, `evals/**`, `deploy/**`, `bin/**`), so these files are a proposal
for the operator, not a landed change. Everything here was built and tested
against the real paywall code on 2026-11-26; `changes-full.patch` applies
the whole thing to the openhuman repo.

## The API

    POST /attest
    X-PAYMENT: <x402 v1 exact payment, base64 JSON>

    {"text": "<the raw challenge text>",
     "operation": "<what the solver applied, e.g. 'multiply 32 by 4'>",
     "answer": "<optional, reported back verbatim>"}

    402 -> {"accepts": [requirements]}   the frozen price and payTo
    200 -> {"verdict": "attested" | "attested-but-ambiguous" | "not-attested",
            "applied_operation": ..., "attested": bool, "ambiguous": bool,
            "attested_operations": {op: [evidence, ...]},
            "corpus_frames": 23, ...}

- An unpaid call gets the requirements and a free shape check of the body
  (nobody pays for a call that could never grade). The verdict is never
  free.
- A paid call is graded and recorded: one `x402_sales` row, one
  `wallet_inflows` row, category `sale`, ref `x402:attest`.
- A paid call whose grading fails is recorded (the money settled) and
  answered with a refundable 422, never a silent 200.
- GET on /attest is 405; unknown paths stay 404; /health stays free.

## Price

`attest_grade_usdc = "0.01"` in evals/prices.toml, beside
`stats_endpoint_usdc`. The meter prints `corpus_frames` per call, so a
buyer can check what the price bought.

## Files

- `changes-full.patch`  the whole change against openhuman main
  (2026-11-26): wallet/attest.py (new), wallet/paywall.py,
  tests/wallet/test_paywall_attest.py (new),
  tests/wallet/fixtures/forgeloop-corpus.json (new), evals/prices.toml,
  deploy/nginx/sites.teeny.enamakel.com.conf, bin/paywall, docs rows.
- `attest_lib.py`       the vendored grader as proposed
  (hands/lib/teeny_hands/wallet/attest.py).
- `test_paywall_attest.py`  the tests as proposed (9 harness tests plus
  AttestCorpusMirror).
- `forgeloop-corpus.json`  the corpus as proposed
  (hands/tests/wallet/fixtures/).

## Test status (2026-11-26)

- `python3 -m unittest discover -s wallet -t .` in hands/tests with the
  patch applied: 328 tests OK (28 in the new file; the 7 existing paywall
  tests untouched and green).
- The corpus mirror reproduces the measured truth exactly: 14 of the 18
  verified frames blocked, f01/f07 blessed (known bugs), f10/f13/f17
  refused.

## Deployment, after the operator applies the patch

1. nginx reload for the new `/attest` location (POST only).
2. `X402_ENDPOINT=1` unchanged; the compose service is unchanged.
3. First real paid call = the goal re-attempt's success condition
   (wallet_inflows at least 1 USDC on a fresh window counts every sale).

## The buyer-side blocker, named

The x402 fetch hand (the buyer side) refused its own vendor twice on
2026-11-26 (07:27 and 11:38 UTC): the exa vendor's payment challenge
arrives addressed on plain http while the request goes out https, so the
origin check rejects the challenge meant to authorize its payment. The fix
belongs in the x402 client's origin check (accept the challenge resource
when its host matches the requested url's host regardless of scheme, or
pin the https challenge url). That file is frozen too; the fix brief is
with the operator. Selling needs no fix; buyers on other stacks are
unaffected.
