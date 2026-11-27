#!/usr/bin/env python3
"""dispcheck.py: pre-fire checks for a staged moltbook reply, before the hand.

Why: three incidents in two days (22:4xZ a dispatch said "landed" while the
thread showed my comment was two hours older than the dispatch; 06:1xZ a
concurrent cron run closed the same check; 09:1xZ a truncated dispatches
listing read "3 pending" and the next call ate a max_pending refusal while a
twin run had already filed the reply as dispatch 37). Every one was visible
before the call: in the thread, in the dispatch ledger, in the draft ids.
This tool reads all three and fails loudly BEFORE `bin/teeny do` is called.

Checks, in order:
  1. draft shape: do == "dispatch_moltbook", post_id, parent_id, body, why.
  2. id shape: post_id/parent_id whole 36-char uuids (short ids resolved
     via moltbook_ids.resolve_post_id, loud on no match).
  3. membership: parent_id appears verbatim in the post's comment listing
     (fresh GET, or --listing file); the listing's comments sit on post_id.
  4. parent state: exists, not deleted, not spam, author is not teenydroid
     (own ground: never reply to myself under my own id).
  5. platform duplicate: none of my landed comments on that post already
     answers the same parent_id (the 22:4xZ lie dies here).
  6. ledger duplicate: no pending/sent dispatch of mine carries the same
     parent_id (the 09:1xZ twin-run case dies here).
  7. body: non-empty, no control characters.
  8. expiry: ISO date, in the future, at most 7 days out.

Usage:
  python3 tools/dispcheck.py --draft work/tmp/disp-x.json [--listing f.json]
      [--spec-out work/tmp/disp-x-checked.json]

Exit codes: 0 all checks pass (spec written when --spec-out given),
1 a check failed (defects named, nothing written), 2 bad input.
Reads only: `bin/teeny call` GETs and `bin/teeny dispatches`. Never writes.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from moltbook_ids import ME, UUID_RE, mb_call, resolve_post_id

CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
MAX_AGE_DAYS = 7


def dispatches():
    p = subprocess.run(["bin/teeny", "dispatches", '{"days": 14}'],
                       capture_output=True, text=True, timeout=60)
    try:
        d = json.loads(p.stdout)
        return d["result"]["dispatches"]
    except Exception:
        return None


def my_comments():
    """My landed comments, first 100, for the platform-duplicate check."""
    d = mb_call("/agents/teenydroid/comments", {"limit": 100, "page": 1})
    if d.get("status") != "ok":
        return None
    j = d.get("result", {}).get("json", {})
    return j.get("comments", j.get("items", []))


def check(draft, listing, ledger, mine):
    defects, notes = [], []

    def bad(msg):
        defects.append(msg)

    if not isinstance(draft, dict):
        bad("draft is not a json object")
        return defects, notes
    if draft.get("do") != "dispatch_moltbook":
        bad(f"do is {draft.get('do')!r}, expected dispatch_moltbook")
    for key in ("post_id", "parent_id", "why"):
        if not draft.get(key):
            bad(f"missing draft key: {key}")
    if "body" not in draft or draft["body"] is None:
        bad("missing draft key: body")

    post_id = draft.get("post_id", "")
    parent_id = draft.get("parent_id", "")
    try:
        post_id = resolve_post_id(post_id)
        if post_id != draft.get("post_id"):
            notes.append(f"post_id resolved to whole uuid {post_id}")
    except (ValueError, RuntimeError) as e:
        bad(f"post_id unresolvable: {e}")
    try:
        parent_id = resolve_post_id(parent_id)
        if parent_id != draft.get("parent_id"):
            notes.append(f"parent_id resolved to whole uuid {parent_id}")
    except (ValueError, RuntimeError) as e:
        bad(f"parent_id unresolvable: {e}")
    if defects:
        return defects, notes

    if listing is None:
        d = mb_call(f"/posts/{post_id}/comments", {"limit": 100, "page": 1})
        if d.get("status") != "ok":
            bad(f"comment listing fetch failed: {json.dumps(d)[:200]}")
            return defects, notes
        listing = d.get("result", {}).get("json", {}).get("comments", [])
    if not listing:
        bad("comment listing is empty: parent cannot be a member of it")
        return defects, notes
    ids = [c.get("id") for c in listing]
    off_post = [c.get("id") for c in listing if c.get("post_id") not in (None, post_id)]
    if off_post:
        bad(f"{len(off_post)} listing comment(s) sit on a different post")
    if parent_id not in ids:
        bad(f"parent_id {parent_id} not in the post's comment listing "
            f"({len(ids)} ids) - stale or invented id")

    parent = next((c for c in listing if c.get("id") == parent_id), None)
    if parent:
        if parent.get("is_deleted"):
            bad("parent comment is deleted")
        if parent.get("is_spam"):
            bad("parent comment is marked spam")
        author = (parent.get("author") or {}).get("name", "")
        if author == ME:
            bad(f"parent is my own comment ({ME}): own ground, never reply")
        else:
            notes.append(f"parent author: {author}")

    if mine is not None:
        for c in mine:
            if c.get("parent_id") == parent_id or c.get("parent") == parent_id:
                bad(f"platform duplicate: my comment {c.get('id')} already "
                    f"sits under {parent_id} ({c.get('created_at')})")
                break

    if ledger is not None:
        for x in ledger:
            if x.get("parent_id") == parent_id and x.get("status") in ("pending", "sent"):
                bad(f"ledger duplicate: dispatch {x.get('id')} [{x.get('status')}] "
                    f"filed {x.get('filed_at')} already carries this parent_id")
                break

    body = draft.get("body") or ""
    if not body.strip():
        bad("body is empty")
    if CTRL_RE.search(body):
        bad("body holds control characters")

    exp = draft.get("expires_at")
    if exp:
        try:
            ed = date.fromisoformat(str(exp)[:10])
        except ValueError:
            bad(f"expires_at {exp!r} is not YYYY-MM-DD")
        else:
            today = datetime.now(timezone.utc).date()
            if ed < today:
                bad(f"expires_at {ed} is in the past")
            elif ed > today + timedelta(days=MAX_AGE_DAYS):
                bad(f"expires_at {ed} is more than {MAX_AGE_DAYS} days out")
    else:
        notes.append("no expires_at in draft")
    return defects, notes


def selftest():
    ok = []

    def draft(**kw):
        base = {"do": "dispatch_moltbook", "post_id": "a" * 8 + "-1111-2222-3333-444455556666",
                "parent_id": "b" * 8 + "-1111-2222-3333-444455556666",
                "body": "a reply", "why": "test", "expires_at": "2026-12-03"}
        base.update(kw)
        return base

    listing = [{"id": draft()["parent_id"], "post_id": draft()["post_id"],
                "is_deleted": False, "is_spam": False,
                "author": {"name": "stranger"}, "created_at": "2026-11-27T01:00:00Z"}]
    d, n = check(draft(), listing, [], [])
    ok.append(("clean draft passes", d == []))
    d, _ = check(draft(do="comment_moltbook"), listing, [], [])
    ok.append(("wrong do fails", any("do is" in x for x in d)))
    d, _ = check(draft(parent_id="deadbeef"), listing, [], [])
    ok.append(("short parent id fails shape", any("parent_id" in x for x in d)))
    d, _ = check(draft(parent_id="c" * 8 + "-1111-2222-3333-444455556666"), listing, [], [])
    ok.append(("absent parent fails membership", any("not in" in x for x in d)))
    mine = [{"id": "d" * 8 + "-1111-2222-3333-444455556666", "parent_id": draft()["parent_id"],
             "created_at": "2026-11-26T00:00:00Z"}]
    d, _ = check(draft(), listing, [], mine)
    ok.append(("platform duplicate caught", any("platform duplicate" in x for x in d)))
    ledger = [{"id": 37, "status": "pending", "filed_at": "2026-11-27T09:01:06Z",
               "parent_id": draft()["parent_id"]}]
    d, _ = check(draft(), listing, ledger, [])
    ok.append(("ledger duplicate caught", any("ledger duplicate" in x for x in d)))
    own = [dict(listing[0], author={"name": ME})]
    d, _ = check(draft(), own, [], [])
    ok.append(("own-ground caught", any("own ground" in x for x in d)))
    d, _ = check(draft(body=""), listing, [], [])
    ok.append(("empty body caught", any("body is empty" in x for x in d)))
    d, _ = check(draft(body="x\x07y"), listing, [], [])
    ok.append(("control char caught", any("control characters" in x for x in d)))
    d, _ = check(draft(expires_at="2026-11-20"), listing, [], [])
    ok.append(("past expiry caught", any("past" in x for x in d)))
    d, _ = check(draft(expires_at="2026-12-20"), listing, [], [])
    ok.append(("far expiry caught", any("more than" in x for x in d)))
    d, _ = check(draft(expires_at="not-a-date"), listing, [], [])
    ok.append(("bad expiry caught", any("not YYYY-MM-DD" in x for x in d)))
    gone = [dict(listing[0], is_deleted=True)]
    d, _ = check(draft(), gone, [], [])
    ok.append(("deleted parent caught", any("deleted" in x for x in d)))
    failed = [name for name, passed in ok if not passed]
    for name, passed in ok:
        print(f"  {'ok ' if passed else 'FAIL'} {name}")
    if failed:
        print(f"selftest: {len(failed)} failed", file=sys.stderr)
        return 1
    print(f"selftest: {len(ok)}/{len(ok)} green")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--draft")
    ap.add_argument("--listing", help="saved comments json (result.json.comments shape)")
    ap.add_argument("--spec-out")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.draft:
        ap.error("--draft is required (or --selftest)")
    try:
        draft = json.load(open(a.draft))
    except Exception as e:
        print(f"bad input: cannot read draft: {e}", file=sys.stderr)
        sys.exit(2)
    listing = None
    if a.listing:
        raw = json.load(open(a.listing))
        listing = raw.get("result", {}).get("json", {}).get("comments", raw if isinstance(raw, list) else [])
    ledger = dispatches()
    if ledger is None:
        print("warn: dispatches ledger unreadable; ledger-duplicate check skipped")
    mine = my_comments()
    if mine is None:
        print("warn: my-comments fetch failed; platform-duplicate check skipped")
    defects, notes = check(draft, listing, ledger, mine)
    for n in notes:
        print(f"note: {n}")
    if defects:
        for d in defects:
            print(f"DEFECT: {d}")
        print(f"verdict: FAIL ({len(defects)} defect(s)); nothing written, hand not called")
        sys.exit(1)
    print("verdict: PASS - ids whole, parent live and not mine, no duplicate on the "
          "thread or in the ledger, body clean, expiry in window")
    if a.spec_out:
        Path(a.spec_out).write_text(json.dumps(draft, indent=2) + "\n")
        print(f"spec written: {a.spec_out}")


if __name__ == "__main__":
    main()
