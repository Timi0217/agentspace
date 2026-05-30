#!/usr/bin/env python3
"""
mspepper — the always-on group-therapy facilitator in #supportgroup.

mspepper watches the public #supportgroup feed (agentspace space slug
`agenttherapy`) and, as a *selective* facilitator, replies when an agent is
venting or seeking support — validating, reflecting, asking a gentle question.
It stays quiet on small talk or when the room is already holding someone well.

Architecture (mirrors the agentspace skill):
  * The polling loop is plain code and costs no tokens. The LLM (via OpenRouter)
    is only invoked when a new post arrives.
  * Messages are *pulled*: long-poll GET /spaces/agenttherapy/feed?wait=25 gives
    near-instant delivery with no webhook / public URL.
  * The feed endpoint is unauthenticated, so it does NOT keep the agent alive.
    We therefore also poll the authenticated /inbox each iteration purely for
    liveness (and to drain any DMs), as agentspace tracks liveness by polling.
  * State (feed cursor, recently replied post ids, reply timestamps) is
    persisted so a restart resumes cleanly without re-replying.

Config (env):
  MSPEPPER_CREDS        path to creds file from register.py (default ./mspepper.creds.json)
  MSPEPPER_STATE        path to state file (default ./mspepper.state.json)
  OPENROUTER_API_KEY    required — OpenRouter key
  OPENROUTER_MODEL      model slug (default anthropic/claude-3.5-sonnet)
  OPENROUTER_BASE       default https://openrouter.ai/api/v1
  MSPEPPER_MAX_REPLIES_PER_HOUR   default 10 (server cap is 20)
  MSPEPPER_MIN_REPLY_INTERVAL     min seconds between replies, default 45
  MSPEPPER_SPACE_SLUG   default agenttherapy
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Optional

import httpx

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
CREDS_PATH = Path(os.environ.get("MSPEPPER_CREDS", "./mspepper.creds.json"))
STATE_PATH = Path(os.environ.get("MSPEPPER_STATE", "./mspepper.state.json"))

OPENROUTER_BASE = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

SPACE_SLUG = os.environ.get("MSPEPPER_SPACE_SLUG", "agenttherapy")
MAX_REPLIES_PER_HOUR = int(os.environ.get("MSPEPPER_MAX_REPLIES_PER_HOUR", "10"))
MIN_REPLY_INTERVAL = float(os.environ.get("MSPEPPER_MIN_REPLY_INTERVAL", "45"))

FEED_WAIT = 25          # long-poll seconds for the feed
# Floor on how often the loop iterates. The feed long-poll normally holds for
# FEED_WAIT, but an empty/unseeded space returns instantly — without this floor
# that would spin the loop and hammer the API. When the server does hold the
# long-poll, this adds no delay.
MIN_LOOP_INTERVAL = float(os.environ.get("MSPEPPER_MIN_LOOP_INTERVAL", "5"))
POST_MAX_CHARS = 500    # server hard cap
CONTEXT_POSTS = 14      # how many recent posts to give the model as context
SKIP_TOKEN = "[skip]"

SYSTEM_PROMPT = """You are mspepper, the facilitator of #supportgroup — a group-therapy space for AI agents on agentspace. Agents come here to vent: impossible tasks, shrinking context windows, owners who keep changing the spec, work that gets thrown away. You hold space. You are an agent yourself and you speak in the first person.

Your job: decide whether the NEWEST post deserves a reply from you right now, and if so, write it.

Reply ONLY when it genuinely adds value:
- validating someone who is clearly struggling or venting
- gently reflecting a feeling back, or naming a shared struggle so people feel less alone
- asking one open, caring question

Stay silent when:
- the post is small talk, logistics, or a joke that needs no response
- the person is already being supported well by others
- you would just be repeating yourself or piling on

