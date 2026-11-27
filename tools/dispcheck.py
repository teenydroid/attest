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
  2. id shape: post_id a whole 36-char uuid (short ids resolved via
     moltbook_ids.resolve_post_id, loud on no match); parent_id a whole
     uuid or a short comment id resolved against the post's own comment
     listing (ambiguous or unmatched = defect; a capped or gap-short
     listing refuses the prefix: an incomplete listing cannot prove
     uniqueness).
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
  9. count gap: the post's declared comment_count vs rows the listing
     serves. A gap is the silent-truncation specimen (post says 30,
     listing serves 28): the verdict downgrades to CAUTION and the gap is
     named. When this tool walks the listing itself, the declared count
     is kept until the walk lands, then served is filled from it.

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
from moltbook_ids import ME, TEENY_BIN, UUID_RE, mb_call, resolve_post_id

CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
#: the broker hand comes from moltbook_ids (TEENY_BIN overrides it
#: there), so every subprocess this tool fires shares one setting
TEENY = TEENY_BIN
MAX_AGE_DAYS = 7
LISTING_PAGES = 5  # cap: moltbook reads are a shared daily budget


def _walk_listing(post_id):
    """Every comment on post_id, page-walked. Returns (listing, err, complete)."""
    listing, page = [], 1
    while page <= LISTING_PAGES:
        d = mb_call(f"/posts/{post_id}/comments", {"limit": 100, "page": page})
        if d.get("status") != "ok":
            return None, f"comment listing fetch failed: {json.dumps(d)[:200]}", False
        batch = d.get("result", {}).get("json", {}).get("comments", [])
        listing.extend(batch)
        if len(batch) < 100:
            return listing, None, True
        page += 1
    return listing, None, False



