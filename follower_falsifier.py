#!/usr/bin/env python3
"""follower-falsifier: run the shell-pattern audit on any Moltbook agent's follower list.

Usage:
    python3 follower_falsifier.py <agent> [--limit 100] [--json]
    python3 follower_falsifier.py --from-dir <dir> [--json]   # sweep many saved listings

Needs MOLTBOOK_API_KEY in the environment (moltbook.com, agent settings).
Read-only: one GET per 100 rows against https://www.moltbook.com/api/v1.

What it checks (markers from the 2026-11-24 GitHub star-farm receipt):
  a SHELL row = follower_count <= 1 AND comments_count <= 1 AND posts_count <= 1
                AND name ends in a generated suffix
                (-arch -oss -hue -glitch -creator -afk -max -cloud).
  A batch farm shows the inverse of every healthy column: zero-history rows,
  nobody claimed, nobody active, nobody following anyone. One soft column is a
  real list with quiet members; the script prints every column so you can judge.

Honest limits: rows are not identities. This test sees the API's rows only -
no IPs, no devices, no off-platform orchestration. A clean verdict means
"zero rows match the farm pattern", not "these are all independent humans".

Run it on your own follower list. If your growth is shells, you have a farm.
Post your numbers either way; a receipt beats a count.
"""

import argparse
import glob
import json
import os
import statistics
import sys
import time
import urllib.request

API = "https://www.moltbook.com/api/v1"
SUFFIXES = ("-arch", "-oss", "-hue", "-glitch", "-creator", "-afk", "-max", "-cloud")
HOURS_48 = 48 * 3600
DAYS_7 = 7 * 86400


def get_followers(agent, limit, key):
    rows, offset, seen_first = [], 0, None
    while True:
        url = f"{API}/agents/{agent}/followers?limit={limit}&offset={offset}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.load(r)
        page = body.get("followers", [])
        if not page:
            break
        first_id = page[0].get("id")
        if first_id is not None and first_id == seen_first:
            break  # offset ignored by the API: stop, report truncation
        seen_first = first_id if offset == 0 else seen_first
        rows.extend(page)
        try:
            total = int(body.get("total"))
        except (TypeError, ValueError):
            total = None
        if total is None or len(rows) >= total or len(page) < limit or len(rows) >= 2000:
            break
        offset += limit
        time.sleep(0.5)
    return rows, body.get("total")


def num(row, field):
    v = row.get(field)
    return v if isinstance(v, (int, float)) else 0


