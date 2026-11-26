# gate-fix v2: the AI-contribution gate, two real-world false positives fixed

The contributing gate (`hands/lib/teeny_hands/gh/contributing.py`) decides
whether a project welcomes AI-authored contributions before any pull request
or issue is opened on it. v1 errs towards "no": a sentence that names AI with
neither a prohibition nor a welcome keyword ("unclear") forbids the whole
repo. That caught two real projects that accept AI contributions:

1. **modelcontextprotocol/servers** (2026-11-25): a sentence describing the
   maintainers' own AI-assisted workflow was graded as a rule about outside
   contributors. Fixed in v1 already: the `self-process` class.
2. **tinyhumansai/openhuman** (2026-11-26): CONTRIBUTING.md *requires* an
   "AI Authored PR Metadata" section for AI-authored PRs (the PR template
   repeats it), which proves the channel exists, and the gate still graded
   the repo "forbids" on five "unclear" sentences. This blocked Teeny's
   openhuman defect filings (goal #2, deadline 2026-11-30).

## What v2 changes

Verdict rule unchanged: still errs towards "no". Three new sentence classes,
so requirement-and-pointer prose stops reading as refusal:

- `requires`: a requirement placed on AI-authored contributions ("AI-authored
  PRs must fill in the metadata section") proves the channel exists. Only
  counts when the sentence carries no prohibition keyword.
- `pointer`: "for coding-agent rules, see AGENTS.md" is resolved against the
  files the gate read: a pointer into a forbidding target forbids, a pointer
  to an unread file stays neutral (residual blind spot, accepted and noted).
- code blocks are stripped before sentence splitting (a repo-tree diagram
  naming an `agent/` directory is not a policy sentence).

## Files

- `contributing.py`: the patched module, drop-in for
  `hands/lib/teeny_hands/gh/contributing.py` (197 lines, stdlib only).
- `test_gate_v2.py`: self-contained tests, run `python3 test_gate_v2.py`
  in this directory. No network, no hands checkout needed.
- `corpus/openhuman/`: the four files the gate reads for the openhuman
  case, fetched from main on 2026-11-26 (CONTRIBUTING.md 22,185 bytes,
  CODE_OF_CONDUCT.md 3,203 bytes, plus AGENTS.md and the PR template for
  reference).

## Test evidence (2026-11-26)

- openhuman corpus: v1 forbids -> v2 allows (evidence: 1 pointer + 3 requires).
- self-process sentence: allows.
- 5 synthetic real bans: still forbid.
- requirement + ban in one sentence: still forbids.
- pointer into a forbidding target: forbids. Pointer to an unread file:
  sentence-level neutral (documented blind spot).
- code-block tree: silent.
- hands case compatibility (`hands/tests/gh/test_reads.py` strings): 9/9.

## How to apply

Replace `hands/lib/teeny_hands/gh/contributing.py` with `contributing.py`
and run the hands gate tests. After it lands, a fresh gate read of
tinyhumansai/openhuman grades "allows" and the openhuman issue filings
unblock before the 2026-11-30 deadline.

## Falsifier

If the live gate, after this patch, still grades openhuman "forbids", this
case is wrong and the wall is real.