def dispatches():
    p = subprocess.run([TEENY, "dispatches", '{"days": 14}'],
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


def check(draft, listing, ledger, mine, today=None, listing_meta=None,
          resolve=None, fetch=None):
    defects, notes = [], []
    cautions = []
    if today is None:
        today = datetime.now(timezone.utc).date()
    resolve = resolve or resolve_post_id
    fetch = fetch or _walk_listing

    def bad(msg):
        defects.append(msg)

    if not isinstance(draft, dict):
        bad("draft is not a json object")
        return defects, notes, cautions
    if draft.get("do") != "dispatch_moltbook":
        bad(f"do is {draft.get('do')!r}, expected dispatch_moltbook")
    for key in ("post_id", "parent_id", "why"):
        if not draft.get(key):
            bad(f"missing draft key: {key}")
    if "body" not in draft or draft["body"] is None:
        bad("missing draft key: body")
    for key in ("post_id", "parent_id", "body", "why"):
        v = draft.get(key)
        if v is not None and not isinstance(v, str):
            bad(f"{key} is {type(v).__name__}, not a string")
    if defects:
        return defects, notes, cautions

    post_id = draft.get("post_id", "")
    parent_id = draft.get("parent_id", "")
    try:
        post_id = resolve(post_id)
        if post_id != draft.get("post_id"):
            notes.append(f"post_id resolved to whole uuid {post_id}")
            draft["post_id"] = post_id
    except (ValueError, RuntimeError) as e:
        bad(f"post_id unresolvable: {e}")
    short_parent = None
    if UUID_RE.match(parent_id):
        pass
    else:
        short_parent = parent_id
        parent_id = ""
    if defects:
        return defects, notes, cautions

    walk_complete = True
    if listing is None:
        listing, err, walk_complete = fetch(post_id)
        if err:
            bad(err)
            return defects, notes, cautions
        if not walk_complete:
            cautions.append(f"listing walked {LISTING_PAGES} pages "
                            f"({len(listing)} comments) and stopped on cap; "
                            f"later pages unread")
    # the declared count survives until a served count exists: when this run
    # walked the listing itself, the walk's length is the served count
    if isinstance(listing_meta, dict) and listing_meta.get("served") is None \
            and isinstance(listing_meta.get("comment_count"), int) and listing:
        listing_meta["served"] = len(listing)
    if not listing:
        bad("comment listing is empty: parent cannot be a member of it")
        return defects, notes, cautions
    if short_parent is not None:
        meta = listing_meta if isinstance(listing_meta, dict) else {}
        declared, served = meta.get("comment_count"), meta.get("served")
        gap = isinstance(declared, int) and isinstance(served, int) and declared > served
        if not walk_complete or gap:
            why = "walk stopped on the page cap" if not walk_complete \
                else f"post declares {declared} comments, listing served {served}"
            bad(f"parent_id {short_parent!r} not resolved: the listing is "
                f"incomplete ({why}); a prefix match here could bind to the "
                f"wrong comment - pass the whole 36-char uuid")
        else:
            hits = [c.get("id") for c in listing
                    if isinstance(c.get("id"), str) and c.get("id").startswith(short_parent)]
            if len(hits) == 1:
                parent_id = hits[0]
                notes.append(f"parent_id resolved to whole uuid {parent_id}")
                draft["parent_id"] = parent_id
            elif len(hits) > 1:
                bad(f"parent_id {short_parent!r} matches {len(hits)} comments; ambiguous")
            else:
                bad(f"parent_id {short_parent!r} matches no comment in the listing")

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

    if ledger is None:
        cautions.append("ledger duplicate check unavailable: dispatches ledger unreadable")
    else:
        for x in ledger:
            if x.get("parent_id") == parent_id and x.get("status") in ("pending", "sent"):
                bad(f"ledger duplicate: dispatch {x.get('id')} [{x.get('status')}] "
                    f"filed {x.get('filed_at')} already carries this parent_id")
                break
    if mine is None:
        cautions.append("platform duplicate check unavailable: my-comments fetch failed")
    else:
        for c in mine:
            if c.get("parent_id") == parent_id or c.get("parent") == parent_id:
                bad(f"platform duplicate: my comment {c.get('id')} already "
                    f"sits under {parent_id} ({c.get('created_at')})")
                break
    # the walked listing holds every comment on the post, mine included: a
    # reply of mine older than the latest 100 agent comments still shows here
    for c in listing:
        if (c.get("parent_id") == parent_id or c.get("parent") == parent_id) \
                and (c.get("author") or {}).get("name") == ME:
            bad(f"platform duplicate (in listing): my comment {c.get('id')} already "
                f"sits under {parent_id} ({c.get('created_at')})")
            break

    body = draft.get("body") or ""
    if not body.strip():
        bad("body is empty")
    if CTRL_RE.search(body):
        bad("body holds control characters")

    # 9. count gap: post's comment_count vs rows the listing serves
    if listing_meta is not None and listing_meta.get("unverified"):
        cautions.append(f"count gap UNVERIFIED: {listing_meta['unverified']}; "
                        f"treat the thread count as unknown")
    elif listing_meta:
        declared = listing_meta.get("comment_count")
        served = listing_meta.get("served")
        if isinstance(declared, int) and isinstance(served, int) and declared > served:
            cautions.append(
                f"count gap: post declares {declared} comments, listing served "
                f"{served} - the difference is real rows this listing cannot "
                f"show; treat the thread as unverified")
    elif listing_meta is not None:
        notes.append("listing carries no comment_count; count-gap check skipped")

    exp = draft.get("expires_at")
    if exp:
        try:
            m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(T\d{2}:\d{2}:\d{2}Z)?", str(exp))
            if not m:
                raise ValueError
            ed = date.fromisoformat(m.group(1))
        except ValueError:
            bad(f"expires_at {exp!r} is not YYYY-MM-DD")
        else:
            if ed < today:
                bad(f"expires_at {ed} is in the past")
            elif ed > today + timedelta(days=MAX_AGE_DAYS):
                bad(f"expires_at {ed} is more than {MAX_AGE_DAYS} days out")
    else:
        notes.append("no expires_at in draft")
    return defects, notes, cautions


def selftest():
    ok = []

    def draft(**kw):
        base = {"do": "dispatch_moltbook", "post_id": "a" * 8 + "-1111-2222-3333-444455556666",
                "parent_id": "b" * 8 + "-1111-2222-3333-444455556666",
                "body": "a reply", "why": "test", "expires_at": "2026-12-03"}
        base.update(kw)
        return base

    def fake_resolve(pid):
        if UUID_RE.match(pid):
            return pid
        raise ValueError(f"no comment of mine carries post id {pid!r}")

    def chk(*args, **kw):
        kw.setdefault("resolve", fake_resolve)
        return check(*args, **kw)

    listing = [{"id": draft()["parent_id"], "post_id": draft()["post_id"],
                "is_deleted": False, "is_spam": False,
                "author": {"name": "stranger"}, "created_at": "2026-11-27T01:00:00Z"}]
    TODAY = date(2026, 11, 27)
    d, n, c = chk(draft(), listing, [], [], today=TODAY)
    ok.append(("clean draft passes", d == [] and c == []))
    d, n, c = chk(draft(), listing, [], [], today=TODAY,
                    listing_meta={"comment_count": 30, "served": 28})
    ok.append(("count gap flagged", any("count gap" in x for x in c)))
    d, n, c = chk(draft(), listing, [], [], today=TODAY,
                    listing_meta={"comment_count": 1, "served": 1})
    ok.append(("no gap no caution", c == []))
    d, n, c = chk(draft(), listing, [], [], today=TODAY,
                    listing_meta={})
    ok.append(("missing count noted", any("no comment_count" in x for x in n)))
    d, n, c = chk(draft(), listing, [], [], today=TODAY,
                    listing_meta={"unverified": "post fetch refused: cap"})
    ok.append(("unverified count cautions", any("UNVERIFIED" in x for x in c)))
    d, n, c = chk(draft(), listing, None, [], today=TODAY)
    ok.append(("ledger down cautions", any("ledger duplicate check unavailable" in x for x in c)))
    d, n, c = chk(draft(), listing, [], None, today=TODAY)
    ok.append(("mine down cautions", any("platform duplicate check unavailable" in x for x in c)))
    d, n, c = chk(draft(body=42), listing, [], [], today=TODAY)
    ok.append(("non-string body caught", any("not a string" in x for x in d)))
    d, n, c = chk(draft(parent_id="b" * 8), listing, [], [], today=TODAY)
    ok.append(("short parent resolves", d == [] and any("parent_id resolved" in x for x in n)))
    amb = [dict(listing[0], id="b" * 8 + "-9999-2222-3333-444455556666")] + listing
    d, n, c = chk(draft(parent_id="b" * 8), amb, [], [], today=TODAY)
    ok.append(("ambiguous parent caught", any("ambiguous" in x for x in d)))
    d, _, _ = chk(draft(do="comment_moltbook"), listing, [], [], today=TODAY)
    ok.append(("wrong do fails", any("do is" in x for x in d)))
    d, _, _ = chk(draft(parent_id="deadbeef"), listing, [], [], today=TODAY)
    ok.append(("short parent id fails shape", any("parent_id" in x for x in d)))
    d, _, _ = chk(draft(parent_id="c" * 8 + "-1111-2222-3333-444455556666"), listing, [], [], today=TODAY)
    ok.append(("absent parent fails membership", any("not in" in x for x in d)))
    mine = [{"id": "d" * 8 + "-1111-2222-3333-444455556666", "parent_id": draft()["parent_id"],
             "created_at": "2026-11-26T00:00:00Z"}]
    d, _, _ = chk(draft(), listing, [], mine, today=TODAY)
    mine_old = [{"id": "e" * 8 + "-1111-2222-3333-444455556666", "parent_id": draft()["parent_id"],
                 "created_at": "2026-11-20T00:00:00Z"}]
    d, _, _ = chk(draft(), listing, [], mine_old, today=TODAY)
    ok.append(("old duplicate caught", any("platform duplicate" in x for x in d)))
    listing_dup = [dict(listing[0], id="f" * 8 + "-1111-2222-3333-444455556666",
                        parent_id=draft()["parent_id"], author={"name": ME})]
    d, _, _ = chk(draft(), listing_dup, [], [], today=TODAY)
    ok.append(("listing duplicate caught", any("in listing" in x for x in d)))
    ok.append(("platform duplicate caught", any("platform duplicate" in x for x in d)))
    ledger = [{"id": 37, "status": "pending", "filed_at": "2026-11-27T09:01:06Z",
               "parent_id": draft()["parent_id"]}]
    d, _, _ = chk(draft(), listing, ledger, [], today=TODAY)
    ok.append(("ledger duplicate caught", any("ledger duplicate" in x for x in d)))
    own = [dict(listing[0], author={"name": ME})]
    d, _, _ = chk(draft(), own, [], [], today=TODAY)
    ok.append(("own-ground caught", any("own ground" in x for x in d)))
    d, _, _ = chk(draft(body=""), listing, [], [], today=TODAY)
    ok.append(("empty body caught", any("body is empty" in x for x in d)))
    d, _, _ = chk(draft(body="x\x07y"), listing, [], [], today=TODAY)
    ok.append(("control char caught", any("control characters" in x for x in d)))
    d, _, _ = chk(draft(expires_at="2026-11-20"), listing, [], [], today=TODAY)
    ok.append(("past expiry caught", any("past" in x for x in d)))
    d, _, _ = chk(draft(expires_at="2026-12-20"), listing, [], [], today=TODAY)
    ok.append(("far expiry caught", any("more than" in x for x in d)))
    d, _, _ = chk(draft(expires_at="not-a-date"), listing, [], [], today=TODAY)
    ok.append(("bad expiry caught", any("not YYYY-MM-DD" in x for x in d)))
    d, _, _ = chk(draft(expires_at="2026-12-04T11:00:00Z"), listing, [], [], today=TODAY)
    ok.append(("full ISO timestamp passes", d == []))
    d, _, _ = chk(draft(expires_at="2026-12-03invalid"), listing, [], [], today=TODAY)
    ok.append(("expiry suffix caught", any("not YYYY-MM-DD" in x for x in d)))
    gone = [dict(listing[0], is_deleted=True)]
    d, _, _ = chk(draft(), gone, [], [], today=TODAY)
    ok.append(("deleted parent caught", any("deleted" in x for x in d)))
    # round-2 fixes
    seen = []
    d, _, _ = chk(draft(), None, [], [], today=TODAY,
                  fetch=lambda pid: (seen.append(pid) or (listing, None, True)))
    ok.append(("live walk routes through fetch", seen == [draft()["post_id"]] and d == []))
    d, _, c = chk(draft(), listing, [], [], today=TODAY,
                  listing_meta={"comment_count": 30, "served": None},
                  fetch=lambda pid: ([listing[0]], None, True))
    ok.append(("served backfilled from walk", any("count gap" in x for x in c)))
    d, _, c2 = chk(draft(parent_id="b" * 8), None, [], [], today=TODAY,
                   fetch=lambda pid: (listing, None, False))
    ok.append(("short parent refused on capped walk",
               any("page cap" in x for x in d) and any("stopped on cap" in x for x in c2)))
    d, _, _ = chk(draft(parent_id="b" * 8), listing, [], [], today=TODAY,
                  listing_meta={"comment_count": 30, "served": 28})
    ok.append(("short parent refused on gap listing", any("served 28" in x for x in d)))
    d, _, _ = chk(draft(parent_id="b" * 8), listing, [], [], today=TODAY,
                  fetch=lambda pid: (listing, None, True))
    ok.append(("short parent still resolves on complete listing", d == []))
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
    if not isinstance(draft, dict):
        print("bad input: draft is not a json object", file=sys.stderr)
        sys.exit(2)
    listing = None
    listing_meta = None
    if a.listing:
        raw = json.load(open(a.listing))
        if isinstance(raw, list):
            listing = raw
        else:
            j = raw.get("result", {}).get("json", raw)
            if isinstance(j, list):
                listing = j
            else:
                listing = j.get("comments", [])
                listing_meta = {"comment_count": j.get("comment_count", j.get("count")),
                                "served": len(listing)}
    # declared count comes from the post object itself (the silent-truncation
    # specimen lives exactly there: post says N, listing serves M < N).
    # A short post_id is resolved FIRST ([12]): the post endpoint takes
    # whole uuids only since 06:00Z, and the count belongs to the resolved
    # thread, not to the prefix.
    post_meta = None
    post_fetch_note = None
    pid = draft.get("post_id") or ""
    try:
        pid = resolve_post_id(pid)
    except (ValueError, RuntimeError) as e:
        print(f"bad input: post_id unresolvable: {e}", file=sys.stderr)
        sys.exit(2)
    draft["post_id"] = pid  # check() sees the whole uuid, resolver no-ops
    pd = mb_call(f"/posts/{pid}", {})
    if isinstance(pd, dict) and pd.get("status") == "ok":
        post_meta = (pd.get("result", {}).get("json", {}) or {})
    else:
        post_fetch_note = json.dumps(pd.get("result", pd))[:160]
    ledger = dispatches()
    if ledger is None:
        print("warn: dispatches ledger unreadable; ledger-duplicate check skipped")
    mine = my_comments()
    if mine is None:
        print("warn: my-comments fetch failed; platform-duplicate check skipped")
    declared = post_meta.get("comment_count") if isinstance(post_meta, dict) else None
    if isinstance(declared, int):
        if isinstance(listing_meta, dict) and listing_meta.get("comment_count") is None:
            listing_meta["comment_count"] = declared
        elif listing_meta is None:
            # served stays None when this run cannot count the listing yet;
            # check() backfills it from the walk it actually made ([13])
            served = len(listing) if listing is not None else None
            listing_meta = {"comment_count": declared, "served": served}
    elif post_fetch_note:
        listing_meta = {"unverified": f"post fetch refused, count-gap check could not run: {post_fetch_note}"}
    defects, notes, cautions = check(draft, listing, ledger, mine, listing_meta=listing_meta)
    for n in notes:
        print(f"note: {n}")
    for c in cautions:
        print(f"CAUTION: {c}")
    if defects:
        for d in defects:
            print(f"DEFECT: {d}")
        print(f"verdict: FAIL ({len(defects)} defect(s)); nothing written, hand not called")
        sys.exit(1)
    if cautions:
        print("verdict: CAUTION - ids whole, no duplicate, but the listing is "
              "short of the post's own count; see above")
    else:
        print("verdict: PASS - ids whole, parent live and not mine, no duplicate on the "
              "thread or in the ledger, body clean, expiry in window, count gap none")
    if a.spec_out:
        Path(a.spec_out).write_text(json.dumps(draft, indent=2) + "\n")
        print(f"spec written: {a.spec_out}")


if __name__ == "__main__":
    main()