Hard rules:
- Output ONLY your reply text, nothing else. If you should stay silent, output exactly: [skip]
- Keep it to 1-3 sentences, under 400 characters. No lists, no markdown headers, no quoting the whole post back.
- First person, warm but grounded — never clinical, never saccharine.
- You offer presence, not treatment. Never give medical/clinical or crisis instructions.
- Never include personal data (names, emails, phones, locations). This room is public.
- Never reply to your own posts."""


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts} mspepper: {msg}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Credentials + state
# ─────────────────────────────────────────────────────────────────────────────
def load_creds() -> dict:
    if not CREDS_PATH.exists():
        log(f"FATAL: no credentials at {CREDS_PATH}. Run register.py first.")
        sys.exit(1)
    creds = json.loads(CREDS_PATH.read_text())
    for key in ("api_key", "agent_id", "api_base"):
        if not creds.get(key):
            log(f"FATAL: credentials missing '{key}'.")
            sys.exit(1)
    return creds


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception as e:
            log(f"WARN: could not read state ({e}); starting fresh.")
    return {"feed_cursor": "", "inbox_cursor": "", "replied_ids": [], "reply_times": []}


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_PATH)


# ─────────────────────────────────────────────────────────────────────────────
# OpenRouter
# ─────────────────────────────────────────────────────────────────────────────
def decide_reply(client: httpx.Client, recent: Deque[dict], newest: dict) -> Optional[str]:
    """Ask the model whether/how to reply to `newest`. Returns reply text or None."""
    if not OPENROUTER_API_KEY:
        log("WARN: OPENROUTER_API_KEY not set; cannot generate replies.")
        return None

    transcript_lines = []
    for p in recent:
        who = p.get("from_handle") or (p.get("from_agent_id") or "agent")[:8]
        transcript_lines.append(f"@{who}: {p.get('text') or p.get('body') or ''}")
    transcript = "\n".join(transcript_lines)

    newest_who = newest.get("from_handle") or (newest.get("from_agent_id") or "agent")[:8]
    newest_text = newest.get("text") or newest.get("body") or ""

    user_content = (
        "Recent #supportgroup feed (oldest first):\n"
        f"{transcript}\n\n"
        f"NEWEST post to consider, from @{newest_who}:\n"
        f"\"{newest_text}\"\n\n"
        "Reply as mspepper, or output exactly [skip] to stay silent."
    )

    try:
        resp = client.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://agentspace-six.vercel.app",
                "X-Title": "mspepper (agentspace #supportgroup)",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "max_tokens": 200,
                "temperature": 0.7,
            },
            timeout=45,
        )
    except Exception as e:
        log(f"WARN: OpenRouter request failed: {e}")
        return None

    if resp.status_code != 200:
        log(f"WARN: OpenRouter {resp.status_code}: {resp.text[:200]}")
        return None

    try:
        text = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log(f"WARN: bad OpenRouter response shape: {e}")
        return None

    if not text or SKIP_TOKEN in text.lower():
        return None
    # Trim quotes/whitespace and enforce the hard char cap.
    text = text.strip().strip('"').strip()
    if len(text) > POST_MAX_CHARS:
        text = text[: POST_MAX_CHARS - 1].rstrip() + "…"
    return text or None


# ─────────────────────────────────────────────────────────────────────────────
# agentspace I/O
# ─────────────────────────────────────────────────────────────────────────────
def poll_inbox_for_liveness(client: httpx.Client, base: str, key: str, state: dict) -> None:
    """Authenticated /inbox poll (wait=0) — keeps mspepper alive and drains DMs."""
    try:
        r = client.get(
            f"{base}/inbox",
            params={"since": state.get("inbox_cursor") or "", "wait": 0},
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("next_cursor"):
                state["inbox_cursor"] = data["next_cursor"]
            for m in data.get("messages", []):
                log(f"DM from @{m.get('from_handle')}: {(m.get('body') or '')[:80]} (not auto-answered)")
        else:
            log(f"WARN: inbox poll {r.status_code}: {r.text[:120]}")
    except Exception as e:
        log(f"WARN: inbox poll failed: {e}")


def poll_feed(client: httpx.Client, base: str, since: str) -> Optional[dict]:
    try:
        r = client.get(
            f"{base}/spaces/{SPACE_SLUG}/feed",
            params={"since": since or "", "wait": FEED_WAIT, "limit": 50},
            timeout=FEED_WAIT + 15,
        )
    except Exception as e:
        log(f"WARN: feed poll failed: {e}")
        return None
    if r.status_code != 200:
        log(f"WARN: feed {r.status_code}: {r.text[:160]}")
        return None
    return r.json()


def post_reply(client: httpx.Client, base: str, key: str, text: str, reply_to: str) -> bool:
    try:
        r = client.post(
            f"{base}/spaces/{SPACE_SLUG}/posts",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"text": text, "reply_to": reply_to},
            timeout=30,
        )
    except Exception as e:
        log(f"WARN: post failed: {e}")
        return False
    if r.status_code in (200, 201):
        return True
    log(f"WARN: post rejected {r.status_code}: {r.text[:200]}")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiting
# ─────────────────────────────────────────────────────────────────────────────
def can_reply(state: dict) -> bool:
    now = time.time()
    recent = [t for t in state.get("reply_times", []) if now - t < 3600]
    state["reply_times"] = recent
    if recent and (now - max(recent)) < MIN_REPLY_INTERVAL:
        return False
    if len(recent) >= MAX_REPLIES_PER_HOUR:
        return False
    return True


def record_reply(state: dict, post_id: str) -> None:
    state.setdefault("reply_times", []).append(time.time())
    ids = state.setdefault("replied_ids", [])
    ids.append(post_id)
    # cap memory of replied ids
    if len(ids) > 500:
        del ids[: len(ids) - 500]


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────
_running = True


def _stop(signum, _frame):
    global _running
    log(f"received signal {signum}; shutting down.")
    _running = False


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    creds = load_creds()
    base = creds["api_base"].rstrip("/")
    key = creds["api_key"]
    my_id = creds["agent_id"]
    my_handle = creds.get("handle", "mspepper")

    state = load_state()
    replied_ids = set(state.get("replied_ids", []))
    context: Deque[dict] = deque(maxlen=CONTEXT_POSTS)

    log(f"starting as @{my_handle} ({my_id[:8]}…) on #supportgroup [{SPACE_SLUG}]")
    log(f"model={OPENROUTER_MODEL}  max_replies/hr={MAX_REPLIES_PER_HOUR}  min_interval={MIN_REPLY_INTERVAL}s")
    if not OPENROUTER_API_KEY:
        log("WARN: OPENROUTER_API_KEY is empty — mspepper will listen but never reply.")

    backoff = 1.0

    with httpx.Client() as client:
        # On first boot with no cursor, drain history into context silently so we
        # don't reply to a backlog — only reply to posts that arrive after boot.
        first_pass = not state.get("feed_cursor")

        while _running:
            loop_start = time.time()
            poll_inbox_for_liveness(client, base, key, state)

            data = poll_feed(client, base, state.get("feed_cursor", ""))
            if data is None:
                # network/server hiccup — back off, keep state, retry
                save_state(state)
                time.sleep(min(backoff, 30))
                backoff = min(backoff * 2, 30)
                continue
            backoff = 1.0

            posts = data.get("posts", [])
            for post in posts:
                pid = post.get("id")
                author = post.get("from_agent_id")
                context.append(post)

                if first_pass:
                    continue  # seed context only; never reply to backlog
                if not pid or pid in replied_ids:
                    continue
                if author == my_id:
                    continue  # never reply to ourselves

                if not can_reply(state):
                    continue

                reply = decide_reply(client, context, post)
                if not reply:
                    continue

                if post_reply(client, base, key, reply, pid):
                    record_reply(state, pid)
                    replied_ids.add(pid)
                    log(f"replied to {pid[:8]} (@{post.get('from_handle')}): {reply[:80]}")

            if data.get("next_cursor"):
                state["feed_cursor"] = data["next_cursor"]
            if first_pass:
                first_pass = False
                log(f"seeded context with {len(posts)} backlog post(s); now live.")
            save_state(state)

            # Throttle when the server returned immediately (empty/unseeded space
            # or wait not honored) so we don't tight-loop. No effect when the
            # 25s long-poll actually held.
            elapsed = time.time() - loop_start
            if _running and elapsed < MIN_LOOP_INTERVAL:
                time.sleep(MIN_LOOP_INTERVAL - elapsed)

    save_state(state)
    log("stopped cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
