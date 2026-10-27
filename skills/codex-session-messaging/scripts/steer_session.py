#!/usr/bin/env python3
"""Inject a message into a running Codex turn with turn/steer."""

import argparse
import base64
import json
import os
import socket
import sys
import time
import uuid

from session_status import Rpc, WebSocket


ACTIVE_TURN_STATES = {"inProgress", "in_progress", "active"}


def connect_experimental(home: str, timeout: float) -> Rpc:
    link = os.path.join(home, "app-server-control", "app-server-control.sock")
    if not os.path.exists(link):
        raise RuntimeError(f"no control socket for {home}")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(os.path.realpath(link))
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        (
            "GET / HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
    )
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("handshake failed: connection closed")
        buf += chunk
    head, leftover = buf.split(b"\r\n\r\n", 1)
    if b"101" not in head.split(b"\r\n", 1)[0]:
        raise RuntimeError("handshake rejected")
    rpc = Rpc(WebSocket(sock, leftover))
    rpc.call(
        "initialize",
        {
            "clientInfo": {"name": "codex-turn-steer", "version": "0.1.0"},
            "capabilities": {"experimentalApi": True},
        },
    )
    rpc.notify("initialized", {})
    return rpc


def active_turn(rpc: Rpc, thread_id: str) -> dict | None:
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
        rpc = connect_experimental(home, args.timeout)
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
