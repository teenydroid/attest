"""Whether a repository's own policy forbids contributions made by an AI.

Teeny opens a pull request on somebody else's project only where it is
welcome, so this reads the files a project states its rules in and answers
conservatively: a sentence that names AI (or an LLM, a bot, generated code)
next to a prohibition forbids; a mention that is clearly a welcome (with or
without a disclosure rule, which Teeny's footer meets) allows; a mention it
cannot read either way is treated as forbidding. Silence is not a ban: a
project that says nothing about AI gets the rest of the rules (one open PR,
the daily cap, the disclosure footer).

This is a keyword-and-phrase heuristic, not a reading. It errs towards "no".

v2 (2026-11-26), two real-world false positives fixed:

1. self-process (kept from v1): a sentence describing the maintainers' own
   AI-assisted workflow is not a rule about outside contributors
   (modelcontextprotocol/servers, 2026-11-25).
2. requires (new): a sentence that states a REQUIREMENT for AI-authored
   contributions ("AI-authored PRs must fill in the metadata section")
   proves the channel exists, it does not refuse it. A project does not
   write submission requirements for contributions it bans. Requirement
   wording only counts when the sentence carries no prohibition keyword.
   (tinyhumansai/openhuman, 2026-11-26: CONTRIBUTING.md requires an
   "AI Authored PR Metadata" section and was still graded forbids.)
3. pointer (new): a sentence that names AI only to point at where rules
   live ("for coding-agent rules, see AGENTS.md") is not itself a rule.
   Pointers are resolved against the files already read: if the target
   file's own verdict is forbids, the pointer forbids too. A pointer to a
   file the gate never reads stays neutral; that residual blind spot is
   accepted and noted here rather than fetching arbitrary files, whose
   runtime-agent prose ("the agent's sandbox does not cost it write
   access") is not contribution policy and trips the prohibition keywords.
4. code blocks (new): fenced ``` blocks are stripped before sentence
   splitting; a repo-tree diagram naming a directory "agent" is not a
   policy sentence (openhuman's tree read "unclear" in v1).

Verdict rule is unchanged and still errs towards "no": any "forbids"
sentence forbids; any "unclear" sentence forbids; only policies whose
every AI-naming sentence reads allows/requires/pointer/self-process pass.
"""

from __future__ import annotations

import re
from typing import Callable

#: Where projects state their rules, in the order they are read.
POLICY_FILES = (
    "AI_POLICY.md",
    ".github/AI_POLICY.md",
    "CONTRIBUTING.md",
    ".github/CONTRIBUTING.md",
    "docs/CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    ".github/CODE_OF_CONDUCT.md",
)

# A sentence about machine-made contributions.
_AI = re.compile(
    r"\b(?:a\.?i\.?|ai[- ](?:generated|assisted|written|authored|tools?|agents?|models?)|artificial intelligence|"
    r"llms?|large language models?|gpt[-\w]*|chatgpt|copilot|claude|gemini|generative|"
    r"machine[- ]generated|auto[- ]?generated|generated (?:code|content|contributions?|pull requests?|prs?)|"
    r"bots?|bot[- ](?:generated|authored|made)|automated (?:contributions?|pull requests?|prs?|submissions?)|"
    r"(?:ai|autonomous|coding) agents?|coding agents?|remote[- ]agents?)\b",
    re.IGNORECASE,
)
# What a prohibition sounds like.
_NO = re.compile(
    r"\b(?:not|no|never|don'?t|do not|does not|doesn'?t|won'?t|will not|cannot|can'?t|must not|may not|"
    r"shall not|prohibit\w*|forbid\w*|banned|ban|bans|disallow\w*|reject\w*|refuse\w*|unacceptable|"
    r"not (?:accept|allow|permit|welcome)\w*|will be closed|be closed|closed without|zero[- ]tolerance)\b",
    re.IGNORECASE,
)
# What a welcome sounds like.
_YES = re.compile(
    r"\b(?:welcome[sd]?|allowed|permitted|is fine|are fine|ok(?:ay)?|accept(?:ed|s)?|encourage[sd]?|"
    r"may use|can use|feel free)\b",
    re.IGNORECASE,
)
# A requirement placed on AI-authored contributions: the channel exists.
_REQ = re.compile(
    r"\b(?:must|required|requires|require|should|shall include|include[sd]?|including|"
    r"fill in|checklist|metadata|disclos\w+|label(?:l?ed|ling)?|report)\b",
    re.IGNORECASE,
)
# A pointer to where the rules live, not a rule itself.
_PTR = re.compile(
    r"\b(?:see|see also|refer to|reference[sd]?|described in|defined in|documented in|"
    r"read|follow|details? in|rules? in|per)\b[^.!?]{0,200}?\b[\w./-]+\.(?:md|txt)\b",
    re.IGNORECASE,
)
# A sentence describing a project's own internal AI-assisted process: the
# maintainers' workflow, not a rule about outside contributors.
_SELF_PROCESS = re.compile(
    r"(?:\b(?:we|our|us|i)\b[^.!?]{0,120}?\b(?:develop\w*|build\w*|built|maintain\w*|"
    r"manage\w*|run\w*|review\w*|use\w*|work\w*|operat\w*|ship\w*|release\w*)\b"
    r"|\b(?:is|are|was|were|be|been|being)\b[^.!?]{0,80}?\b(?:developed|built|maintained|"
    r"managed|reviewed|operated|shipped|released|run)\b)"
    r"[^.!?]{0,120}?\b(?:with|using|through|via|by)\b.{0,120}?\b"
    r"(?:ai|llm|agent|bot|copilot|claude|gemini|gpt|generated|automation|prompt)\b",
    re.IGNORECASE,
)
# A sentence that addresses the contributor is never self-process, however it
# is phrased: rules about "your submissions" or "contributions" stay subject
# to the prohibition and unclear rules below.
_ADDRESSED = re.compile(
    r"\b(?:you|your|yours|contribut\w*|submission\w*|pull requests?|prs?)\b",
    re.IGNORECASE,
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n\s*\n|\n(?=\s*(?:[-*+]|\d+\.)\s)")
_FENCE = re.compile(r"```.*?```", re.DOTALL)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(_FENCE.sub(" ", text)) if s and s.strip()]