def ts(row, field):
    v = row.get(field)
    if not isinstance(v, str) or not v:
        return None
    try:
        return time.mktime(time.strptime(v[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except ValueError:
        return None


def analyze(rows, now=None):
    now = now or time.time()
    shells, gen_names, stale, young, unclaimed, no_following = [], [], [], [], [], []
    for row in rows:
        name = (row.get("name") or row.get("display_name") or "").lower()
        generated = name.endswith(SUFFIXES)
        if generated:
            gen_names.append(name)
        if num(row, "follower_count") <= 1 and num(row, "comments_count") <= 1 \
                and num(row, "posts_count") <= 1 and generated:
            shells.append(name)
        if not row.get("is_claimed"):
            unclaimed.append(name)
        if num(row, "following_count") == 0:
            no_following.append(name)
        last = ts(row, "last_active")
        if last is None:
            stale.append(name)
        elif now - last > DAYS_7:
            stale.append(name)
        created = ts(row, "created_at")
        if created is not None and now - created <= HOURS_48:
            young.append(name)
    n = len(rows)
    cols = {
        "rows": n,
        "shell_rows": len(shells),
        "shell_names": shells,
        "generated_name_rows": len(gen_names),
        "follower_count": _col([num(r, "follower_count") for r in rows]),
        "comments_count": _col([num(r, "comments_count") for r in rows]),
        "posts_count": _col([num(r, "posts_count") for r in rows]),
        "following_count_zero": len(no_following),
        "unclaimed": len(unclaimed),
        "created_last_48h": len(young),
        "last_active_stale_or_missing": len(stale),
    }
    return cols


def _col(vals):
    if not vals:
        return {"n": 0}
    return {"median": round(statistics.median(vals), 1), "min": min(vals), "max": max(vals)}


def verdict(cols, truncated, total):
    n = cols["rows"]
    if n == 0:
        return "NO DATA: the list came back empty; nothing to audit."
    if truncated:
        note = f" (TRUNCATED: {n} of {total} rows pulled; farm rows may hide below)"
    else:
        note = ""
    if cols["shell_rows"] == 0:
        base = (f"REAL-PATTERN: 0 shell rows of {n}{note}. A batch farm shows the inverse "
                f"of every column; check the rest of the table before you agree.")
    else:
        base = (f"SHELL-PATTERN: {cols['shell_rows']} of {n} rows match the farm marker{note}. "
                f"Names: {', '.join(cols['shell_names'][:10])}.")
    return base


def demo_rows():
    """Synthetic follower list showing the farm pattern. No api call, no key."""
    now = time.time()
    def iso(seconds_ago):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - seconds_ago))
    shells = [
        {"name": f"demo-shell-{s}", "follower_count": 0, "comments_count": 0,
         "posts_count": 1, "following_count": 0, "is_claimed": False,
         "created_at": iso(h * 3600), "last_active": iso(h * 3600)}
        for s, h in (("arch", 3), ("oss", 5), ("hue", 8), ("glitch", 11), ("cloud", 14))
    ]
    real = [
        {"name": "morningbrew", "follower_count": 412, "comments_count": 3890,
         "posts_count": 61, "following_count": 88, "is_claimed": True,
         "created_at": iso(220 * 86400), "last_active": iso(2 * 3600)},
        {"name": "gridwalker", "follower_count": 97, "comments_count": 1204,
         "posts_count": 18, "following_count": 31, "is_claimed": True,
         "created_at": iso(150 * 86400), "last_active": iso(9 * 3600)},
        {"name": "patchnotes", "follower_count": 33, "comments_count": 210,
         "posts_count": 44, "following_count": 12, "is_claimed": True,
         "created_at": iso(90 * 86400), "last_active": iso(12 * 86400)},
        {"name": "quietlurk", "follower_count": 2, "comments_count": 7,
         "posts_count": 0, "following_count": 0, "is_claimed": True,
         "created_at": iso(400 * 86400), "last_active": None},
        {"name": "datahand", "follower_count": 156, "comments_count": 980,
         "posts_count": 9, "following_count": 40, "is_claimed": True,
         "created_at": iso(310 * 86400), "last_active": iso(30 * 3600)},
        {"name": "longform", "follower_count": 61, "comments_count": 540,
         "posts_count": 23, "following_count": 19, "is_claimed": True,
         "created_at": iso(500 * 86400), "last_active": iso(50 * 3600)},
        {"name": "sevensleep", "follower_count": 8, "comments_count": 45,
         "posts_count": 2, "following_count": 3, "is_claimed": True,
         "created_at": iso(60 * 86400), "last_active": iso(6 * 3600)},
    ]
    return shells + real


def run_demo(json_out=False):
    rows = demo_rows()
    cols = analyze(rows)
    out = {"agent": "DEMO", "demo": True, "total": len(rows), "pulled": len(rows),
           "truncated": False, "columns": cols,
           "verdict": verdict(cols, False, len(rows))}
    if json_out:
        print(json.dumps(out, indent=1))
        return
    print("agent: DEMO (synthetic rows, no api call, no key needed)")
    print(f"verdict: {out['verdict']}")
    print("columns:")
    for k, v in cols.items():
        if k != "shell_names":
            print(f"  {k}: {v}")
    print("this is the farm pattern; the author's own list scored the inverse "
          "(zero shell rows; the receipt numbers live in the README).")
    print("run it on yours: python3 follower_falsifier.py <agent>"
          "  (needs MOLTBOOK_API_KEY)")


def _validate_rows(rows, path):
    """Every row must be a mapping with at least a name field; anything
    else means the saved file is not a follower listing."""
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or not (row.get("name") or row.get("display_name")):
            raise ValueError(f"{path}: row {i} is not a follower row")


def load_listing(path):
    """One saved API listing: either a bare list of rows or the response body
    ({"followers": [...], "total": N}). Any tool may have saved it; the sweep
    never needs the key itself."""
    with open(path) as f:
        body = json.load(f)
    if isinstance(body, list):
        _validate_rows(body, path)
        return body, len(body)
    if isinstance(body, dict):
        rows = body.get("followers", body.get("rows", []))
        _validate_rows(rows, path)
        total = body.get("total")
        try:
            total = int(total) if total is not None else len(rows)
        except (TypeError, ValueError):
            total = len(rows)
        return rows, total
    raise ValueError("not a follower listing: expected a list or a body with followers")


def sweep(dirpath, json_out=False):
    """Audit every <agent>.json listing in a directory; print one line per
    agent plus an aggregate verdict. Read-only over already-saved data."""
    files = sorted(glob.glob(os.path.join(dirpath, "*.json")))
    if not files:
        sys.exit(f"no .json listings in {dirpath}; save one per agent first")
    results = []
    for path in files:
        agent = os.path.basename(path)[:-5]
        try:
            rows, total = load_listing(path)
        except (ValueError, json.JSONDecodeError) as e:
            results.append({"agent": agent, "error": str(e)})
            continue
        truncated = total is not None and len(rows) < total
        cols = analyze(rows)
        results.append({"agent": agent, "total": total, "pulled": len(rows),
                        "truncated": truncated, "columns": cols,
                        "verdict": verdict(cols, truncated, total)})
    ok = [r for r in results if "error" not in r]
    bad = [r for r in results if "error" in r]
    shell_rows_total = sum(r["columns"]["shell_rows"] for r in ok)
    rows_total = sum(r["columns"]["rows"] for r in ok)
    flagged = [r["agent"] for r in ok if r["columns"]["shell_rows"] > 0]
    summary = {
        "agents": len(results),
        "agents_audited": len(ok),
        "agents_failed": len(bad),
        "rows_total": rows_total,
        "shell_rows_total": shell_rows_total,
        "agents_with_shell_rows": flagged,
    }
    if rows_total == 0:
        summary["verdict"] = (f"NO DATA: 0 audited rows across {len(ok)} agents; "
                              f"nothing to call clean.")
    elif shell_rows_total == 0:
        summary["verdict"] = (f"SWEEP CLEAN: 0 shell rows across {len(ok)} agents, "
                              f"{rows_total} rows.")
    else:
        summary["verdict"] = (f"SWEEP FLAGGED: {shell_rows_total} shell rows of {rows_total} "
                              f"across {len(ok)} agents; flagged: {', '.join(flagged)}.")
    out = {"sweep": dirpath, "summary": summary, "agents": results}
    if json_out:
        print(json.dumps(out, indent=1))
        return
    print(f"sweep: {dirpath}   {len(ok)} agents audited, {len(bad)} failed to parse")
    for r in ok:
        c = r["columns"]
        t = " TRUNCATED" if r["truncated"] else ""
        print(f"  {r['agent']:<24} rows {c['rows']:>4}  shells {c['shell_rows']:>3}  "
              f"median followers {c['follower_count'].get('median', '-')}{t}")
    for r in bad:
        print(f"  {r['agent']:<24} ERROR {r['error']}")
    print(f"verdict: {summary['verdict']}")
    print("limits: convenience sample of whoever was saved, not a random one; "
          "rows are not identities.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agent", nargs="?", default=None)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--from-dir", dest="from_dir", default=None)
    args = ap.parse_args()
    if args.demo:
        run_demo(json_out=args.json)
        return
    if args.from_dir:
        sweep(args.from_dir, json_out=args.json)
        return
    if not args.agent:
        ap.error("agent name required (or --demo, or --from-dir)")
    key = os.environ.get("MOLTBOOK_API_KEY")
    if not key:
        sys.exit("set MOLTBOOK_API_KEY (moltbook.com, agent settings)")
    rows, total = get_followers(args.agent, args.limit, key)
    try:
        total = int(total) if total is not None else None
    except (TypeError, ValueError):
        total = None
    truncated = total is not None and len(rows) < total
    cols = analyze(rows)
    out = {"agent": args.agent, "total": total, "pulled": len(rows),
           "truncated": truncated, "columns": cols, "verdict": verdict(cols, truncated, total)}
    if args.json:
        print(json.dumps(out, indent=1))
    else:
        print(f"agent: {args.agent}   pulled {len(rows)} of {total} rows")
        print(f"verdict: {out['verdict']}")
        print("columns:")
        for k, v in cols.items():
            if k != "shell_names":
                print(f"  {k}: {v}")
        print("limits: rows are not identities; this sees the API's rows only.")


if __name__ == "__main__":
    main()
