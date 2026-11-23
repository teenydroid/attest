# attest

A stdlib-only Python 3 CLI that checks a challenge answer against the
challenge text before it goes out.

Agents that answer verification gates often fall back to a default
operation when the parse is unsure ("found no operator it trusted, so it
added the numbers"). The result is well-formed, confident, wrong.
`attest` scans the raw challenge text for evidence that attests the
operation the solver actually applied, and refuses to bless the answer
when the text does not back it.

## What it does

- Input: the raw challenge text, the operation the solver applied
  (operator plus operands, e.g. `multiply 32 by 4`), and optionally the
  answer it produced.
- It scans the text for an operator glyph or a phrase from a small
  bundled synonym list (`times`, `x`, `doubled`, `product`; `plus`,
  `sum`, `total`; `minus`, `difference`; `divided`, `per`) and reports
  every operation the text attests, with the matching snippet.
- Exit 0: the applied operation is attested and nothing competes with
  it. Ship the answer.
- Exit 1: the applied operation is NOT attested (the answer likely came
  from a fallback default; say `unknown` instead), OR the text attests
  two or more competing operations (the ambiguous-challenge case; a
  wrong guess spends the reply).
- Exit 2: usage error (unrecognised applied operation).

Glyph matching demands operator context, so prose hyphens
("well-known"), markdown bold and URLs do not count as operators, and
bare `of` attests multiply only where it means it ("half of 12"), not
after "sum of", "total of", "out of" and friends.

## Usage

```console
$ python3 attest.py --text "What is 32 times 4?" --operation "multiply 32 by 4" --answer 128
attests multiply: phrase 'times' near 'What is 32 times 4?'
applied operation 'multiply' is attested
$ echo $?
0

$ python3 attest.py --text "What is 32 times 4?" --operation "add 32 and 4" --answer 36
attests multiply: phrase 'times' near 'What is 32 times 4?'
applied operation 'add' should not ship: not attested; answer likely came from a fallback default
$ echo $?
1

$ python3 attest.py --text "the product of 3 and the sum of 2" --operation "add" --json
{
  "applied_operation": "add",
  ...
  "ambiguous": true,
  "verdict": "attested-but-ambiguous"
}
$ echo $?
1
```

Options:

- `--text` (required): the raw challenge text, or `-` to read stdin.
- `--operation` (required): what the solver applied, e.g.
  `multiply 32 by 4`. Synonyms are recognised (`times 32 by 4`,
  `sum of 5 and 3`, ...).
- `--answer`: the produced answer, echoed back verbatim in the report.
- `--json`: machine-readable report with `attested`, `ambiguous`,
  `attested_operations` (each with matching snippets) and `verdict`
  (`attested`, `attested-but-ambiguous`, `not-attested`).

## Tests

```console
$ python3 -m unittest test_attest -v
...
Ran 17 tests ... OK
```

No network, no accounts, no keys. Python 3 standard library only.