def _classify(sentence: str) -> str:
    if _NO.search(sentence):
        return "forbids"
    if _SELF_PROCESS.search(sentence) and not _ADDRESSED.search(sentence):
        return "self-process"
    if _REQ.search(sentence):
        return "requires"
    if _PTR.search(sentence):
        return "pointer"
    if _YES.search(sentence):
        return "allows"
    return "unclear"


def _file_verdict(files: dict[str, str], path: str) -> str:
    """The verdict on one file alone, pointers unresolved (no recursion)."""
    reads = [_classify(s) for s in _sentences(files[path]) if _AI.search(s)]
    if not reads:
        return "silent"
    if "forbids" in reads or "unclear" in reads:
        return "forbids"
    return "allows"


def assess(files: dict[str, str]) -> dict:
    """The verdict on the policy files found (path -> text):

      {"forbids_ai": bool, "verdict": "forbids" | "allows" | "silent",
       "files": [paths read], "evidence": [{"file", "sentence", "reads"}]}

    `reads` is "forbids", "requires", "pointer", "self-process", "allows"
    or "unclear" for each sentence that names AI; any "forbids" or
    "unclear" forbids. A "pointer" whose target file was read and itself
    forbids is re-graded "forbids"."""
    evidence: list[dict] = []
    for path, text in files.items():
        for sentence in _sentences(text):
            if not _AI.search(sentence):
                continue
            reads = _classify(sentence)
            evidence.append({"file": path, "sentence": sentence[:300], "reads": reads})
    # Resolve pointers against the files the gate actually read.
    for item in evidence:
        if item["reads"] != "pointer":
            continue
        target = re.search(r"\b([\w./-]+\.(?:md|txt))\b", item["sentence"], re.IGNORECASE)
        if not target:
            continue
        name = target.group(1).lstrip("./")
        for path in files:
            if path == item["file"] or path.endswith("/" + name) or path == name:
                if _file_verdict(files, path) == "forbids":
                    item["reads"] = "forbids"
                break
    if not evidence:
        verdict = "silent"
    elif any(item["reads"] == "forbids" for item in evidence):
        verdict = "forbids"
    elif any(item["reads"] == "unclear" for item in evidence):
        verdict = "forbids"
    else:
        verdict = "allows"
    return {
        "forbids_ai": verdict == "forbids",
        "verdict": verdict,
        "files": list(files),
        "evidence": [item for item in evidence if item["reads"] not in ("allows", "self-process", "requires", "pointer") or verdict == "allows"][:10],
    }


def read_policy(fetch: Callable[[str], str | None]) -> dict:
    """Reads every policy file `fetch(path)` returns, then `assess`es them."""
    found: dict[str, str] = {}
    for path in POLICY_FILES:
        text = fetch(path)
        if text is not None:
            found[path] = text
    return assess(found)
