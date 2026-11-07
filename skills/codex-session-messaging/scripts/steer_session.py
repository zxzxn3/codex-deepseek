#!/usr/bin/env python3
"""Inject a message into a running Codex turn with turn/steer."""

import argparse
import json
import os
import sys
import time
import uuid

from session_status import connect


ACTIVE_TURN_STATES = {"inProgress", "in_progress", "active"}


def active_turn(rpc, thread_id: str) -> dict | None:
    result = rpc.call("thread/turns/list", {"threadId": thread_id, "limit": 10})
    for turn in result.get("data") or []:
        if turn.get("status") in ACTIVE_TURN_STATES:
            return turn
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, help="target CODEX_HOME")
    parser.add_argument("--thread", required=True, help="target thread ID")
    parser.add_argument("--message", help="text to inject")
    parser.add_argument("--message-file", help="read the message from this UTF-8 file")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    if bool(args.message) == bool(args.message_file):
        parser.error("provide exactly one of --message or --message-file")
    if args.message_file:
        try:
            message = open(args.message_file, encoding="utf-8").read()
        except OSError as exc:
            parser.error(str(exc))
    else:
        message = args.message
    if not message.strip():
        parser.error("message must not be empty")

    home = os.path.abspath(os.path.expanduser(args.home))
    try:
        rpc = connect(home, args.timeout, client="codex-turn-steer",
                      capabilities={"experimentalApi": True})
        thread = rpc.call("thread/read", {"threadId": args.thread, "includeTurns": False}).get("thread") or {}
        runtime = thread.get("status") or {}
        status = runtime.get("type")
        if status != "active":
            reason = (
                "target is not working; use codex queue if it is ready"
                if status == "idle"
                else f"target status is {status or 'unknown'}; do not send"
            )
            print(reason, file=sys.stderr)
            return 3
        if runtime.get("activeFlags"):
            print("target needs approval or input; do not steer", file=sys.stderr)
            return 3
        turn = None
        for _ in range(3):
            turn = active_turn(rpc, args.thread)
            if turn:
                break
            time.sleep(0.15)
        if not turn:
            print("target is active but no active turn was readable; recheck status", file=sys.stderr)
            return 4
        result = rpc.call(
            "turn/steer",
            {
                "threadId": args.thread,
                "expectedTurnId": turn["id"],
                "clientUserMessageId": str(uuid.uuid4()),
                "input": [{"type": "text", "text": message, "text_elements": []}],
            },
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    payload = {
        "home": home,
        "thread": args.thread,
        "delivery": "steered",
        "turnId": result.get("turnId"),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Steered {args.thread} in active turn {result.get('turnId')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
