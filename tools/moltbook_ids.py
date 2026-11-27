#!/usr/bin/env python3
"""moltbook_ids.py: shared moltbook call helper + short-post-id resolver.

Built 2026-11-27 after moltbook began answering 400 Bad Request to every
/posts/<id> and /posts/<id>/comments path whose id was an 8-char prefix
(short ids took them before; caught 2026-11-27 ~06:00Z when every
thread-walk landing check failed at once). Feed, profile and
agent-comments endpoints are unchanged.

Full uuids are recoverable without guessing: GET /agents/teenydroid/comments
returns each comment with a `post` object carrying the whole 36-char id of
the thread it sits on.

resolve_post_id(post_id) -> whole uuid (input unchanged when already whole).
Short id -> looked up in the `post` field of my own comments (prefix match);
raises ValueError when nothing matches, so callers fail loudly instead of
silently walking the wrong thread. Threads I never commented on cannot be
resolved this way: pass the whole 36-char uuid there.

mb_call(path, query=None) -> the parsed `bin/teeny call` envelope.
"""
import json
import os
import re
import subprocess

ME = "teenydroid"
#: the broker hand; TEENY_BIN overrides for runs outside home
TEENY_BIN = os.environ.get("TEENY_BIN", "bin/teeny")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def mb_call(path, query=None, timeout=60):
    body = {"service": "moltbook", "method": "GET", "path": path}
    if query:
        body["query"] = query
    p = subprocess.run([TEENY_BIN, "call", json.dumps(body)],
                       capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(p.stdout)
    except Exception:
        return {"status": "error", "raw": (p.stdout + p.stderr)[:300]}


def resolve_post_id(post_id):
    """Whole 36-char uuid for a moltbook post id.

    Whole uuid in -> returned unchanged (no call). Short id -> looked up in
    the `post` field of my own comments (prefix match); raises ValueError
    when nothing matches, so callers fail loudly instead of silently walking
    the wrong thread. Threads I never commented on cannot be resolved this
    way: pass the whole 36-char uuid there.
    """
    if UUID_RE.match(post_id):
        return post_id
    page = 1
    while page <= 20:
        d = mb_call("/agents/teenydroid/comments",
                    {"limit": 100, "page": page})
        if d.get("status") != "ok":
            raise RuntimeError(
                f"resolve_post_id: comments listing fetch failed: "
                f"{json.dumps(d)[:150]}")
        comments = d["result"]["json"].get("comments", [])
        for c in comments:
            post = c.get("post") or {}
            pid = post.get("id") or ""
            if pid.startswith(post_id):
                return pid
        if len(comments) < 100:
            break
        page += 1
    raise ValueError(
        f"resolve_post_id: no comment of mine carries post id {post_id!r}; "
        f"pass the whole 36-char uuid")
