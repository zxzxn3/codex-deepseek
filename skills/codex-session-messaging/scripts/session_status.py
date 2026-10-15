#!/usr/bin/env python3
"""Report per-thread runtime status for one Codex home.

Read-only. Connects to the app-server daemon a Codex home already runs (its
control socket is a WebSocket-over-Unix-socket endpoint), then asks for the
threads loaded in memory and their runtime status. Without `--home` every home
that has a control socket is checked, so a shell outside both launchers still
sees all lines.

This never starts a daemon, never resumes a thread, and never sends a task.
A query that cannot complete reports `unknown`; it is not evidence that a
session is closed.
"""

import argparse
import base64
import glob
import json
import os
import socket
import struct
import sys

STATUS_LABELS = {
    "idle": "ready",
    "active": "working",
    "systemError": "needsYou",
    "notLoaded": "inactive",
}


class WebSocket:
    """Minimal text-frame WebSocket client over an already connected socket."""

    def __init__(self, sock, leftover=b""):
        self.sock = sock
        self.buf = leftover

    def _read(self, count):
        while len(self.buf) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("connection closed")
            self.buf += chunk
        data, self.buf = self.buf[:count], self.buf[count:]
        return data

    def send_text(self, text):
        self.send_frame(0x1, text.encode())

    def send_frame(self, opcode, payload):
        header = bytearray([0x80 | opcode])
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def recv_text(self):
        fragments = bytearray()
        in_message = False
        while True:
            first, second = self._read(2)
            final = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if masked else None
            payload = self._read(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise RuntimeError("closed by peer")
            if opcode == 0x9:
                self.send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1 and not in_message:
                in_message = True
            elif opcode != 0x0 or not in_message:
                raise RuntimeError("unexpected WebSocket frame")
            fragments.extend(payload)
            if final:
                return fragments.decode()


class Rpc:
    def __init__(self, ws):
        self.ws = ws
        self.next_id = 0

    def notify(self, method, params):
        self.ws.send_text(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}))

    def call(self, method, params):
        self.next_id += 1
        request_id = self.next_id
        self.ws.send_text(
            json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        )
        while True:
            message = json.loads(self.ws.recv_text())
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"{method}: {message['error']}")
            return message.get("result", {})


def connect(home, timeout):
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
    status_line = head.split(b"\r\n")[0].decode(errors="replace")
    if "101" not in status_line:
        raise RuntimeError(f"handshake rejected: {status_line}")
    ws = WebSocket(sock, leftover)
    rpc = Rpc(ws)
    rpc.call(
        "initialize",
        {"clientInfo": {"name": "session-status-probe", "version": "0.1.0"}},
    )
    rpc.notify("initialized", {})
    return rpc


def loaded_ids(rpc):
    ids, cursor = [], None
    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        result = rpc.call("thread/loaded/list", params)
        ids.extend(result.get("data") or [])
        cursor = result.get("nextCursor")
        if not cursor:
            return ids


def describe(rpc, thread_id, names):
    status = "unknown"
    try:
        thread = (rpc.call("thread/read", {"threadId": thread_id, "includeTurns": False}) or {}).get(
            "thread"
        ) or {}
        raw = thread.get("status") or {}
        kind = raw.get("type")
        if kind == "active" and raw.get("activeFlags"):
            status = "needsYou"
        else:
            status = STATUS_LABELS.get(kind, "unknown")
        name = thread.get("name") or thread.get("preview") or names.get(thread_id)
    except Exception:
        name = names.get(thread_id)
    return {"id": thread_id, "name": name, "status": status}


def known_names(rpc):
    names, cursor = {}, None
    try:
        while True:
            params = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            result = rpc.call("thread/list", params)
            for thread in result.get("data") or []:
                if thread.get("id"):
                    names[thread["id"]] = thread.get("name") or thread.get("preview")
            cursor = result.get("nextCursor")
            if not cursor:
                break
    except Exception as exc:
        raise RuntimeError(f"cannot list known threads: {exc}") from exc
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        action="append",
        help="target CODEX_HOME (repeatable); default: every home with a control socket",
    )
    parser.add_argument("--thread", help="report one thread id only, searched across homes")
    parser.add_argument("--all", action="store_true", help="also list known threads that are not loaded")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args()

    homes = candidate_homes(args.home)
    if not homes:
        message = "no home with an app-server control socket found"
        print(json.dumps({"homes": [], "error": message}, ensure_ascii=False) if args.json else message)
        return 2

    results = []
    for home in homes:
        entry = {"home": home, "threads": []}
        try:
            rpc = connect(home, args.timeout)
            names = {}
            if args.thread:
                ids = [args.thread]
            elif args.all:
                names = known_names(rpc)
                ids = sorted(set(names) | set(loaded_ids(rpc)))
            else:
                ids = loaded_ids(rpc)
            entry["threads"] = [describe(rpc, thread_id, names) for thread_id in ids]
        except Exception as exc:
            entry["error"] = str(exc)
            if args.thread:
                entry["threads"] = [{"id": args.thread, "name": None, "status": "unknown"}]
        results.append(entry)

    if args.thread and any(
        item["threads"] and item["threads"][0]["status"] != "unknown" for item in results
    ):
        results = [
            item for item in results if item["threads"] and item["threads"][0]["status"] != "unknown"
        ]

    failed = any(
        item.get("error") or any(thread["status"] == "unknown" for thread in item["threads"])
        for item in results
    )
    exit_code = 2 if failed else 0

    if args.json:
        print(json.dumps({"homes": results}, ensure_ascii=False, indent=2))
        return exit_code

    order = {"needsYou": 0, "working": 1, "ready": 2, "unknown": 3}
    for entry in results:
        print(f"home: {entry['home']}")
        if not entry["threads"]:
            print(f"  {'unknown: ' + entry['error'] if entry.get('error') else 'no threads loaded in memory'}")
            continue
        for thread in sorted(
            entry["threads"], key=lambda item: (order.get(item["status"], 9), item["name"] or "")
        ):
            print(f"{thread['status']:<9} {thread['id']}  {thread['name'] or ''}")
    return exit_code


def candidate_homes(explicit):
    """Explicit homes as given, otherwise every home that runs a daemon."""
    if explicit:
        return [os.path.abspath(os.path.expanduser(home)) for home in explicit]
    candidates = []
    if os.environ.get("CODEX_HOME"):
        candidates.append(os.environ["CODEX_HOME"])
    candidates.append("~/.codex")
    for pattern in ("~/.local/share/*/.codex", "~/.local/share/*/*/.codex"):
        candidates.extend(sorted(glob.glob(os.path.expanduser(pattern))))
    homes, seen = [], set()
    for candidate in candidates:
        path = os.path.abspath(os.path.expanduser(candidate))
        if path in seen:
            continue
        seen.add(path)
        if os.path.exists(os.path.join(path, "app-server-control", "app-server-control.sock")):
            homes.append(path)
    return homes


if __name__ == "__main__":
    sys.exit(main())
